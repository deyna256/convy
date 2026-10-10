"""The report: runs read back, summed up, and rendered as static HTML pages."""

import re
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
from convy.dialog import (
    Claim,
    Confidence,
    Failed,
    Grade,
    Graded,
    NoConfidence,
    NoGrade,
    NoVerdict,
    Turn,
    Verdict,
)
from convy.scenario import Outcome, Scenario, Stop

UNREADABLE = (msgspec.DecodeError, OSError)  # ValidationError is a DecodeError


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

    def broken(self, read: Iterable[Run]) -> tuple[Path, ...]:
        """The runs that could not be read whole, given the runs iterating read: the folders
        missing from them, and those with unreadable lines."""
        whole = {run.path for run in read if not run.unreadable}
        found = (folder.relative_to(self.directory) for folder in self.folders())
        return tuple(path for path in found if path not in whole)

    def run(self, wanted: str) -> Run:
        """The run whose id is `wanted`, or ends with `_<wanted>`: its random part."""
        found = [run for run in self if wanted in (run.spec.id, run.spec.short())]
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
            match outcome.verdict:  # explained by the run's snapshot of its scenarios?
                case Verdict(claims=decided):
                    fits = len(decided) == claims.get(outcome.scenario)
                case Failed() | NoVerdict():
                    fits = outcome.scenario in claims
            if not fits:
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

type Result = Literal["failing", "flaky", "passing", "none"]
type Tone = Literal["good", "bad", "same", "noise", "none"]
type Group = Literal["worse", "better", "same", "apart"]
type Change = Literal["unchanged", "worse", "better"]

ORDER: dict[Result, int] = {"failing": 0, "flaky": 1, "none": 2, "passing": 3}
GROUPS: dict[Group, int] = {"worse": 0, "better": 1, "same": 2, "apart": 3}


class Tally(Struct, frozen=True):
    """How many of the judged held: the attempts of a scenario, or the decisions on a claim."""

    held: int
    judged: int

    def rate(self) -> float | None:
        return self.held / self.judged if self.judged else None

    def result(self) -> Result:
        if not self.judged:
            return "none"
        if self.held == self.judged:
            return "passing"
        return "failing" if self.held == 0 else "flaky"


class ClaimView(Struct, frozen=True):
    """The judge's decision on one claim in one attempt."""

    passed: bool | None  # None: the judge was not asked, or gave no verdict
    reason: str
    confidence: float | None = None  # None: the judge did not say
    trusted: bool = True  # False: less sure than the run's trust
    grade: str | None = None  # None: the claim is not graded


class TurnView(Struct, frozen=True):
    user: str
    agent: str
    seconds: float
    input: int | None
    output: int | None
    tokens: int | None


class AttemptView(Struct, frozen=True):
    attempt: int
    passed: bool | None  # None: no verdict, left out of pass rates
    cut: bool  # the judge was not sure enough: left out of pass rates
    stop: Stop
    error: str  # the agent's error, or the failure of convy's model
    claims: tuple[ClaimView, ...]
    seconds: float
    slowest: float | None  # None: no answers
    input: int | None
    output: int | None
    tokens: int | None
    turns: tuple[TurnView, ...]


class ClaimSummary(Struct, frozen=True):
    """A claim over a scenario's attempts that have a verdict."""

    text: str
    held: int
    judged: int
    result: Result
    cut: int  # decisions less sure than the run's trust
    grades: tuple[tuple[str, int], ...] = ()  # each grade, worst to best, and how many trusted
    typical: str | None = None  # the median trusted grade, the worse of two; None: not graded


class ScenarioView(Struct, frozen=True):
    id: str
    user: str
    max_turns: int
    rate: float | None
    result: Result
    claims: tuple[ClaimSummary, ...]
    seconds: float | None  # mean per answer
    slowest: float | None
    input: float | None  # mean per attempt
    output: float | None
    tokens: float | None
    attempts: tuple[AttemptView, ...]


class Metrics(Struct, frozen=True):
    """The tiles of a run: the numbers behind them."""

    passed: int  # judged attempts that passed
    judged: int
    cut: int  # attempts left out because the judge was not sure enough
    rate: float | None
    stable: int  # scenarios whose k attempts all passed
    seconds: float | None  # mean per answer
    slowest: float | None
    input: float | None  # mean per attempt
    output: float | None
    tokens: float | None
    agent_errors: int
    model_errors: int
    errors: int


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
    trust: float
    confident: bool  # some decision of the run says how sure the judge was


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
    change: Change  # by the pass rate; when that is equal, as `moved`
    was: str | None = None  # the typical grade before; None: not graded
    now: str | None = None
    moved: Change = "unchanged"  # where the typical grade went, whatever the pass rate did


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
    cut: int
    rate: float | None
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


class Template(Struct, frozen=True):
    """A page in `convy/pages/`, assembled from the shared parts its `/*include <file>*/`
    placeholders name and filled with its data: a written page stands alone."""

    name: str

    def html(self, data: Struct) -> str:
        # ponytail: every dialogue of a run is in its page (~5 KB per attempt); load
        # attempts.jsonl lazily when pages get heavy
        encoded = msgspec.json.encode(data).decode().replace("<", "\\u003c")
        folder = files("convy").joinpath("pages")
        page = re.sub(
            r"/\*include (\S+)\*/",
            lambda match: folder.joinpath(match[1]).read_text(encoding="utf-8"),
            folder.joinpath(self.name).read_text(encoding="utf-8"),
        )
        return page.replace("__DATA__", encoded)


class Summary(Struct, frozen=True):
    """A run summed up for the pages: its head, a view per scenario, and its tiles."""

    run: Run

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
            short=spec.short(),
            agent=spec.agent,
            version=spec.version,
            started=spec.started.isoformat(),
            status=status,
            user=spec.user,
            judge=spec.judge,
            k=spec.k,
            scenarios=len(spec.scenarios),
            unreadable=self.run.unreadable,
            trust=spec.trust,
            confident=self.confident(),
        )

    def confident(self) -> bool:
        """Whether some decision of the run says how sure the judge was: only then does a page
        mark the decisions that do not."""
        for outcome in self.run.outcomes:
            match outcome.verdict:
                case Verdict(claims=claims) if any(c.confidence != NoConfidence() for c in claims):
                    return True
        return False

    def metrics(self, scenarios: Iterable[ScenarioView]) -> Metrics:
        """The tiles over the views `scenarios()` made."""
        views = list(scenarios)
        attempts = [attempt for view in views for attempt in view.attempts]
        judged = [a.passed for a in attempts if a.passed is not None]
        turns = [turn.seconds for attempt in attempts for turn in attempt.turns]
        k = self.run.spec.k
        agent_errors = sum(a.stop == "agent_failure" for a in attempts)
        model_errors = sum(a.stop == "model_failure" for a in attempts)
        return Metrics(
            passed=sum(judged),
            judged=len(judged),
            cut=sum(a.cut for a in attempts),
            rate=Tally(sum(judged), len(judged)).rate(),
            stable=sum(
                len(v.attempts) == k and all(a.passed is True for a in v.attempts) for v in views
            ),
            seconds=self.average(turns),
            slowest=max(turns, default=None),
            input=self.average(a.input for a in attempts),
            output=self.average(a.output for a in attempts),
            tokens=self.average(a.tokens for a in attempts),
            agent_errors=agent_errors,
            model_errors=model_errors,
            errors=agent_errors + model_errors,
        )

    def scenarios(self) -> dict[str, ScenarioView]:
        """The run's scenarios by id, each with its recorded attempts in order."""
        return {scenario.id: self.scenario(scenario) for scenario in self.run.spec.scenarios}

    def scenario(self, scenario: Scenario) -> ScenarioView:
        played = sorted(
            (o for o in self.run.outcomes if o.scenario == scenario.id), key=lambda o: o.attempt
        )
        attempts = tuple(self.attempt(scenario, outcome) for outcome in played)
        judged = [a.passed for a in attempts if a.passed is not None]
        tally = Tally(sum(judged), len(judged))
        turns = [turn.seconds for attempt in attempts for turn in attempt.turns]
        return ScenarioView(
            id=scenario.id,
            user=scenario.instructions,
            max_turns=scenario.max_turns,
            rate=tally.rate(),
            result=tally.result(),
            claims=tuple(
                self.claim(claim, [a.claims[i] for a in attempts])
                for i, claim in enumerate(scenario.claims)
            ),
            seconds=self.average(turns),
            slowest=max(turns, default=None),
            input=self.average(a.input for a in attempts),
            output=self.average(a.output for a in attempts),
            tokens=self.average(a.tokens for a in attempts),
            attempts=attempts,
        )

    def claim(self, claim: str | Graded, decisions: list[ClaimView]) -> ClaimSummary:
        """A claim over the attempts the judge decided, cut or not: its trusted decisions are
        tallied, the rest counted as cut. A graded claim also counts each grade."""
        trusted = [d for d in decisions if d.passed is not None and d.trusted]
        tally = Tally(sum(d.passed is True for d in trusted), len(trusted))
        cut = sum(d.passed is not None and not d.trusted for d in decisions)
        match claim:
            case str():
                return ClaimSummary(claim, tally.held, tally.judged, tally.result(), cut)
            case Graded(text=text, levels=levels):
                ranks = sorted(levels.index(d.grade) for d in trusted if d.grade in levels)
                return ClaimSummary(
                    text,
                    tally.held,
                    tally.judged,
                    tally.result(),
                    cut,
                    grades=tuple((level, ranks.count(i)) for i, level in enumerate(levels)),
                    typical=levels[ranks[(len(ranks) - 1) // 2]] if ranks else None,
                )

    def attempt(self, scenario: Scenario, outcome: Outcome) -> AttemptView:
        turns = tuple(self.turn(turn) for turn in outcome.transcript.turns)
        trust = self.run.spec.trust
        cut = False
        match outcome.verdict:
            case Verdict(claims=decided) as verdict:
                cut = not verdict.decided(trust)
                judged: tuple[bool | None, str] = (None if cut else verdict.passed, "")
                claims = tuple(self.decision(claim, trust) for claim in decided)
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
            cut=cut,
            stop=outcome.stop,
            error=error,
            claims=claims,
            seconds=sum(turn.seconds for turn in turns),
            slowest=max((turn.seconds for turn in turns), default=None),
            input=self.total(turn.input for turn in turns),
            output=self.total(turn.output for turn in turns),
            tokens=self.total(turn.tokens for turn in turns),
            turns=turns,
        )

    def decision(self, claim: Claim, trust: float) -> ClaimView:
        match claim.confidence:
            case Confidence(value=value):
                sure: float | None = value
            case NoConfidence():
                sure = None
        match claim.grade:
            case Grade(value=value):
                grade: str | None = value
            case NoGrade():
                grade = None
        return ClaimView(claim.passed, claim.reason, sure, claim.trusted(trust), grade)

    def turn(self, turn: Turn) -> TurnView:
        match turn.answer.usage:
            case Usage(input=spent, output=produced):
                tokens: tuple[int | None, int | None, int | None] = (
                    spent,
                    produced,
                    spent + produced,
                )
            case NoUsage():
                tokens = (None, None, None)
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
        views = summary.scenarios().values()
        scenarios = sorted(views, key=lambda s: (ORDER[s.result], s.id))
        return RunPage(summary.head(), summary.metrics(views), tuple(scenarios))

    def html(self) -> str:
        return Template("run.html").html(self.page())


class Comparison(Struct, frozen=True):
    """Two runs side by side, `compare/<before>-vs-<after>.html`: what changed from `before` to
    `after`, scenario by scenario."""

    before: Run
    after: Run

    def page(self) -> ComparePage:
        was, now = Summary(self.before), Summary(self.after)
        before, after = was.scenarios(), now.scenarios()
        unchanged = self.unchanged()
        rows = [self.row(id, before.get(id), after.get(id), unchanged) for id in {*before, *after}]
        rows.sort(key=lambda row: (GROUPS[row.group], row.id))
        old, new = was.metrics(before.values()), now.metrics(after.values())
        return ComparePage(
            before=was.head(),
            after=now.head(),
            was=old,
            now=new,
            deltas=self.deltas(old, new, self.significant(before, after, unchanged)),
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

    def unchanged(self) -> set[str]:
        """The scenarios both runs have, not edited between them."""
        before = {scenario.id: scenario for scenario in self.before.spec.scenarios}
        return {s.id for s in self.after.spec.scenarios if before.get(s.id) == s}

    def row(
        self, id: str, was: ScenarioView | None, now: ScenarioView | None, unchanged: set[str]
    ) -> CompareRow:
        if was is None or now is None:
            why = "only in the after run" if was is None else "only in the before run"
            return CompareRow(id, "apart", why, was, now, ())
        if id not in unchanged:
            return CompareRow(id, "apart", "edited between the runs", was, now, ())
        if was.rate is None or now.rate is None:
            return CompareRow(id, "apart", "no verdict in one of the runs", was, now, ())
        group: Group = (
            "worse" if now.rate < was.rate else "better" if now.rate > was.rate else "same"
        )
        return CompareRow(id, group, "", was, now, self.claims(was, now))

    def claims(self, was: ScenarioView, now: ScenarioView) -> tuple[ClaimChange, ...]:
        changes = []
        for old, new in zip(was.claims, now.claims, strict=True):
            before = Tally(old.held, old.judged).rate()
            after = Tally(new.held, new.judged).rate()
            moved: Change = "unchanged"
            if old.typical and new.typical and old.typical != new.typical:
                levels = [grade for grade, _ in new.grades]  # the same before: not edited
                up = levels.index(new.typical) > levels.index(old.typical)
                moved = "better" if up else "worse"
            change: Change = moved
            if before is not None and after is not None and before != after:
                change = "better" if after > before else "worse"
            changes.append(
                ClaimChange(
                    new.text, old.result, new.result, change, old.typical, new.typical, moved
                )
            )
        return tuple(changes)

    def deltas(
        self, was: Metrics, now: Metrics, significant: Literal["good", "bad"] | None
    ) -> Deltas:
        if was.rate is None or now.rate is None:
            rate = Delta(None, "none")
        else:
            points = round((now.rate - was.rate) * 100, 6)
            agrees = significant == ("good" if points > 0 else "bad")
            rate = Delta(points, self.tone(points, more_is_better=True, noisy=not agrees))
        return Deltas(
            rate=rate,
            stable=self.delta(was.stable, now.stable, more_is_better=True),
            seconds=self.delta(was.seconds, now.seconds, more_is_better=False),
            tokens=self.delta(was.tokens, now.tokens, more_is_better=False),
            errors=self.delta(was.errors, now.errors, more_is_better=False),
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

    def significant(
        self, before: dict[str, ScenarioView], after: dict[str, ScenarioView], unchanged: set[str]
    ) -> Literal["good", "bad"] | None:
        """The pass rate's tone when the paired change over the scenarios both runs played
        unchanged is beyond its 95% margin; None when it is not."""
        differences = []
        for id in unchanged:
            new, old = after[id].rate, before[id].rate
            if new is not None and old is not None:
                differences.append(new - old)
        sample = Sample(tuple(differences))
        change, margin = sample.mean(), sample.margin()
        if change is None or margin is None or abs(change) <= margin:
            return None
        return "good" if change > 0 else "bad"


class Index(Struct, frozen=True):
    """`index.html`: every run, newest first, with a link to its report."""

    runs: Iterable[Run]

    def page(self) -> IndexPage:
        rows = []
        for run in sorted(self.runs, key=lambda run: run.spec.started, reverse=True):
            summary = Summary(run)
            metrics = summary.metrics(summary.scenarios().values())
            report = f"{run.path.as_posix()}/report.html"
            rows.append(
                IndexRow(
                    summary.head(),
                    metrics.passed,
                    metrics.judged,
                    metrics.cut,
                    metrics.rate,
                    report,
                )
            )
        return IndexPage(tuple(rows))

    def html(self) -> str:
        return Template("index.html").html(self.page())
