# Run from Python

Everything the command does is in the library. A run is a `Bench` played against an agent. A
`RunJournal` writes it into the run's folder. The report is built from the runs:

```python
import asyncio
from datetime import datetime
from pathlib import Path

from convy import (
    Bench,
    Claim,
    Index,
    Limits,
    Models,
    Reason,
    Report,
    Requirement,
    RunJournal,
    Runs,
    RunSpec,
    Scenario,
)
from convy.fakes import Echo, FakeJudge, FakeModel

scenario = Scenario(
    id="greet",
    max_turns=3,
    instructions="Say hello to the assistant, then thank it.",
    claims=(Requirement("The agent answered the greeting", required=True),),
)
models = Models(  # fakes: nothing is called; use OpenAiModel and ChatJudge for real ones
    user=FakeModel("Hello!", "Thank you!", "###STOP###"),
    judge=FakeJudge((Claim(True, Reason("it answered")),)),
)
limits = Limits(agent=2, user=4, judge=1, judge_per_minute=50)  # at once; the judge per minute too
bench = Bench((scenario,), models, limits=limits)
spec = RunSpec(
    id="first",  # the run's folder: results/echo/first/
    agent="echo",
    version="",
    user=models.user.name,
    judge=models.judge.name,
    k=bench.attempts,
    turn_timeout=600,
    scenarios=bench.scenarios,
    started=datetime.now().astimezone(),
    trust=0.0,  # minimum confidence for a claim to hold
    claim_threshold=1.0,  # fraction of all claims needed, with every required claim holding
    limits=bench.limits,
)
results = Path("results")
journal = RunJournal(results, spec)
journal.create()
outcomes = asyncio.run(journal.play(bench, Echo(), journal))
runs = tuple(Runs(results))
for run in runs:
    (results / run.path / "report.html").write_text(Report(run).html(), encoding="utf-8")
(results / "index.html").write_text(Index(runs).html(), encoding="utf-8")
```

Open `results/index.html` for the [runs workspace](report.md#runs-workspace). Code that used
`Comparison(before, after).html()` to write a two-run page can render `Index((before, after)).html()`
there and link to the same individual reports. For the CLI’s verdict in Python,
`Comparison(before, after).check()` returns the text and a boolean indicating whether the CI gate
fails. For flat tables to use with pandas or polars, see [Results as data](results.md).

`Bench` also takes `patience=Patience(seconds=300)`: how long each participant waits for a busy
service, 120 seconds by default. The run records the installed convy version, as `convy run` does.
`play` raises `RunInUse` when another process is playing the run's folder. Put your own agent in
place of `Echo()`. The fakes in `convy.fakes` are public too: use them to test your agent classes
without a model.

## Score a verdict

Python scenarios take `tuple[Requirement, ...]`; strings are shorthand only in YAML. This is a
breaking API change. `Requirement(text, required=False)` separates what the scenario asks for from
the judge's `Claim`, which records its raw decision, reason and confidence.

For a valid `Verdict`, call `scenario.score(verdict, trust=0.8, threshold=0.8)`. It returns a
`Score` with `held`, `total`, `required_failed` (a tuple of claim numbers starting at 1) and
`threshold`. Its `fraction` and `passed` properties follow the
[scoring rule](scenarios.md#passing-an-attempt). Defaults are `trust=0` and `threshold=1`.
`Claim.holds(trust)` gives the effective result of one decision; `Claim.passed` remains the raw
judge decision. `Verdict.passed` and `Verdict.decided` are removed: the scenario and run settings
are needed to determine an attempt's result. Agent failures and missing verdicts have no `Score`.
