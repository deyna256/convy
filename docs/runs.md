# Runs

A run tests one agent on a set of scenarios, with `k` attempts per scenario. If you name several
agents in one command, each gets its own run folder.

```text
results/
├── index.html                          # runs workspace and links to the reports
├── export/                             # convy export: every table as CSV and JSON Lines
└── support_bot/
    └── 2026-10-07T14-02-11_a3f9/       # a run: when it started, and a random part
        ├── report.html                 # the run's report
        ├── run.json                    # what it played and with what, and whether it finished
        ├── run.lock                    # held by the process that plays the run
        └── attempts.jsonl              # a line per attempt
```

convy writes each completed attempt to `attempts.jsonl`. The scenario definitions, model names,
agent and convy versions, limits, scoring settings, and hashes of `agents/<agent>.py` and
`models.py` are saved in `run.json`. A later edit to a scenario leaves old results unchanged.

## Run format compatibility

The current run format is 9. Older standalone HTML reports still open. To resume, rebuild, or
export an older run, use a convy version that supports its format. To start fresh with this
version, give each Python `Call` a [kind](agents.md#steps) and replace graded scenarios with
[yes/no claims](scenarios.md).

## Stop and resume

Ctrl+C stops a run. convy says how to go on:

```text
support_bot: run 2026-10-07T14-02-11_a3f9, 10 scenarios, 3 attempts each
^C
interrupted: 12 of 30 attempts recorded
resume with: convy resume a3f9
```

`convy resume` accepts the full run ID or its unique random suffix. It uses the saved
scenarios, attempt count, timeout, and scoring settings. It skips recorded attempts, including
errors, and starts any missing attempts from the beginning.

Resume checks the installed convy version and the two file hashes before loading project code.
It also checks the agent version and model names. If any differ, use the original versions or
start a new run. Changes in imported modules such as `gateway.py` and changes to remote services
can go undetected.

A process running a journal holds its `run.lock`. If another process holds the lock, resume
exits with code 2. After a crash on Windows, the lock may take a few seconds to clear.
Syncing a results folder between machines does not share the lock.

## How much runs at once

Each participant has a separate concurrency limit, with a default of 4.

- **Agent** — open conversations. Each conversation holds a place until it closes.
- **Simulated user** — requests for the next message.
- **Judge** — requests to judge completed dialogues. The agent's place is free by then.

convy reduces concurrency while a service is busy and raises it again as requests succeed.
Set the limits in the project's `pyproject.toml`.

```toml
[tool.convy]
agent_parallel = 4     # conversations at once with each agent
user_parallel = 8      # messages of the simulated user at once
judge_parallel = 2     # decisions of the judge at once

[tool.convy.agents.support_bot]
parallel = 20          # conversations at once with this agent, instead of agent_parallel
```

Use environment variables to override a setting, for example in CI.

```sh
CONVY_JUDGE_PARALLEL=1 uv run convy run support_bot
CONVY_AGENTS__SUPPORT_BOT__PARALLEL=5 uv run convy run support_bot
```

Process environment variables take precedence over the project's `.env`, then
`pyproject.toml`. Agent names are case-insensitive. An unknown key under `[tool.convy]` in
`pyproject.toml` is an error.

Concurrency limits the number of requests in progress. To also limit how often requests start,
set a requests-per-minute limit. The default is 0 (unlimited). For example, sustaining 120
requests per minute at 3 seconds per request requires at least 6 concurrent requests.

Leave some room below the provider's limit for network timing. If the user and judge share a
key, split its allowance between them. For example, with 100 requests per minute available:

```toml
[tool.convy]
user_parallel = 8
user_per_minute = 70   # with the judge's 20, 90 of the key's 100
judge_per_minute = 20
```

To override one agent's rate limit for a run:

```sh
CONVY_AGENTS__SUPPORT_BOT__PER_MINUTE=27 uv run convy run support_bot
```

Time spent waiting for a place or for the next request slot is excluded from answer times and
the agent's turn timeout. Resume uses the project's current limits. If the agent limits change,
convy warns that the run combines timings measured under different loads.

## Forget a run

Delete its folder and run `convy report` to rebuild the index.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | The command succeeded. A failed claim alone does not change the exit code. |
| 1 | An attempt had an agent error, a persistently busy agent, or a model failure. For resume, only attempts played by that command count. This code takes precedence over 3. |
| 2 | Invalid arguments, configuration, or run selection. Examples include a locked run, an ambiguous ID, or an export that cannot be written. |
| 3 | A CI check failed. For `--fail-under`, a run scored below the threshold or had no counted attempts. For `--fail-on-regression`, see below. |
| 130 | Ctrl+C interrupted the run. Resume it to play the remaining attempts. |

In CI, fail the build when the pass rate is below 90%:

```sh
uv run convy run support_bot --fail-under 0.9
```

convy prints each agent's pass rate and the threshold, for example
`support_bot: pass rate 449 of 500 (89.8%), below 90%`.

## Fail CI when the pass rate regresses

Compare a baseline run with the new build:

```sh
uv run convy compare <before> <after> --fail-on-regression
```

The command prints a verdict and lists any comparable scenarios whose pass rate fell. It exits
with 3 for a statistically supported regression, or if either run is unfinished, the scoring
settings differ, or no unchanged scenario has counted attempts in both runs. Without the flag,
`convy compare` prints the same verdict and exits with 0 for two readable, uniquely identified
runs. See [how the test works](report.md#compare-two-runs).
Use enough attempts and the same models and settings for a meaningful baseline.
