# Run from Python

Everything the command does is in the library. A run is a `Bench` played against an agent. A
`RunJournal` writes it into the run's folder. The report is built from the runs:

```python
import asyncio
from datetime import datetime
from pathlib import Path

from convy import Bench, Claim, Models, Report, RunJournal, Runs, RunSpec, Scenario
from convy.fakes import Echo, FakeJudge, FakeModel

scenario = Scenario(
    id="greet",
    max_turns=3,
    instructions="Say hello to the assistant, then thank it.",
    claims=("The agent answered the greeting",),
)
models = Models(  # fakes: nothing is called; use OpenAiModel and ChatJudge for real ones
    user=FakeModel("Hello!", "Thank you!", "###STOP###"),
    judge=FakeJudge((Claim(True, "it answered"),)),
)
bench = Bench((scenario,), models)
spec = RunSpec(
    id="first",  # the run's folder: results/echo/first/
    agent="echo",
    version="",
    user=models.user.name,
    judge=models.judge.name,
    k=bench.attempts,
    parallel=bench.parallel,
    turn_timeout=600,
    scenarios=bench.scenarios,
    started=datetime.now().astimezone(),
)
results = Path("results")
journal = RunJournal(results, spec)
journal.create()
outcomes = asyncio.run(journal.play(bench, Echo(), journal))
(run,) = Runs(results)
Path("results/echo/first/report.html").write_text(Report(run).html(), encoding="utf-8")
```

Put your own agent in place of `Echo()`. The fakes in `convy.fakes` are public too: use them to test
your agent classes without a model.
