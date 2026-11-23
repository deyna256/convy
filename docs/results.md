# Results as data

Read saved runs in Python with `Runs`. Use `Tables` to analyze their records in pandas or
Polars, or export CSV and JSON Lines files for other tools.

## A run is the result

```python
from pathlib import Path

from convy import Runs

runs = Runs(Path("results"))
for run in runs:
    print(run.spec.agent, run.spec.id, len(run.outcomes))
```

Use `runs.run("7ad8")` to select a run by full ID or unique suffix. Each `Run` has:

- `spec` — the agent, build, models, saved scenarios and run settings.
- `status` — `Running`, `Finished` or `Interrupted`. Finished and interrupted runs have an end time.
- `outcomes` — recorded attempts with dialogues, answer times, reported tokens, steps and verdicts.
- `path`, `format` and `unreadable` — the run folder relative to `results/`, the file format
  version and the number of unreadable attempt lines.

Iteration skips unreadable runs and individual unreadable attempts. Reading leaves the files
untouched. See [supported run formats](runs.md#run-format-compatibility).

## Tables

```python
from pathlib import Path

import pandas as pd

from convy import Runs, Tables

tables = Tables(tuple(Runs(Path("results"))))
table = tables.answers()
answers = pd.DataFrame(table.records(), columns=table.row.__struct_fields__)
```

Each table reads the tuple of runs independently. A table's `rows` are typed records;
`records()` returns dictionaries and keeps datetimes. The example uses the row type to keep
the columns even when there are no answers. Use `csv()` or `jsonl()` for serialized text.
Iterating over `tables` yields the seven tables below.

| table | keys | columns |
|---|---|---|
| `runs` | `run` | `agent`, `version`, `user_model`, `judge_model`, `k`, `turn_timeout`, `trust`, `claim_threshold`, `convy`, `started`, `status` (`running`, `finished` or `interrupted`), `ended`, `agent_parallel`, `user_parallel`, `judge_parallel`, `agent_per_minute`, `user_per_minute`, `judge_per_minute`, `agent_file`, `models_file` (sha256), `format`, `path` (the run's folder inside `results/`, with `/`), `unreadable` |
| `scenarios` | `run`, `scenario` | `instructions`, `max_turns` |
| `claims` | `run`, `scenario`, `claim` | `text`, `required` |
| `attempts` | `run`, `scenario`, `attempt` | `verdict` (`verdict`, `failed` or `no_verdict`), `error`, `stop` |
| `decisions` | `run`, `scenario`, `attempt`, `claim` | `passed`, `reason`, `confidence` |
| `answers` | `run`, `scenario`, `attempt`, `turn` | `message`, `answer`, `seconds`, `steps_complete`, `input`, `output`, `thinking`, `cache_read`, `cache_write` |
| `steps` | `run`, `scenario`, `attempt`, `turn`, `step` | `kind` (`thought` or `call`), `call_kind` (`model` or `tool`, `None` for a thought), `text`, `name`, `started`, `seconds`, `input`, `output`, `thinking`, `cache_read`, `cache_write`, `sent`, `received` |

Claims, turns, steps and attempts are numbered from 1. An unfinished run can have gaps in attempt
numbers. Runs are sorted by start time, scenarios follow their saved order, and attempts within
each scenario are sorted by number. A missing value is `None`, including fields that do not apply
to the row. An empty string is a reported value.

When joining tables, include all shared key columns for the record you need. An attempt's key is
`(run, scenario, attempt)`. Child rows carry the run ID but do not carry the agent or folder. If
two runs share an ID, process their folders separately. Scenarios created through Python also
need distinct IDs for these keys to be unique.

`decisions.passed` is the judge's raw yes/no answer. The [example below](#a-full-example)
applies trust, required claims and the claim threshold to calculate the pass rate.
`answers.steps_complete` and `steps.call_kind` let you [count tool calls](report.md#tool-invocations).

## Export

```sh
uv run convy export 7ad8 5e85           # two runs by unique suffix
uv run convy export results/shop_bot    # all runs of one agent
uv run convy export results             # all runs
```

Each export replaces the 14 files in `results/export/`, one CSV and one JSON Lines file per
table. JSON Lines keeps missing values (`null`) distinct from empty strings (`""`). CSV leaves
missing cells empty and quotes all reported values, including empty strings. Dates use ISO 8601.
Check how your CSV reader handles empty strings and dates, or use JSON Lines to preserve the
distinction.

If an export stops partway through, the folder can contain a mix of old and new files. Close any
open files and run the export again.

## How convy makes its numbers

See [the report tiles](report.md#tiles) for pass rates and
[measured population](report.md#measured-population) for means, medians and coverage.

## A full example

Plot the pass rate of each run over time using pandas and matplotlib. Calculate each run
separately so runs with the same ID stay distinct. A run with no counted attempts has no rate.

```python
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from convy import Runs, Tables


def pass_rate(run):
    tables = Tables((run,))
    counted = sum(row.verdict != "no_verdict" for row in tables.attempts().rows)
    if not counted:
        return None

    decisions = pd.DataFrame(tables.decisions().records())
    if decisions.empty:
        return 0.0  # Every counted attempt was an agent failure.

    claims = pd.DataFrame(tables.claims().records())
    decisions = decisions.merge(claims, on=["scenario", "claim", "run"], validate="many_to_one")
    decisions["held"] = decisions["passed"] & (
        decisions["confidence"].isna() | (decisions["confidence"] >= run.spec.trust)
    )
    decisions["required_failed"] = decisions["required"] & ~decisions["held"]
    attempts = decisions.groupby(["scenario", "attempt"])
    enough_claims = attempts["held"].mean() >= run.spec.claim_threshold
    passed = enough_claims & ~attempts["required_failed"].any()
    return 100 * passed.sum() / counted


points = [(run.spec.started, pass_rate(run)) for run in Runs(Path("results"))]
series = pd.DataFrame(points, columns=["started", "percent"]).sort_values("started")
plt.plot(series["started"], series["percent"], marker="o")
plt.ylabel("Pass rate (%)")
plt.savefig("pass-rate.png")
```

## Careful with an export

Exports contain the dialogue text. Share them with the same care as the original runs.
Spreadsheet software may interpret a cell starting with `=`, `+`, `-` or `@` as a formula.

## Columns are kept

convy may add columns. A rename or removal is a breaking change documented in the changelog.
If you used ordered claim scales, remove references to `claims.grades`, `claims.threshold` and
`decisions.grade`. Current exports contain yes/no decisions. See [the table format decision](decisions/0011-run-as-data.md).
