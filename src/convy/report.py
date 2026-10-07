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
        claims = {scenario.id: len(scenario.claims) for scenario in file.spec.scenarios}
        outcomes: dict[Pair, Outcome] = {}
        unreadable = 0
        for line in lines:
            try:
                outcome = msgspec.json.decode(line, type=Outcome)
            except UNREADABLE:  # a line cut short by a crash, say
                unreadable += 1
                continue
            wanted = claims.get(outcome.scenario)  # a scenario of the run's snapshot
            match outcome.verdict:
                case Verdict(claims=decided) if len(decided) != wanted:
                    wanted = None
            if wanted is None:
                unreadable += 1  # not explained by the snapshot
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

type Result = Literal["failing", "flaky", "passing", "none"]
type Tone = Literal["good", "bad", "same", "noise", "none"]
type Group = Literal["worse", "better", "same", "apart"]

ORDER: dict[Result, int] = {"failing": 0, "flaky": 1, "none": 2, "passing": 3}
GROUPS: dict[Group, int] = {"worse": 0, "better": 1, "same": 2, "apart": 3}


class ClaimView(Struct, frozen=True):
    """The judge's decision on one claim in one attempt."""

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


class ClaimSummary(Struct, frozen=True):
    """A claim over a scenario's attempts that have a verdict."""

    text: str
    held: int
    judged: int

    def result(self) -> Result:
        if not self.judged:
            return "none"
        if self.held == self.judged:
            return "passing"
        return "failing" if self.held == 0 else "flaky"


class ScenarioView(Struct, frozen=True):
    id: str
    user: str
    max_turns: int
    result: Result
    claims: tuple[ClaimSummary, ...]
    seconds: float | None  # mean per answer
    slowest: float | None
    input: float | None  # mean per attempt
    output: float | None
    attempts: tuple[AttemptView, ...]


class Metrics(Struct, frozen=True):
    """The tiles of a run: the numbers behind them."""

    passed: int  # judged attempts that passed
    judged: int
    stable: int  # scenarios whose k attempts all passed
    scenarios: int
    k: int
    seconds: float | None  # mean per answer
    slowest: float | None
    input: float | None  # mean per attempt
    output: float | None
    agent_errors: int
    model_errors: int

    def rate(self) -> float | None:
        return self.passed / self.judged if self.judged else None

    def tokens(self) -> float | None:
        if self.input is None and self.output is None:
            return None
        return (self.input or 0) + (self.output or 0)

    def errors(self) -> int:
        return self.agent_errors + self.model_errors


class RunHead(Struct, frozen=True):
    id: str
    short: str
    agent: str
    version: str
    started: str  # ISO 8601
    status: Literal["running", "finished", "interrupted"]
    user: str
    judge: str
    k: int
    scenarios: int
    unreadable: int


class RunPage(Struct, frozen=True):
    run: RunHead
    metrics: Metrics
    scenarios: tuple[ScenarioView, ...]  # failing, flaky, no verdict, passing; each by id


class Delta(Struct, frozen=True):
    """A change from before to after, in the metric's own unit, and how to read it."""

    value: float | None
    tone: Tone


class Deltas(Struct, frozen=True):
    rate: Delta  # percentage points
    stable: Delta
    seconds: Delta
    tokens: Delta
    errors: Delta


class ClaimChange(Struct, frozen=True):
    text: str
    before: Result
    after: Result
    change: Literal["unchanged", "worse", "better"]


class CompareRow(Struct, frozen=True):
    id: str
    group: Group
    why: str  # why a scenario is not compared, or ""
    before: ScenarioView | None
    after: ScenarioView | None
    claims: tuple[ClaimChange, ...]


class ComparePage(Struct, frozen=True):
    before: RunHead
    after: RunHead
    was: Metrics
    now: Metrics
    deltas: Deltas
    models: tuple[str, ...]  # the models that differ, as "judge: a → b"
    rows: tuple[CompareRow, ...]  # worse, better, same, not compared; each by id


class IndexRow(Struct, frozen=True):
    run: RunHead
    passed: int
    judged: int
    report: str  # the run's report, relative to the index


class IndexPage(Struct, frozen=True):
    runs: tuple[IndexRow, ...]  # newest first


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

    def result(self) -> Result:
        judged = self.judged()
        if not judged:
            return "none"
        if all(judged):
            return "passing"
        return "flaky" if any(judged) else "failing"

    def stable(self, k: int) -> bool:
        """Whether all `k` attempts are recorded, judged and passed."""
        judged = self.judged()
        return len(judged) == len(self.outcomes) == k and all(judged)


class Template(Struct, frozen=True):
    """A page in `convy/pages/`, filled with its data."""

    name: str

    def html(self, data: Struct) -> str:
        # ponytail: every dialogue of a run is in its page (~5 KB per attempt); load
        # attempts.jsonl lazily when pages get heavy
        encoded = msgspec.json.encode(data).decode().replace("<", "\\u003c")
        page = files("convy").joinpath("pages", self.name).read_text(encoding="utf-8")
        return page.replace("__DATA__", encoded)


class Summary(Struct, frozen=True):
    """A run summed up for the pages: its head, its tiles, a view per scenario."""

    run: Run

    def played(self) -> dict[str, Played]:
        """The run's scenarios by id, each with its recorded attempts in order."""
        return {
            scenario.id: Played(
                scenario,
                tuple(
                    sorted(
                        (o for o in self.run.outcomes if o.scenario == scenario.id),
                        key=lambda outcome: outcome.attempt,
                    )
                ),
            )
            for scenario in self.run.spec.scenarios
        }

    def head(self) -> RunHead:
        spec = self.run.spec
        match self.run.status:
            case Running():
                status: Literal["running", "finished", "interrupted"] = "running"
            case Finished():
                status = "finished"
            case Interrupted():
                status = "interrupted"
        return RunHead(
            id=spec.id,
            short=spec.id.rpartition("_")[2],
            agent=spec.agent,
            version=spec.version,
            started=spec.started.isoformat(),
            status=status,
            user=spec.user,
            judge=spec.judge,
            k=spec.k,
            scenarios=len(spec.scenarios),
            unreadable=self.run.unreadable,
        )

    def metrics(self) -> Metrics:
        played = self.played().values()
        judged = [passed for p in played for passed in p.judged()]
        attempts = [self.attempt(p.scenario, o) for p in played for o in p.outcomes]
        turns = [turn.seconds for attempt in attempts for turn in attempt.turns]
        return Metrics(
            passed=sum(judged),
            judged=len(judged),
            stable=sum(p.stable(self.run.spec.k) for p in played),
            scenarios=len(played),
            k=self.run.spec.k,
            seconds=self.average(turns),
            slowest=max(turns, default=None),
            input=self.average(a.input for a in attempts),
            output=self.average(a.output for a in attempts),
            agent_errors=sum(a.stop == "agent_failure" for a in attempts),
            model_errors=sum(a.stop == "model_failure" for a in attempts),
        )

    def scenarios(self) -> dict[str, ScenarioView]:
        return {id: self.scenario(played) for id, played in self.played().items()}

    def scenario(self, played: Played) -> ScenarioView:
        attempts = tuple(self.attempt(played.scenario, o) for o in played.outcomes)
        turns = [turn.seconds for attempt in attempts for turn in attempt.turns]
        claims = tuple(
            ClaimSummary(
                text,
                held=sum(a.claims[i].passed is True for a in attempts if a.claims),
                judged=sum(a.claims[i].passed is not None for a in attempts if a.claims),
            )
            for i, text in enumerate(played.scenario.claims)
        )
        return ScenarioView(
            id=played.scenario.id,
            user=played.scenario.instructions,
            max_turns=played.scenario.max_turns,
            result=played.result(),
            claims=claims,
            seconds=self.average(turns),
            slowest=max(turns, default=None),
            input=self.average(a.input for a in attempts),
            output=self.average(a.output for a in attempts),
            attempts=attempts,
        )

    def attempt(self, scenario: Scenario, outcome: Outcome) -> AttemptView:
        turns = tuple(self.turn(turn) for turn in outcome.transcript.turns)
        match outcome.verdict:
            case Verdict(claims=decided) as verdict:
                judged: tuple[bool | None, str] = (verdict.passed, "")
                claims = tuple(ClaimView(claim.passed, claim.reason) for claim in decided)
            case Failed(reason=reason):
                judged = (False, reason)
                claims = tuple(ClaimView(None, "") for _ in scenario.claims)
            case NoVerdict(error=error):
                judged = (None, error)
                claims = tuple(ClaimView(None, "") for _ in scenario.claims)
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


class Report(Struct, frozen=True):
    """A run's page, `<agent>/<id>/report.html`. Every number and decision on it is made here;
    the page only draws."""

    run: Run

    def page(self) -> RunPage:
        summary = Summary(self.run)
        scenarios = sorted(summary.scenarios().values(), key=lambda s: (ORDER[s.result], s.id))
        return RunPage(summary.head(), summary.metrics(), tuple(scenarios))

    def html(self) -> str:
        return Template("run.html").html(self.page())


class Comparison(Struct, frozen=True):
    """Two runs side by side, `compare/<before>-vs-<after>.html`: what changed from `before` to
    `after`, scenario by scenario."""

    before: Run
    after: Run

    def page(self) -> ComparePage:
        was, now = Summary(self.before), Summary(self.after)
        before, after = was.played(), now.played()
        views = (was.scenarios(), now.scenarios())
        rows = [self.row(id, before.get(id), after.get(id), views) for id in {*before, *after}]
        rows.sort(key=lambda row: (GROUPS[row.group], row.id))
        return ComparePage(
            before=was.head(),
            after=now.head(),
            was=was.metrics(),
            now=now.metrics(),
            deltas=self.deltas(was.metrics(), now.metrics(), before, after),
            models=self.models(),
            rows=tuple(rows),
        )

    def html(self) -> str:
        return Template("compare.html").html(self.page())

    def models(self) -> tuple[str, ...]:
        """The convy models that differ between the runs, as `judge: a → b`."""
        before, after = self.before.spec, self.after.spec
        pairs = (("user", before.user, after.user), ("judge", before.judge, after.judge))
        return tuple(f"{role}: {was} → {now}" for role, was, now in pairs if was != now)

    def row(
        self,
        id: str,
        before: Played | None,
        after: Played | None,
        views: tuple[dict[str, ScenarioView], dict[str, ScenarioView]],
    ) -> CompareRow:
        was, now = views[0].get(id), views[1].get(id)
        if before is None or after is None:
            why = "only in the after run" if before is None else "only in the before run"
            return CompareRow(id, "apart", why, was, now, ())
        if before.scenario.fingerprint() != after.scenario.fingerprint():
            return CompareRow(id, "apart", "edited between the runs", was, now, ())
        old, new = before.rate(), after.rate()
        if old is None or new is None:
            return CompareRow(id, "apart", "no verdict in one of the runs", was, now, ())
        group: Group = "worse" if new < old else "better" if new > old else "same"
        return CompareRow(id, group, "", was, now, self.claims(views[0][id], views[1][id]))

    def claims(self, was: ScenarioView, now: ScenarioView) -> tuple[ClaimChange, ...]:
        changes = []
        for old, new in zip(was.claims, now.claims, strict=True):
            before = old.held / old.judged if old.judged else None
            after = new.held / new.judged if new.judged else None
            if before is None or after is None or before == after:
                change: Literal["unchanged", "worse", "better"] = "unchanged"
            else:
                change = "better" if after > before else "worse"
            changes.append(ClaimChange(new.text, old.result(), new.result(), change))
        return tuple(changes)

    def deltas(
        self, was: Metrics, now: Metrics, before: dict[str, Played], after: dict[str, Played]
    ) -> Deltas:
        old, new = was.rate(), now.rate()
        if old is None or new is None:
            rate = Delta(None, "none")
        else:
            points = round((new - old) * 100, 6)
            agrees = self.significant(before, after) == ("good" if points > 0 else "bad")
            rate = Delta(points, self.tone(points, more_is_better=True, noisy=not agrees))
        return Deltas(
            rate=rate,
            stable=self.delta(was.stable, now.stable, more_is_better=True),
            seconds=self.delta(was.seconds, now.seconds, more_is_better=False),
            tokens=self.delta(was.tokens(), now.tokens(), more_is_better=False),
            errors=self.delta(was.errors(), now.errors(), more_is_better=False),
        )

    def delta(self, was: float | None, now: float | None, more_is_better: bool) -> Delta:
        if was is None or now is None:
            return Delta(None, "none")
        return Delta(now - was, self.tone(now - was, more_is_better=more_is_better, noisy=False))

    def tone(self, change: float, more_is_better: bool, noisy: bool) -> Tone:
        if change == 0:
            return "same"
        if noisy:
            return "noise"
        return "good" if (change > 0) == more_is_better else "bad"

    def significant(self, before: dict[str, Played], after: dict[str, Played]) -> Tone | None:
        """The pass rate's tone when the paired change over the scenarios both runs played
        unchanged is beyond its 95% margin; None when it is not."""
        differences = []
        for id, played in after.items():
            earlier = before.get(id)
            if earlier is None or earlier.scenario.fingerprint() != played.scenario.fingerprint():
                continue
            new, old = played.rate(), earlier.rate()
            if new is not None and old is not None:
                differences.append(new - old)
        margin = Sample(tuple(differences)).margin()
        if margin is None or abs(mean(differences)) <= margin:
            return None
        return "good" if mean(differences) > 0 else "bad"


class Index(Struct, frozen=True):
    """`index.html`: every run, newest first, with a link to its report."""

    runs: Iterable[Run]

    def page(self) -> IndexPage:
        rows = []
        for run in sorted(self.runs, key=lambda run: run.spec.started, reverse=True):
            summary = Summary(run)
            metrics = summary.metrics()
            report = f"{run.path.as_posix()}/report.html"
            rows.append(IndexRow(summary.head(), metrics.passed, metrics.judged, report))
        return IndexPage(tuple(rows))

    def html(self) -> str:
        return Template("index.html").html(self.page())
