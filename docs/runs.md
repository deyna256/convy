# Runs

A run is one `convy run` of one agent: the scenarios it played, `k` attempts each. Every run has a
folder of its own:

```text
results/
├── index.html                          # every run, with a link to its report
├── compare/                            # the pages convy compare writes
└── support_bot/
    └── 2026-10-07T14-02-11_a3f9/       # a run: when it started, and a random part
        ├── report.html                 # the run's report
        ├── run.json                    # what it played and with what, and whether it finished
        └── attempts.jsonl              # a line per attempt
```

Each attempt is written as soon as it ends, so a stopped run loses nothing.

`run.json` keeps a copy of every scenario as it was played. It also keeps the agent's `version`, the
convy version, the model names, the settings (`k`, `trust` and the rest), and fingerprints of
`agents/<agent>.py` and `models.py`. So a run describes itself: editing a scenario later does not
change what an old run means.

## Stop and resume

Ctrl+C stops a run. convy says how to go on:

```text
support_bot: run 2026-10-07T14-02-11_a3f9, 10 scenarios, 3 attempts each
^C
interrupted: 12 of 30 attempts recorded
resume with: convy resume a3f9
```

`convy resume` takes the run's id or its random part. It plays the missing attempts with exactly the
run's settings: the same scenarios, `k`, `--parallel`, `--turn-timeout` and `--trust`.

It refuses, and says why, if the agent's file, `models.py`, the agent's `version` or a model name
has changed. The run would no longer measure one thing. It cannot see a change in a module the agent
imports, or in the service behind the agent.

Attempts that ended in an error are recorded and are not played again.

## Forget a run

Delete its folder and run `convy report`.

## Exit codes

- `0`: every attempt finished.
- `1`: an attempt ended with an agent error or a failure of convy's models. For `convy resume`, an
  attempt it played.
- `2`: the project could not be loaded, or the run cannot be resumed. Nothing ran.
- `130`: the run was stopped with Ctrl+C. `convy resume` continues it.
