"""The report: runs read back, summed up, and rendered as static HTML pages."""

from collections.abc import Iterable, Iterator
from importlib.resources import files
from math import sqrt
from pathlib import Path
from statistics import mean, stdev
from typing import Literal

import msgspec
from msgspec import Struct

from convy.agent import NoUsage, Usage
from convy.bench import Finished, Interrupted, Pair, RunFile, Running, RunSpec, Status
from convy.dialog import Failed, NoVerdict, Turn, Verdict
from convy.scenario import Outcome, Scenario, Stop

UNREADABLE = (msgspec.DecodeError, msgspec.ValidationError, ValueError, OSError)


class Run(Struct, frozen=True):
    """A run's folder read back: where it is under the results directory, its specification and
    status, the outcomes it could read, and how many lines it could not."""

    path: Path
    spec: RunSpec
    status: Status
    outcomes: tuple[Outcome, ...]
    unreadable: int = 0

    def done(self) -> frozenset[Pair]:
        """The attempts the run has recorded."""
        return frozenset((outcome.scenario, outcome.attempt) for outcome in self.outcomes)

    def complete(self) -> bool:
        return self.done() >= set(self.spec.pairs())


class Runs(Struct, frozen=True):
    """Every run under a results directory, `<agent>/<id>/`. Iterating skips a run whose
    `run.json` cannot be read and the attempt lines that cannot; `broken` lists the runs with
    either. Paths in both are relative to the directory."""

    directory: Path

    def __iter__(self) -> Iterator[Run]:
        for folder in self.folders():
            try:
                yield self.read(folder)
            except UNREADABLE:
                continue

    def broken(self) -> tuple[Path, ...]:
        found = []
        for folder in self.folders():
            try:
                if self.read(folder).unreadable:
                    found.append(folder.relative_to(self.directory))
            except UNREADABLE:
                found.append(folder.relative_to(self.directory))
        return tuple(found)

    def run(self, wanted: str) -> Run:
        """The run whose id is `wanted`, or ends with `_<wanted>`: its random part."""
        found = [run for run in self if wanted in (run.spec.id, run.spec.id.rpartition("_")[2])]
        if not found:
            raise ValueError(f"no run {wanted!r} in {self.directory}")
        if len(found) > 1:
            names = ", ".join(run.path.as_posix() for run in found)
            raise ValueError(f"{wanted!r} names several runs: {names}; give the whole id")
        return found[0]

    def folders(self) -> list[Path]:
        return sorted(path.parent for path in self.directory.glob("*/*/run.json"))

    def read(self, folder: Path) -> Run:
        file = msgspec.json.decode((folder / "run.json").read_bytes(), type=RunFile)
        attempts = folder / "attempts.jsonl"
        lines = attempts.read_bytes().splitlines() if attempts.exists() else []
        outcomes: dict[Pair, Outcome] = {}
        unreadable = 0
        for line in lines:
            try:
                outcome = msgspec.json.decode(line, type=Outcome)
            except UNREADABLE:  # a line cut short by a crash, say
                unreadable += 1
                continue
            # two processes resumed one run: the first line of an attempt counts
            outcomes.setdefault((outcome.scenario, outcome.attempt), outcome)
        return Run(
            folder.relative_to(self.directory),
            file.spec,
            file.status,
            tuple(outcomes.values()),
            unreadable,
        )


# The pages' data. It is JSON for the browser, so a number nobody reported is None (null).

type Tint = Literal["better", "worse", ""]


class ClaimView(Struct, frozen=True):
    text: str
    passed: bool | None  # None: the judge was not asked, or gave no verdict
    reason: str


class TurnView(Struct, frozen=True):
    user: str
    agent: str
    seconds: float
    input: int | None
    output: int | None


class AttemptView(Struct, frozen=True):
    attempt: int
    passed: bool | None  # None: no verdict, left out of pass rates
    stop: Stop
    error: str  # the agent's error, or the failure of convy's model
    claims: tuple[ClaimView, ...]
    seconds: float
    input: int | None
    output: int | None
    turns: tuple[TurnView, ...]


class CellView(Struct, frozen=True):
    """A scenario as one run played it."""

    run: str
    user: str
    claims: tuple[str, ...]
    max_turns: int
    rate: float | None
    changed: bool  # the scenario differs from the newest run that played it
    earlier: str  # the nearest earlier run that played the scenario, or ""
    revised: bool  # the scenario differs from the one in `earlier`
    tint: Tint  # the pass rate against `earlier`, when the scenario is the same
    attempts: tuple[AttemptView, ...]


class ChangeView(Struct, frozen=True):
    delta: float  # the mean change of a scenario's pass rate, over scenarios both runs played
    scenarios: int
    verdict: Literal["better", "worse", "noise", "few"]


class RunView(Struct, frozen=True):
    id: str
    short: str
    started: str  # ISO 8601
    version: str
    status: Literal["running", "finished", "interrupted"]
    user: str
    judge: str
    models_changed: bool
    k: int
    played: int  # scenarios in the run
    passed: float | None
    margin: float | None  # ± of `passed`, shown from three scenarios
    steady: int  # scenarios whose k attempts all passed, when k > 1
    counted: int  # scenarios that count for pass^k
    change: ChangeView | None
    input: float | None
    output: float | None
    turn_mean: float | None
    turn_max: float | None
    agent_failures: int
    model_failures: int
    unreadable: int


class Page(Struct, frozen=True):
    """An agent's page: its runs, oldest first, and a cell per scenario and run."""

    agent: str
    runs: tuple[RunView, ...]
    scenarios: tuple[str, ...]  # those that changed in the latest run first
    changed: tuple[str, ...]
    cells: dict[str, CellView]  # keyed by "<scenario>@<run id>"


class AgentView(Struct, frozen=True):
    agent: str
    runs: int
    latest: RunView


class Index(Struct, frozen=True):
    agents: tuple[AgentView, ...]


class Sample(Struct, frozen=True):
    """Values, one per scenario: their mean, and its 95% margin from three values on."""

    values: tuple[float, ...]

    def mean(self) -> float | None:
        return mean(self.values) if self.values else None

    def margin(self) -> float | None:
        if len(self.values) < 3:
            return None
        return 1.96 * stdev(self.values) / sqrt(len(self.values))


class Played(Struct, frozen=True):
    """A run's attempts of one scenario."""

    scenario: Scenario
    outcomes: tuple[Outcome, ...]

    def judged(self) -> list[bool]:
        """Whether each attempt with a verdict passed; an agent that failed did not."""
        found = []
        for outcome in self.outcomes:
            match outcome.verdict:
                case Verdict() as verdict:
                    found.append(verdict.passed)
                case Failed():
                    found.append(False)
                case NoVerdict():
                    pass
        return found

    def rate(self) -> float | None:
        judged = self.judged()
        return sum(judged) / len(judged) if judged else None

    def steady(self, k: int) -> bool | None:
        """Whether all `k` attempts passed; None when an attempt is missing or has no verdict."""
        judged = self.judged()
        return all(judged) if len(judged) == len(self.outcomes) == k else None


class Report(Struct, frozen=True):
    """The pages under `results/`: `index.html` with every agent, and `<agent>/index.html` with
    an agent's runs. Every number and decision on them is made here; the pages only draw."""

    runs: Iterable[Run]

    def pages(self) -> dict[str, str]:
        """Each page's path under the results directory, and its HTML."""
        runs = list(self.runs)
        agents = sorted({run.spec.agent for run in runs})
        pages = {
            f"{agent}/index.html": self.html(
                "report.html", self.page([run for run in runs if run.spec.agent == agent])
            )
            for agent in agents
        }
        pages["index.html"] = self.html("index.html", self.index(runs))
        return pages

    def html(self, template: str, data: Struct) -> str:
        encoded = msgspec.json.encode(data).decode().replace("<", "\\u003c")
        page = files("convy").joinpath("pages", template).read_text(encoding="utf-8")
        return page.replace("__DATA__", encoded)

    def index(self, runs: list[Run]) -> Index:
        agents = sorted({run.spec.agent for run in runs})
        views = []
        for agent in agents:
            page = self.page([run for run in runs if run.spec.agent == agent])
            views.append(AgentView(agent, len(page.runs), page.runs[-1]))
        return Index(tuple(views))

    def page(self, runs: list[Run]) -> Page:
        """The page of one agent's runs."""
        runs = sorted(runs, key=lambda run: run.spec.started)
        played = [self.played(run) for run in runs]
        cells = {
            f"{scenario}@{run.spec.id}": self.cell(runs, played, index, scenario)
            for index, run in enumerate(runs)
            for scenario in played[index]
        }
        ids = sorted({scenario for found in played for scenario in found})
        newest = runs[-1].spec.id if runs else ""
        changed = [s for s in ids if (c := cells.get(f"{s}@{newest}")) and c.tint]
        return Page(
            agent=runs[0].spec.agent if runs else "",
            runs=tuple(self.run(runs, played, index) for index in range(len(runs))),
            scenarios=(*changed, *(s for s in ids if s not in changed)),
            changed=tuple(changed),
            cells=cells,
        )

    def played(self, run: Run) -> dict[str, Played]:
        """The run's scenarios by id, each with its attempts in order."""
        return {
            scenario.id: Played(
                scenario,
                tuple(
                    sorted(
                        (o for o in run.outcomes if o.scenario == scenario.id),
                        key=lambda outcome: outcome.attempt,
                    )
                ),
            )
            for scenario in run.spec.scenarios
        }

    def run(self, runs: list[Run], played: list[dict[str, Played]], index: int) -> RunView:
        run, scenarios = runs[index], played[index]
        rates = Sample(tuple(r for p in scenarios.values() if (r := p.rate()) is not None))
        steady = [s for p in scenarios.values() if (s := p.steady(run.spec.k)) is not None]
        attempts = [self.attempt(p.scenario, o) for p in scenarios.values() for o in p.outcomes]
        turns = [turn.seconds for attempt in attempts for turn in attempt.turns]
        previous = runs[index - 1].spec if index else None
        return RunView(
            id=run.spec.id,
            short=run.spec.id.rpartition("_")[2],
            started=run.spec.started.isoformat(),
            version=run.spec.version,
            status=self.status(run),
            user=run.spec.user,
            judge=run.spec.judge,
            models_changed=previous is not None
            and (previous.user, previous.judge) != (run.spec.user, run.spec.judge),
            k=run.spec.k,
            played=len(scenarios),
            passed=rates.mean(),
            margin=rates.margin(),
            steady=sum(steady) if run.spec.k > 1 else 0,
            counted=len(steady) if run.spec.k > 1 else 0,
            change=self.change(played[index - 1], scenarios) if index else None,
            input=self.average(a.input for a in attempts),
            output=self.average(a.output for a in attempts),
            turn_mean=self.average(turns),
            turn_max=max(turns, default=None),
            agent_failures=sum(a.stop == "agent_failure" for a in attempts),
            model_failures=sum(a.stop == "model_failure" for a in attempts),
            unreadable=run.unreadable,
        )

    def status(self, run: Run) -> Literal["running", "finished", "interrupted"]:
        match run.status:
            case Running():
                return "running"
            case Finished():
                return "finished"
            case Interrupted():
                return "interrupted"

    def change(self, before: dict[str, Played], after: dict[str, Played]) -> ChangeView | None:
        """The change of pass rates over the scenarios both runs played unchanged, paired by
        scenario; significant when it is beyond the 95% margin of the differences."""
        differences = []
        for scenario, played in after.items():
            earlier = before.get(scenario)
            if earlier is None or earlier.scenario.fingerprint() != played.scenario.fingerprint():
                continue
            rate, earlier_rate = played.rate(), earlier.rate()
            if rate is not None and earlier_rate is not None:
                differences.append(rate - earlier_rate)
        if not differences:
            return None
        sample = Sample(tuple(differences))
        delta, margin = mean(differences), sample.margin()
        if margin is None:
            verdict = "few"
        elif abs(delta) > margin:
            verdict = "better" if delta > 0 else "worse"
        else:
            verdict = "noise"
        return ChangeView(delta, len(differences), verdict)

    def cell(
        self, runs: list[Run], played: list[dict[str, Played]], index: int, scenario: str
    ) -> CellView:
        here = played[index][scenario]
        fingerprint = here.scenario.fingerprint()
        newest = next(found[scenario] for found in reversed(played) if scenario in found)
        before = next((i for i in reversed(range(index)) if scenario in played[i]), None)
        earlier = None if before is None else played[before][scenario]
        return CellView(
            run=runs[index].spec.id,
            user=here.scenario.instructions,
            claims=here.scenario.claims,
            max_turns=here.scenario.max_turns,
            rate=here.rate(),
            changed=newest.scenario.fingerprint() != fingerprint,
            earlier="" if before is None else runs[before].spec.id,
            revised=earlier is not None and earlier.scenario.fingerprint() != fingerprint,
            tint=self.tint(earlier, here),
            attempts=tuple(self.attempt(here.scenario, o) for o in here.outcomes),
        )

    def tint(self, earlier: Played | None, here: Played) -> Tint:
        if earlier is None or earlier.scenario.fingerprint() != here.scenario.fingerprint():
            return ""
        before, after = earlier.rate(), here.rate()
        if before is None or after is None or before == after:
            return ""
        return "better" if after > before else "worse"

    def attempt(self, scenario: Scenario, outcome: Outcome) -> AttemptView:
        turns = tuple(self.turn(turn) for turn in outcome.transcript.turns)
        match outcome.verdict:
            case Verdict(claims=decided) as verdict:
                judged: tuple[bool | None, str] = (verdict.passed, "")
                claims = tuple(
                    ClaimView(text, claim.passed, claim.reason)
                    for text, claim in zip(scenario.claims, decided, strict=True)
                )
            case Failed(reason=reason):
                judged = (False, reason)
                claims = tuple(ClaimView(text, None, "") for text in scenario.claims)
            case NoVerdict(error=error):
                judged = (None, error)
                claims = tuple(ClaimView(text, None, "") for text in scenario.claims)
        passed, error = judged
        return AttemptView(
            attempt=outcome.attempt,
            passed=passed,
            stop=outcome.stop,
            error=error,
            claims=claims,
            seconds=sum(turn.seconds for turn in turns),
            input=self.total(turn.input for turn in turns),
            output=self.total(turn.output for turn in turns),
            turns=turns,
        )

    def turn(self, turn: Turn) -> TurnView:
        match turn.answer.usage:
            case Usage(input=spent, output=produced):
                tokens: tuple[int | None, int | None] = (spent, produced)
            case NoUsage():
                tokens = (None, None)
        return TurnView(turn.message.text, turn.answer.text, turn.seconds, *tokens)

    def total(self, counts: Iterable[int | None]) -> int | None:
        known = [count for count in counts if count is not None]
        return sum(known) if known else None

    def average(self, values: Iterable[float | None]) -> float | None:
        known = [value for value in values if value is not None]
        return mean(known) if known else None
