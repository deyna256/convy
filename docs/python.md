# Run from Python

A `Bench` runs scenarios against an agent. A `RunJournal` saves each attempt to disk.
This example runs locally with an echo agent and fake models, then writes both HTML reports.
Run it in a directory where `results/echo/first/` does not already exist.

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
    TimeLimited,
)
from convy.fakes import Echo, FakeJudge, FakeModel

scenario = Scenario(
    id="greet",
    max_turns=3,
    instructions="Say hello to the assistant, then thank it.",
    claims=(Requirement("The agent answered the greeting", required=True),),
)
models = Models(
    user=FakeModel("Hello!", "Thank you!", "###STOP###"),
    judge=FakeJudge((Claim(True, Reason("it answered")),)),
)
limits = Limits(agent=2, user=4, judge=1, judge_per_minute=50)
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
agent = TimeLimited(Echo(), spec.turn_timeout)
asyncio.run(journal.play(bench, agent, journal))
runs = tuple(Runs(results))
for run in runs:
    (results / run.path / "report.html").write_text(Report(run).html(), encoding="utf-8")
(results / "index.html").write_text(Index(runs).html(), encoding="utf-8")
```

Open `results/index.html` to [compare runs](report.md#runs-workspace), or open a run's
`report.html` to read its dialogues. For the CLI regression check, use
`Comparison(before, after).check()`. It returns the summary text and a boolean that is true
when the check fails. To analyze runs in pandas or polars, see [Results as data](results.md).

Replace `Echo()` with your agent and the fake models with your [user model and judge](judge.md).
Use `Bench(..., patience=Patience(seconds=300))` to change the default 120-second retry budget
for busy services. `RunJournal.play` raises `RunInUse` if another process holds the run lock.

## Score a verdict

Define each claim as a `Requirement(text, required=False)`. YAML also accepts plain strings.
The judge returns a `Claim` for each requirement. Its `passed` field is the original decision.
`claim.holds(trust)` applies the confidence cutoff.

Call `scenario.score(verdict, trust=0.8, threshold=0.8)` to score the whole attempt.
The returned `Score` gives the counts (`held`, `total`), the fraction that held (`fraction`),
the numbers of any failed required claims (`required_failed`, starting at 1), the `threshold`,
and the result (`passed`). Defaults are `trust=0` and `threshold=1`.
Only attempts with a judge's verdict have a score. See [Passing an attempt](scenarios.md#passing-an-attempt).
