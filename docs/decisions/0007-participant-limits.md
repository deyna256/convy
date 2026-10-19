# 7. Each participant has its own limit, set in the project's settings

**Status:** Accepted

## Context

A run has three participants: the agent, the model that plays the user, and the judge. Each can sit
behind its own API with its own capacity: an agent may take 50 conversations at once while the
judge's gateway takes 2, or an agent may need exactly 1 because its conversations share a token
counter.

convy had one limit for all of them, `--parallel`, which held a place from the moment a
conversation opened until the judge had decided. So the weakest API set the pace for all three, a
place stayed taken while the judge worked, `convy run a b` played both agents with one limit, and
`convy resume` could not go on slower after rate limits.

Splitting an attempt into smaller tasks does not help: each step waits for the one before it, and
asyncio already interleaves the steps of different conversations. What matters is what each limit
holds.

Other tools limit per model or per API: Inspect AI has `max_connections` per model and lets
`eval_retry` lower it ([Model Concurrency](https://inspect.aisi.org.uk/models-concurrency.html)),
promptfoo tracks limits per provider and key
([Rate Limits](https://www.promptfoo.dev/docs/configuration/rate-limits/)). Settings like these
usually live in a version-controlled file of the tool, with environment variables over it
([Command Line Interface Guidelines](https://clig.dev/)); Locust reads `[tool.locust]` in
`pyproject.toml`, then `LOCUST_*` variables
([Configuration](https://locust.readthedocs.io/en/stable/configuration.html)).

## Decision

- **Three limits, one per participant:** conversations open with the agent, messages of the
  simulated user, decisions of the judge. The judge decides after the conversation has let its
  place go, and the wait for a place counts neither in the answer time nor against the time limit.
- **The limits are settings of the project, not flags and not code:** `[tool.convy]` in the
  project's `pyproject.toml`, with `CONVY_*` variables over it, and a table of an agent's own. The
  keys use underscores, so that a key and its variable have one name. How to set them is in
  [Runs](../runs.md#how-much-runs-at-once); how they are read and checked is in
  [ARCHITECTURE](../../ARCHITECTURE.md).
- **`--parallel` is removed.** The command says where the limits are now.
- **A run records its limits,** and its format moves from 3 to 4. Older runs read their one
  `parallel` as every limit, since it held all three ([0005](0005-runs.md)).
- **`convy resume` plays with the current limits.** They change how hard convy pushes, not what it
  measures, so they are not fingerprinted. The command says when the agent's limit changed, since
  the agent's load can change its answer time.
- **`convy compare` names a different agent limit,** next to the models and the convy version.

## Alternatives

- **Keep one `--parallel`.** Simple, but the weakest API sets the pace for all.
- **A flag per participant,** such as `--parallel bot=20`. Long commands, easy to forget in CI.
  Flags can still be added later on top.
- **Limits in the participants' code,** such as `parallel = 20` in `agents/bot.py`. Those files are
  fingerprinted, so lowering a limit after rate limits would make a run impossible to resume.
- **Limits only in `.env` and the environment.** `.env` is not kept in git, so a team cannot share
  its limits.
- **A limit that adapts to rate limits,** as in Inspect and promptfoo. More to build; retries on
  429 and 503 already cover rate limits. It can come later.

## Consequences

- The agent is played at its own pace while a slow judge works through a queue of finished
  dialogues, which hold no conversation open.
- A run resumed with another agent limit mixes two loads in its answer times; `run.json` keeps the
  limits it started with.
- An agent that must run alone can still be resumed with a higher limit by mistake; its own table
  in `[tool.convy.agents]` is where the team sees its limit.
- `--parallel`, and `parallel` in `Bench` and `RunSpec`, are gone: a breaking change of the alpha.
- No dependency is added.
