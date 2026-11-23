# Results as data

Every run is kept whole in its folder. Read it from Python as a `Run`, as flat tables for pandas or
polars, or export the tables as files for any other tool.

## A run is the result

A `Run` holds everything a run did:

- `spec`: what it played and with what — the agent and its `version`, the user's and the judge's
  models, `k`, `trust`, `claim_threshold`, the limits, the convy version, and a copy of every
  scenario with its claims;
- `status`: `Running`, `Finished` or `Interrupted`, with the time it ended;
- `outcomes`: one per attempt, with its dialogue, each answer's time, tokens and steps, and the
  judge's decisions;
- `format`: the format its folder was written in, and `unreadable`: how many attempt lines could not
  be read.

Read the runs of a results folder, or one run by its id or its random part:

```python
from pathlib import Path

from convy import Runs

runs = Runs(Path("results"))
for run in runs:
    print(run.spec.id, len(run.outcomes))
run = runs.run("7ad8")
```

`Runs` reads only the current run format. Earlier formats are unsupported and are not converted;
see [run format compatibility](runs.md#run-format-compatibility). Reading does not change the
saved files.

## Tables

`Tables` gives runs as seven flat tables, one for each kind of object a run holds:

```python
import pandas as pd

from convy import Runs, Tables

tables = Tables(tuple(Runs(Path("results"))))
answers = pd.DataFrame(tables.answers().records())
```

Give it a tuple, not a generator: each table reads the runs again. The tables compute nothing and
drop nothing. The keys come first:

| table | keys | columns |
|---|---|---|
| `runs` | `run` | `agent`, `version`, `user_model`, `judge_model`, `k`, `turn_timeout`, `trust`, `claim_threshold`, `convy`, `started`, `status` (`running`, `finished` or `interrupted`), `ended`, `agent_parallel`, `user_parallel`, `judge_parallel`, `agent_per_minute`, `user_per_minute`, `judge_per_minute`, `agent_file`, `models_file` (sha256), `format`, `path` (the run's folder inside `results/`, with `/`), `unreadable` |
| `scenarios` | `run`, `scenario` | `instructions`, `max_turns` |
| `claims` | `run`, `scenario`, `claim` | `text`, `required` |
| `attempts` | `run`, `scenario`, `attempt` | `verdict` (`verdict`, `failed` or `no_verdict`), `error`, `stop` |
| `decisions` | `run`, `scenario`, `attempt`, `claim` | `passed`, `reason`, `confidence` |
| `answers` | `run`, `scenario`, `attempt`, `turn` | `message`, `answer`, `seconds`, `steps_complete`, `input`, `output`, `thinking`, `cache_read`, `cache_write` |
| `steps` | `run`, `scenario`, `attempt`, `turn`, `step` | `kind` (`thought` or `call`), `call_kind` (`model` or `tool`, `None` for a thought), `text`, `name`, `started`, `seconds`, `input`, `output`, `thinking`, `cache_read`, `cache_write`, `sent`, `received` |

- `run` is the run's id, `scenario` the scenario's id, `attempt` the attempt's number; an
  unfinished run may skip numbers. `claim`, `turn` and `step` count from 1, as on the report.
  Scenario ids are unique in scenario files; a run made in Python with repeated ids gives repeated
  keys.
- Runs come by start time; in a run, scenarios and claims in the run's order, attempts by scenario
  then number, and decisions, answers and steps in their order.
- `None` is a value the agent or the judge did not give, or one that does not apply: a thought has
  no `name`, an attempt with a verdict no `error`. `""` is text given
  empty. A run still running has no `ended`.
- A key means one thing in every table. A value of two grains — `started`, `seconds`, the tokens —
  keeps its name in both tables, so join on the keys and pick the columns you need.

Each table has a `name`, the type of its rows in `row`, so an empty table still knows its columns,
and its `rows`. `records()` gives the rows as dicts, with times as `datetime`; `csv()` and `jsonl()`
give the table as a file's text. Iterating `tables` gives the seven tables in the order above.

`answers.steps_complete` and `steps.call_kind` preserve the [agent's reported facts](agents.md#steps).
Tool counts are derived, not exported: use the [tool-invocation rule](report.md#tool-invocations)
to distinguish complete measurements from partial traces.

Other values are left out on purpose, since they are computed. With the tables as DataFrames, the
random part of a run's id is:

```python
runs["short"] = runs["run"].str.rpartition("_")[2]
```

Whether an attempt passed is also computed. `decisions.passed` is the **raw judge decision**,
not the effective result after confidence and required claims. Join decisions to the run's `trust`
and `claim_threshold`, and to each claim's `required` flag; apply the
[scoring rule](scenarios.md#passing-an-attempt). The [full example](#a-full-example) below does this
and includes agent failures in the pass rate. Completion fractions and final attempt results are
not stored as redundant columns.

## Export

`convy export` writes the tables as files for tools outside Python:

```sh
uv run convy export 7ad8 5e85           # two runs, by id or random part
uv run convy export results/shop_bot    # every run of an agent
uv run convy export results             # every run
```

A target is a folder inside `results/`, or else a run. It writes 14 files into `results/export/`:
`runs.csv` and `runs.jsonl`, and so on for each table, replacing the files of an earlier export.

JSON Lines is the complete form: one JSON object a line, `null` for `None`, `""` kept. CSV is for
spreadsheets: an empty cell for `None`, every other value quoted, and a value that is not text
written as in JSON Lines: a list as JSON text, `true` and `false`, times in ISO form (`…Z` for
UTC). Reading it back:

- pandas and DuckDB read a quoted `""` as missing, the same as `None`; polars keeps it apart.
- pandas keeps times as text; so does polars, unless you give `try_parse_dates=True`, which reads
  them in UTC. DuckDB reads them as times in your local zone.

An export that fails part way, say on a CSV open in Excel on Windows, can leave older files next to
new ones: close it and export again. An agent named `export` shares the folder with the files.

## How convy makes its numbers

The report's rules — what counts in the pass rate and which scenario is stable — are in
[The report](report.md#tiles). Its [measured population](report.md#measured-population) defines
means and medians per answer and per task, including missing token measurements and
[tool invocations](report.md#tool-invocations). Follow these rules and your numbers are convy's.

## A full example

The pass rate of each run over time, computed as the report does, with pandas and matplotlib:

```python
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from convy import Runs, Tables

tables = Tables(tuple(Runs(Path("results"))))
runs = pd.DataFrame(tables.runs().records())
attempts = pd.DataFrame(tables.attempts().records())
decisions = pd.DataFrame(tables.decisions().records())

claims = pd.DataFrame(tables.claims().records())

# Raw decisions stay intact; derive effective claims and attempt results.
decisions = decisions.merge(runs[["run", "trust", "claim_threshold"]], on="run")
decisions = decisions.merge(
    claims[["run", "scenario", "claim", "required"]], on=["run", "scenario", "claim"]
)
decisions["held"] = decisions["passed"] & (
    decisions["confidence"].fillna(1.0) >= decisions["trust"]
)
decisions["required_failed"] = decisions["required"] & ~decisions["held"]
keys = ["run", "scenario", "attempt"]
verdicts = decisions.groupby(keys).agg(
    held=("held", "sum"),
    total=("held", "size"),
    required_failed=("required_failed", "any"),
    threshold=("claim_threshold", "first"),
)
verdicts["passed"] = ~verdicts["required_failed"] & (
    verdicts["held"] / verdicts["total"] >= verdicts["threshold"]
)
attempts = attempts.join(verdicts[["passed"]], on=keys)
attempts["counted"] = attempts["verdict"].isin(["verdict", "failed"])
attempts["passed"] = attempts["verdict"].eq("verdict") & attempts["passed"].eq(True)

rate = attempts[attempts["counted"]].groupby("run")["passed"].mean().rename("rate")
by_time = runs.join(rate, on="run").sort_values("started")
plt.plot(by_time["started"], by_time["rate"] * 100, marker="o")
plt.ylabel("pass rate, %")
plt.savefig("pass-rate.png")
```

## Careful with an export

An export holds the dialogues' text: share it as carefully as `results/`. A cell that starts with
`=`, `+`, `-` or `@` may run as a formula when a spreadsheet opens the CSV. convy keeps the text as
the agent gave it.

## Columns are kept

A new convy version may add columns. Renaming or removing one is a breaking change, and the
changelog says so; see [why](decisions/0011-run-as-data.md).

Removing ordered claim scales removes `grades` and `threshold` from `claims`, and `grade` from
`decisions`. Update consumers of those columns; new exports contain yes/no decisions only.
