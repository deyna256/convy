# 7. Each participant has its own limit, set in the project's settings

**Status:** Accepted

## Context

A run has three participants: the agent, the model that plays the user, and the judge. Each can sit
behind its own API, with its own capacity. An agent may take 50 conversations at once while the
judge's gateway takes 2, or an agent may need exactly 1 because it counts tokens with a shared
counter (see [Connect an agent](../agents.md)).

convy has one limit for all of them, `--parallel`: conversations at once. It holds a slot from the
moment a conversation opens until the judge has decided, so:

- the weakest API sets the pace for all three; with a judge that takes 2 requests at once, the agent
  is also played 2 conversations at a time;
- a slot stays taken while the judge decides, after the agent has finished;
- `convy run a b` plays both agents with the same limit;
- `convy resume` keeps the run's `parallel`, so a run that hit a rate limit cannot go on slower.

Splitting an attempt into smaller tasks — a user's message, an agent's answer, a judge's decision —
does not help. Each step waits for the one before it, and asyncio already interleaves the steps of
different conversations at every `await`. What matters is what each limit holds.

Other tools set limits per model or per API. Inspect AI has `max_samples` for samples at once and
`max_connections` per model, which a model's own `GenerateConfig` can set, and `eval_retry` may
lower it ([Model Concurrency](https://inspect.aisi.org.uk/models-concurrency.html),
[Eval Logs](https://inspect.aisi.org.uk/eval-logs.html)). promptfoo tracks limits per provider and
API key ([Rate Limits](https://www.promptfoo.dev/docs/configuration/rate-limits/)).

Where such settings live is a common question with a common answer: built-in defaults, then a
version-controlled file of the tool, then environment variables, then flags, each overriding the
one before ([Command Line Interface Guidelines](https://clig.dev/)). Locust reads `[tool.locust]` in
`pyproject.toml`, then `LOCUST_*` variables, then flags
([Configuration](https://locust.readthedocs.io/en/stable/configuration.html)); k6 does the same for
`vus` ([Options](https://grafana.com/docs/k6/latest/using-k6/k6-options/how-to/)). The same guide
warns against `.env` as a configuration file: it holds only strings, is not kept in version control,
and holds secrets.

## Decision

- **Three limits, one per participant.** `Bench` makes three semaphores when it plays:
  - the **agent's** slot is held while a conversation is open, from opening to closing; a
    conversation sends one message at a time, so this also bounds the agent's requests;
  - the **user's** slot is held for one message of the simulated user;
  - the **judge's** slot is held for one decision, after the agent's slot is let go.

  The wait for a slot is outside the agent's timing and outside `TimeLimited`, so it counts neither
  in the time per answer nor against `--turn-timeout`. There is no deadlock: a user's or judge's
  call waits for nothing else, and the judge's slot is taken only after the agent's is let go.
- **The limits are settings of the project, not flags and not code.** They are read from
  `[tool.convy]` in the project's `pyproject.toml`, then from `.env`, then from the environment,
  each overriding the one before; a limit not given is 4. An agent's own table wins over
  `agent_parallel`.

  ```toml
  [tool.convy]
  agent_parallel = 4     # conversations at once with each agent, unless set below
  user_parallel = 8      # messages of the simulated user at once
  judge_parallel = 2     # decisions of the judge at once

  [tool.convy.agents.support_bot]
  parallel = 20          # conversations at once with this agent
  ```

  A variable is `CONVY_` and the key in capitals, such as `CONVY_JUDGE_PARALLEL`, and an agent's
  own limit is `CONVY_AGENTS__<AGENT>__PARALLEL`; they override the file for one run or one
  machine, such as CI. The keys use underscores, as pytest's and mypy's do, so that a key and its
  variable have one name: pydantic-settings cannot read keys with dashes and still match the
  variables. A key convy does not know in `[tool.convy]` is an error, so a typo does not leave a
  limit at 4 unnoticed.
- **`--parallel` is removed.** The command says where the limits are now when it is given.
- **A run records its limits,** as it records `k`. The run's format moves from 3 to 4. A run
  written before reads its one `parallel` as the limit of every participant, since it held all
  three, as older formats are read today ([0005](0005-runs.md)); a format 3 run can still be
  resumed.
- **`convy resume` plays with the current limits.** The limits are not part of the project's
  fingerprints: they change how hard convy pushes, not what it measures. When the agent's limit
  differs from the run's, the command says so, since the agent's load can change its answer time.
  The run keeps the limits it started with.
- **A comparison names a different agent limit** among the differences between two runs, next to
  the models and the convy version.

## Alternatives

- **Keep one `--parallel`.** Simple, but the weakest API sets the pace, and two agents in one
  command share one limit.
- **A flag per participant**, such as `--judge-parallel 2` or `--parallel bot=20`. Long commands,
  easy to forget in CI, and a limit per agent is awkward to write as a flag. Flags can be added
  later as the top layer without breaking anything.
- **Limits in the participants' code**, such as `parallel = 20` in `agents/bot.py` or a field of
  `Models`. Each limit sits next to its participant, but those files are fingerprinted: lowering a
  limit after a rate limit would make the run impossible to resume.
- **Limits only in the environment and `.env`.** `.env` is ignored by git, so a team cannot share
  its limits, and per-agent names such as `CONVY_AGENTS__BOT__PARALLEL` are hard to read as the
  main place; they serve only to override the file.
- **A file of convy's own, `convy.toml`.** One more file in the project, with the same content as
  `[tool.convy]`; it can be added later for projects without `pyproject.toml`.
- **A limit that adapts to rate limits,** as in Inspect and promptfoo. Nothing to set, but more to
  build and test; retries on 429 and 503 already cover rate limits. It can come later.

## Consequences

- The agent can be played at its own pace while a slow judge works through a queue of finished
  dialogues; the queue holds no conversation open.
- A run resumed with another agent limit mixes two loads in its answer times. The command says so;
  `run.json` keeps only the limits the run started with.
- An agent that must run alone, because its conversations share state, can still be resumed with a
  higher limit by mistake. Its limit belongs in `[tool.convy.agents.<name>]`, where the team sees
  it.
- `Bench` and `RunSpec` change their fields, and `--parallel` is gone: a breaking change of the
  alpha, listed in the changelog.
- If the user waits long for its slot, the agent's conversation stays open and the agent idles. The
  docs say to keep the user's limit at least as high as the agent's.
- `pydantic-settings` reads `pyproject.toml` and the environment itself, so no dependency is added.
