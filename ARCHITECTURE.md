# Architecture

## How a run works

Each YAML scenario describes a user, a task and a list of claims to check. For each attempt,
convy opens a fresh conversation. A simulated user talks to the agent. After the conversation
closes, a judge checks each claim against the dialogue.

```text
convy run → RunJournal.play → Bench.run → Scenario.outcome
                                              ├─ SimulatedUser ⇄ Conversation
                                              └─ Judge
```

Each run has a folder under `results/<agent>/<run>/`. The journal writes the configuration and
status to `run.json` and appends each completed attempt to `attempts.jsonl`. Reports, comparisons
and exports read those files and can run offline.

## Code map

The library lives in `src/convy/`. Its public Python API consists of the names in `convy.__all__`
and the `convy.fakes` module. See [Run from Python](docs/python.md) for a working example.

| Module | Responsibility |
|---|---|
| `cli.py` | Parse commands, print progress and errors, and set exit codes. |
| `project.py`, `env.py` | Load project files and settings, identify the agent build, and write reports and exports. |
| `template/` | Files copied by `convy init`. |
| `agent.py`, `http.py` | Define conversations, answers, token counts and calls. Connect JSON APIs and apply time limits. |
| `model.py`, `dialog.py` | Run the simulated user and judge, record the dialogue and validate judge decisions. |
| `scenario.py` | Load YAML scenarios, play one attempt and score its claims. |
| `bench.py`, `busy.py` | Schedule attempts, limit and retry requests, and record the run. |
| `report.py`, `pages/` | Read journals, calculate metrics, build HTML pages and check for regressions. |
| `tables.py` | Export runs as seven related tables, in memory, CSV or JSON Lines. |
| `fakes.py` | Provide working agents, models, judges and a journal for tests and examples. |

## Invariants

convy follows Yegor Bugayenko's *Elegant Objects* with the Python conventions below.

1. **Name classes after things in the problem.** Examples include a conversation, judge or journal.
   Avoid generic managers, runners and parsers. Keep logic in instance methods. The CLI entry
   point, `main`, is the one module-level function with application logic. Avoid static methods.
2. **Keep domain records immutable.** Use `msgspec.Struct` with `frozen=True` and public fields.
   Constructors store arguments. Use `__post_init__` to reject values a record cannot represent.
   The check also runs when msgspec decodes a record. Put I/O and checks that depend on the
   environment, such as opening a certificate file, in the method that needs them.
3. **Add a protocol when at least two implementations need it.** The five protocols are
   `Agent`, `Conversation`, `Model`, `Journal` and `Judge`.
4. **Add behaviour by wrapping an object.** For example, `TimeLimited(agent, 600)` puts a time
   limit on opening, answering and closing. It implements the same interface as the wrapped agent.
   Avoid behaviour switches and implementation inheritance. Exception classes inherit from
   `Exception`. Use `async with` for the lifetime of a conversation.
5. **Give missing domain values explicit types.** Examples include `NoUsage`, `NotReported`,
   `NoReason` and `NoVerdict`. msgspec tags these records so a reader can restore their types.
   Use `None` for an omitted optional argument, an external JSON null or a missing value in
   report and export data.
6. **Keep storage separate from domain objects.** `RunJournal` writes journal records and
   `Runs` reads them. Keep serialization methods off domain records. Pages and tables have
   their own output formats.
7. **Validate data where it enters convy.** Decode YAML, journals, HTTP replies and settings
   into typed records. Validate agent answers and custom judge decisions against their journal
   types. A judge must return one decision per claim. Use pydantic for settings and msgspec for
   domain records. Handle variable JSON shapes inside the HTTP adapter.
8. **Give each protocol a working fake.** Keep fakes in `convy.fakes` and use them through the
   same interface as the real implementation. A fake can expose what it observed, such as peak
   concurrency. Avoid methods added solely for test setup or inspection.
9. **Keep output in the CLI.** Library methods return data. Only the CLI prints messages and
   chooses the process exit code.
10. **Inspect data and call behaviour through its interface.** Use `match` for records and
    tagged alternatives such as `Verdict`, `Failed` and `NoVerdict`. Check the objects a project
    file supplies when loading it. The CLI also checks the type of an output stream before
    configuring its encoding.

Conversations keep session state. Fakes, the in-memory journal and the request limiter also
keep mutable state. Each bench run gets its own limiters.

## The report

`Scenario.score` applies the required-claim rule, confidence check and claim threshold for the
CLI and both report pages. Journals and exports keep the judge's original decisions.
[Scoring rules](docs/scenarios.md#passing-an-attempt)

`Summary` calculates the numbers for the run report and the index. The index stores summaries
and links to the detailed report for individual attempts and dialogues. Each HTML page embeds
its own data, scripts and styles. Page data is internal because convy writes it alongside the code
that reads it. The journal format and export columns are public contracts.
[Reports](docs/report.md) · [Run format](docs/decisions/0005-runs.md) · [Export columns](docs/results.md)

## Concurrency and retries

`Bench.run` schedules attempts with `asyncio.TaskGroup`. It gives the agent, simulated user and
judge separate instances of `Places`. The agent holds a place while a conversation is open.
The simulated user and judge hold a place for one request attempt. The judge runs after the
agent releases its place. Use monotonic time for durations and the event loop's clock for
request scheduling.

A service raises `Busy` when it refused a request before processing it. The HTTP adapter does
this for 429 and 503. `Places` retries eligible requests within the participant's patience
budget and reduces concurrency after a refusal. A read timeout can occur after the service
acted, so convy treats it as a failure. [Limits](docs/decisions/0007-participant-limits.md) ·
[Retries](docs/decisions/0008-busy-services.md) · [Requests per minute](docs/decisions/0009-requests-per-minute.md)

`RunJournal.play` takes a nonblocking lock on `run.lock` where the filesystem supports it.
If another process holds it, the CLI reports `RunInUse`. The OS releases the lock when the
process exits. If a running attempt is interrupted, the journal keeps completed attempts.
[Resuming a run](docs/runs.md)

## Errors

| What happened | Result |
|---|---|
| The agent failed to open, answer or close | Record a failed attempt. It counts against the pass rate. |
| The agent's service stayed busy | Record `NoVerdict` with stop reason `agent_busy`. Exclude the attempt from the pass rate. |
| The simulated user's model failed or the judge failed to return valid decisions | Record `NoVerdict` with stop reason `model_failure`. Exclude the attempt from the pass rate. |
| The CLI could not load the project or resume the requested run | Report the error and exit with code 2. |

Catch exceptions at the boundary that knows whose code failed. `Scenario` handles agent errors,
`Contained` handles exceptions from the simulated user's model, and `Checked` handles errors from
the judge. The CLI handles errors while loading project code.

## Project code and secrets

A regular CLI run loads `models.py` once per agent. The smoke check uses built-in models.
Project modules run in the convy process and can import other files in their project.

Use `SecretStr` for API keys. Report settings errors by field and message, and omit URL query
strings from diagnostics. Save model names in the journal. Treat agent replies as untrusted
text when rendering HTML. [Security policy](SECURITY.md)

Adding a runtime dependency requires an [architecture decision](docs/decisions/0004-dependencies.md).
