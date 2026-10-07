# Architecture

This document is for people who change convy's code. It describes how the code is laid out and the
rules that hold everywhere in it. How to use convy is in the [README](README.md); why the main choices
were made is in [docs/decisions](docs/decisions/).

## Bird's eye view

convy plays scenarios against an agent. For each attempt it opens a conversation with the agent, lets a
simulated user talk to it, and asks a judge whether each of the scenario's claims holds. The simulated
user and the judge are models; the agent is anything that implements a small interface. A run has a
folder of its own: its specification and status in `run.json`, each attempt in `attempts.jsonl` as soon
as it ends. The report is built from the runs.

```text
convy run ──▶ RunJournal.play ──▶ Bench ──▶ Scenario.outcome ──▶ SimulatedUser ⇄ Conversation (agent)
                   │                                         └─▶ Judge
                   └──▶ results/<agent>/<run>/ ──▶ Runs ──▶ Report ──▶ results/<agent>/<run>/report.html
                                                        └─▶ Comparison ──▶ results/compare/*.html
```

## Code map

All code is in `src/convy/`.

| module | what is there |
|---|---|
| `agent.py` | the agent interface — `Agent`, `Conversation`, `Message`, `Answer`, `Usage`, `NoUsage`, `AgentFailure` — and `TimeLimited` |
| `http.py` | `JsonEndpoint` (JSON over HTTP with retries) and `JsonConnection`, its open connection that a conversation keeps for all its turns; `Tls`, `HttpFailure`, and `JsonAgent`, an agent configured with a URL and a body template |
| `model.py` | the model interface `Model`, `OpenAiModel`, `ModelFailure`, `Models`, which holds the simulated user's model and the judge's, and `Contained`, which turns any error of a model into `ModelFailure` |
| `env.py` | `Env`, the base class for settings read from `.env` and the environment |
| `dialog.py` | `Transcript`, `Turn`, `SimulatedUser`, `Finished`, `Judge`, its decisions `Verdict` and `Claim`, and the attempts without them, `Failed` and `NoVerdict` |
| `scenario.py` | `Scenario` (read from YAML) and the attempt it plays, `Outcome`; `Scenarios`, `Matching` |
| `bench.py` | `Bench`, which runs scenarios against an agent; `Journal`; a run's `RunSpec`, its status (`Running`, `Finished`, `Interrupted`) and `RunJournal`, which writes its folder |
| `report.py`, `pages/` | `Runs`, which reads runs back; `Summary`, a run summed up into view records; the pages: `Report` (a run), `Comparison` (two runs), `Index` (every run), each rendered through a `Template` |
| `fakes.py` | `FakeAgent`, `Echo`, `FakeModel`, `MemoryJournal` |
| `project.py` | `Project`: a user's project — it loads `models.py` and `agents/*.py`, with the project folder on `sys.path` so they import each other, finds scenarios and results, fingerprints the files a run starts with, writes the reports, the index and comparisons, and copies the template; `ProjectAgent` |
| `cli.py` | the `convy` command: `InitCommand`, `RunCommand`, `ResumeCommand`, `ReportCommand`, `CompareCommand`; `Printed`, a journal that prints progress; `Recorded`, a run played as the command shows it, Ctrl+C included; `Invalid`, settings errors shown without the values read; `Rebuilt`, the report written again and shown with the runs it skipped |
| `template/` | the project that `convy init` copies |

`convy run` runs `models.py` once per agent, so each agent gets fresh models; code at the top level
of `models.py` runs that many times.

A user's project holds the files convy loads: `models.py`, `agents/*.py`, `scenarios/*.yaml`, `.env`,
and `results/`, which convy writes. Other modules in it, such as the template's `gateway.py`, are what
those files import.

The public API is `convy.__all__` and the module `convy.fakes`; with them a run can be made from
Python as well as from the command. Everything else may change without notice.

## Invariants

convy follows the ideas of *Elegant Objects* by Yegor Bugayenko, in idiomatic Python. These rules hold
in all of `src/convy/`.

1. **A class stands for a thing in the problem, not an action:** an agent, a conversation, a scenario,
   a judge, a journal. There are no `*Manager`, `*Runner` or `*Parser` classes, no static methods and
   no module-level functions with logic. The one function is `main` in `cli.py`, the command's entry
   point.
2. **Objects do not change after construction.** Classes are `msgspec.Struct` with `frozen=True`. A
   constructor stores its arguments and may reject a value the object cannot represent (ValueError);
   it never does work — no I/O, no computing, no calls to other objects. The check is in
   `__post_init__`, which msgspec also calls on decoding, so a scenario file gets it too; a check that
   depends on the situation, such as whether a certificate file exists, stays in the method that needs
   it.
3. **An interface (`typing.Protocol`) exists only where there are two implementations or more.** There
   are four: `Agent`, `Conversation`, `Model` and `Journal`.
4. **New behaviour is a wrapper, not a flag or a subclass.** `TimeLimited(agent, 600)` is the same agent
   with a time limit on each step: opening a conversation, a turn, closing. Only exceptions inherit, from `Exception`.
5. **"No value" is an empty object, not `None`:** `NoUsage`, `NoVerdict`. It is stored and read like the
   real value, with no type checks: msgspec tags it (`{"type": "no_usage"}`) and restores the right
   class. `None` is allowed only for an optional constructor argument that was not given.
6. **Domain objects become JSON in one place, the run's folder.** Objects have no `json()` or
   `to_dict()` methods. `RunJournal` writes with `msgspec.json.encode`; `Runs` reads back with
   `msgspec.json.decode`. The report's pages embed data of their own: `Report` builds view records for
   the browser from the runs and encodes those.
7. **Outside data is checked where it enters and is typed after that.** Scenarios: `yamlrocks.loads`,
   then `msgspec.convert` into `Scenario`. An agent's answer: encoded and decoded with `msgspec.json`
   as the run's folder will do it, so a wrong one fails its turn instead of the run. Runs:
   `msgspec.json.decode` of `run.json`, whose `format` must be 2, and of `attempts.jsonl` line by line.
   The judge's answer: `"claims"`, one object per claim, each with a `"pass"` of `true` or
   `false`. The environment and the command line: pydantic-settings.
   Pydantic is used only there; every other class is msgspec.
8. **Every interface has a fake** in `fakes.py`, part of the public API. A fake is a simple working
   object, not a mock. Fakes get no methods that exist only for tests; a fake may keep what it collected
   in public fields (`outcomes`, `peak`).
9. **The library does not print or log.** It returns what the command needs to show, such as
   `Runs.broken()`. Only `cli.py` prints and picks the exit code.
10. **Types are checked on data, never on behaviour.** `match` reads data: the closed unions —
    `Message | Finished`, `Usage | NoUsage`, `Verdict | Failed | NoVerdict`, a run's status — and
    records such as `Outcome`.
    Objects with behaviour are called through their interface, not checked for type. The exception is
    input validation: `Project` checks the type of what a project file defines
    (`isinstance(models, Models)`), as outside data is checked where it enters.

**Where convy departs from *Elegant Objects*:**

- **Data has public fields.** `Message`, `Usage`, `Answer`, `Turn`, `Verdict`, `Outcome` and `RunSpec`
  are immutable records with public fields; accessor methods would be noise in Python.
- **A conversation is opened with `async with`**, Python's usual "open, use, close".
- **Three kinds of objects change inside:** a conversation (its session and history), fakes (they count)
  and `MemoryJournal`. They are plain classes, not frozen `Struct`s, and their state never leaves them.
- **The report's page data uses `None`** (`null` in JSON) for numbers nobody reported: it is data for
  the browser, not part of the domain.

## The report

`report.py` makes every number and decision on the pages: the tiles, a scenario's result, a claim's
count, the change between two runs and its colour, whether a change of pass rate is significant, the
groups and order of the rows. The scripts in `pages/` only draw them — how a value looks, the filter,
the scenario window, the theme, the address — and add data as text, never as HTML; agent text goes
through a small Markdown subset built as DOM nodes. A metric is therefore tested with pytest, and the
scripts stay thin enough to need no tests of their own. Each page is one template that carries its
own copy of the shared styles and helpers, so a written page stands alone.

The view records are internal and have no version: one convy version writes the template and the data
into one file, and a page written earlier keeps working on its own. The only durable format is the
run's folder; see [decision 5](docs/decisions/0005-runs.md).

## Cross-cutting concerns

**Concurrency.** Conversations run at the same time, so the whole path is `async`: `asyncio.timeout` for
limits, `asyncio.TaskGroup` for concurrent work, `asyncio.Semaphore` for `--parallel`. Nothing blocks
the event loop except the run's append of one short line per attempt and the rewrite of its small
`run.json`. Durations are measured with `time.monotonic`. Ctrl+C makes `asyncio.run` cancel the
bench; `RunJournal.play` marks the run `interrupted` on that, or on any other error, and re-raises
it.

**Failure.** Three kinds, one rule each:

- `AgentFailure` — the agent failed: the dialogue ends and the attempt is `Failed` without asking the
  judge, so a broken agent cannot pass on what it said before.
- `ModelFailure` — the simulated user's or the judge's model failed after retries, or gave an answer
  convy cannot use: an empty message, or a judge's answer without one decision per claim whose
  `"pass"` is `true` or `false`; or raised any other error, which `Contained` turns into
  `ModelFailure`. The attempt has `NoVerdict` and is left out of the pass rate.
- Configuration errors — raised while loading the project, or a run that cannot be resumed, before any
  request: the command prints them and exits with code 2.

`except Exception` appears in three places: in `scenario.py` around the agent's code — opening a
conversation, a turn, closing it — because a bug there must not stop a run; in `Contained`
(`model.py`) around a model's `reply`, which `Scenario.outcome` wraps both models in, so a bug in a
model is a `ModelFailure`, not the agent's failure or a crashed run; and in `cli.py` around loading
the project, where any error is a configuration error.

**Retries** live only in `JsonConnection`, which `JsonEndpoint` opens; everything that talks HTTP
goes through it. Only requests the service did not process are repeated — 429, 503 and a connection
that could not be made — so an agent never gets the same message twice. A 500, 502, 504 or a read
timeout may come after the service acted on the request, so it is not repeated.

**Secrets.** Keys are `SecretStr` and never printed. A settings error is shown by field and message
only, because pydantic's own text includes every value it read; `Env` also sets
`hide_input_in_errors`, since an agent that reads its settings in `conversation()` fails with that
error into the run's folder; an HTTP error shows the URL without
its query, which may hold a key. Models are written to runs by `name` only,
never as objects, because an object holds request headers with keys.

**Trust.** `convy run` imports the project's Python files and runs them in its own process; see the
[security policy](SECURITY.md). The other way round, nothing an agent says is trusted: the report shows
dialogues only as text, never as HTML.

**Dependencies.** httpx2, msgspec, yamlrocks and pydantic-settings; why these is in
[decision 4](docs/decisions/0004-dependencies.md). Adding a runtime dependency needs an ADR.
