"""The report: runs read back, summed up, and rendered as static HTML pages."""

import math
import re
from collections.abc import Iterable, Iterator, Sequence
from importlib.resources import files
from math import comb
from pathlib import Path
from statistics import mean, quantiles
from typing import Literal

import msgspec
from msgspec import Struct

from convy.agent import Call, NotReported, NoUsage, Reported, Thought, Usage
from convy.bench import Finished, Interrupted, Limits, Pair, RunFile, Running, RunSpec, Status
from convy.dialog import (
    Claim,
    Confidence,
    Failed,
    Grade,
    Graded,
    NoConfidence,
    NoGrade,
    NoReason,
    NoVerdict,
    Reason,
    Turn,
    Verdict,
)
from convy.scenario import Outcome, Scenario, Stop

UNREADABLE = (msgspec.DecodeError, OSError)  # ValidationError is a DecodeError


class OlderLine(Struct, frozen=True):
    """An attempt line of an older format, read as format 6: format 2 kept a claim's reason as a
    string, formats before 5 kept the agent's thinking apart from the steps of its answer, and
    formats 3 to 5 wrote 0 for a thinking count the agent did not give. Reading drops the old
    `thinking` field, as fields an `Outcome` does not have."""

    line: bytes

    def outcome(self) -> Outcome:
        data = msgspec.json.decode(self.line)
        match data:
            case {"verdict": {"type": "verdict", "claims": list() as claims}}:
                data["verdict"]["claims"] = [self.claim(claim) for claim in claims]
        match data:
            case {"transcript": {"turns": list() as turns}}:
                data["transcript"]["turns"] = [self.turn(turn) for turn in turns]
        return msgspec.convert(data, Outcome)

    def turn(self, turn: object) -> object:
        match turn:
            case {"answer": {"thinking": {"type": "thinking", "text": str() as text}} as answer}:
                turn = {**turn, "answer": {**answer, "steps": [{"type": "thought", "text": text}]}}
        match turn:
            case {"answer": dict() as answer}:
                return {**turn, "answer": self.answer(answer)}
            case _:
                return turn

    def answer(self, answer: dict) -> dict:
        """The answer, with its usage and its calls' usage read as format 6."""
        match answer:
            case {"usage": usage}:
                answer = {**answer, "usage": self.usage(usage)}
        match answer:
            case {"steps": list() as steps}:
                answer = {**answer, "steps": [self.step(step) for step in steps]}
        return answer

    def step(self, step: object) -> object:
        match step:
            case {"type": "call", "usage": usage}:
                return {**step, "usage": self.usage(usage)}
            case _:
                return step

    def usage(self, usage: object) -> object:
        """0 was the default thinking count, not one the agent gave."""
        match usage:
            case {"type": "usage", "thinking": 0}:
                return {**usage, "thinking": {"type": "not_reported"}}
            case _:
                return usage

    def claim(self, claim: object) -> object:
        match claim:
            case {"reason": str() as text}:
                reason = {"type": "reason", "text": text} if text.strip() else {"type": "no_reason"}
                return {**claim, "reason": reason}
            case _:
                return claim


class OlderSpec(Struct, frozen=True):
    """What the specification of a `run.json` of format 2 or 3 held instead of `limits`: one
    `parallel`, which held all three participants."""

    parallel: int


class OlderRunFile(Struct, frozen=True):
    """A `run.json` of format 2 or 3, as far as format 4 changed it."""

    spec: OlderSpec


class Run(Struct, frozen=True):
    """A run's folder read back: where it is under the results directory, its specification and
    status, the outcomes it could read, how many lines it could not, and the format it was written
    in."""

    path: Path
    spec: RunSpec
    status: Status
    outcomes: tuple[Outcome, ...]
    unreadable: int = 0
    format: Literal[2, 3, 4, 5, 6] = 6

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
        raw = (folder / "run.json").read_bytes()
        file = msgspec.json.decode(raw, type=RunFile)
        if file.format < 4:
            shared = msgspec.json.decode(raw, type=OlderRunFile).spec.parallel
            limits = Limits(agent=shared, user=shared, judge=shared)
            file = msgspec.structs.replace(
                file, spec=msgspec.structs.replace(file.spec, limits=limits)
            )
        attempts = folder / "attempts.jsonl"
        lines = attempts.read_bytes().splitlines() if attempts.exists() else []
        claims = {scenario.id: len(scenario.claims) for scenario in file.spec.scenarios}
        outcomes: dict[Pair, Outcome] = {}
        unreadable = 0
        for line in lines:
            try:
                outcome = (
                    msgspec.json.decode(line, type=Outcome)
                    if file.format >= 6
                    else OlderLine(line).outcome()
                )
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
            file.format,
        )


# The pages' data. It is JSON for the browser, so a number nobody reported is None (null).

type Result = Literal["failing", "flaky", "passing", "none"]
type Tone = Literal["good", "bad", "same", "noise", "none"]
type Group = Literal["worse", "better", "same", "apart"]
type Change = Literal["unchanged", "worse", "better"]
type Stat = Literal["p50", "p90", "max", "mean"]  # what a chart shows of a spread

ORDER: dict[Result, int] = {"failing": 0, "flaky": 1, "none": 2, "passing": 3}
GROUPS: dict[Group, int] = {"worse": 0, "better": 1, "same": 2, "apart": 3}
SLIGHT = 5  # percent: a smaller change of a time or token statistic is drawn as the same
TONES: dict[Group, Tone] = {"worse": "bad", "better": "good", "same": "same", "apart": "none"}
STATS: tuple[Stat, ...] = ("p50", "p90", "max", "mean")  # the switch's order
FAR = 3  # interquartile ranges past the upper quartile, on a log scale: Tukey's far-out fence


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


class Ranking(Struct, frozen=True):
    """Ids by a number, the largest first and ties by id; ids without the number last, by id."""

    numbers: tuple[tuple[str, float | None], ...]

    def ids(self) -> tuple[str, ...]:
        ranked = sorted(self.numbers, key=lambda pair: (pair[1] is None, -(pair[1] or 0), pair[0]))
        return tuple(id for id, _ in ranked)


class Spread(Struct, frozen=True):
    """How numbers spread: how many, the least, the 50th and 90th percentiles, the most and the
    mean."""

    n: int
    min: float
    p50: float
    p90: float
    max: float
    mean: float

    def of(self, stat: Stat) -> float:
        return getattr(self, stat)  # a Stat is a field's name


class PerStat[T](Struct, frozen=True):
    """One value per statistic the switch offers: an order, a change. Its fields are `STATS`."""

    p50: T
    p90: T
    max: T
    mean: T

    def of(self, stat: Stat) -> T:
        return getattr(self, stat)  # a Stat is a field's name


class ClaimView(Struct, frozen=True):
    """The judge's decision on one claim in one attempt."""

    passed: bool | None  # None: the judge was not asked, or gave no verdict
    reason: str
    confidence: float | None = None  # None: the judge did not say
    trusted: bool = True  # False: less sure than the run's trust
    grade: str | None = None  # None: the claim is not graded


class ThoughtView(Struct, frozen=True, tag="thought"):
    text: str


class CallView(Struct, frozen=True, tag="call", kw_only=True):
    name: str
    seconds: float
    left: float  # where its bar starts on the answer's time line of calls, 0..1
    width: float  # how much of that line it takes, 0..1
    start: float  # seconds after the answer's first call started
    tokens: int | None  # input + output; None: not reported
    sent: str | None  # None: not reported; "" was reported empty
    received: str | None


class TurnView(Struct, frozen=True):
    user: str
    agent: str
    seconds: float
    input: int | None
    output: int | None
    tokens: int | None
    thinking_tokens: int | None  # part of output
    cache_read: int | None  # part of input
    cache_write: int | None  # part of input
    steps: tuple[ThoughtView | CallView, ...]
    thoughts: int  # how many of the steps are thoughts
    calls: int  # and how many are calls
    span: float  # seconds from the first call's start to the last call's end; 0 without calls


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
    thinking_tokens: int | None
    cache_read: int | None
    cache_write: int | None
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


class Parts(Struct, frozen=True):
    """A scenario's mean tokens per attempt by part, over its attempts that report tokens: the
    parts add up to the mean. A part the agent does not report is None and stays in the whole:
    without cache reads `input` is all the input, without thinking `output` all the output."""

    cached: float | None  # input read from the cache
    input: float  # the rest of the input, cache writes included
    output: float  # the rest of the output
    thinking: float | None


class Shares(Struct, frozen=True):
    """Each part's share of the tokens, 0..1, None for a part not reported; and the share of the
    input read from the cache, None when the cache is not reported or the input is 0."""

    cached: float | None
    input: float
    output: float
    thinking: float | None
    read: float | None


class ScenarioView(Struct, frozen=True):
    id: str
    user: str
    max_turns: int
    held: int  # attempts that passed, of the judged
    judged: int
    rate: float | None
    result: Result
    claims: tuple[ClaimSummary, ...]
    seconds: Spread | None  # per answer
    tokens: Spread | None  # per attempt that reports them
    parts: Parts | None  # None: no attempt reports tokens
    shares: Shares | None
    attempts: tuple[AttemptView, ...]

    def parted(self, stat: Stat) -> float | None:
        """A statistic of the tokens per attempt when the parts are known, which orders
        `by_parts`."""
        return None if self.parts is None or self.tokens is None else self.tokens.of(stat)


class Metrics(Struct, frozen=True):
    """The tiles of a run: the numbers behind them."""

    passed: int  # judged attempts that passed
    judged: int
    cut: int  # attempts left out because the judge was not sure enough
    open: int  # attempts without a verdict: convy's models failed, or the agent stayed busy
    rate: float | None
    stable: int  # scenarios whose k attempts all passed
    flaky: int  # scenarios with passed and failed attempts
    seconds: Spread | None  # per answer
    tokens: Spread | None  # per attempt that reports them
    cached: float | None  # share of input read from the cache, over the turns that report it
    agent_errors: int
    busy: int  # attempts whose agent's service stayed busy
    model_errors: int
    errors: int


class TurnStats(Struct, frozen=True):
    """The answers at one turn number of a run's dialogues, from 1, and their tokens."""

    turn: int
    answers: int  # every answer at this turn
    scenarios: int  # how many scenarios they come from
    input: Spread | None  # over the answers that report tokens
    output: Spread | None
    cached: Spread | None  # their cache reads, when every one of them reports its own
    share: float | None  # the share of their input read from the cache, when every one reports it


class TurnPair(Struct, frozen=True):
    turn: int
    before: TurnStats | None  # None: no answer of the run at this turn reports tokens
    after: TurnStats | None


class CallPlace(Struct, frozen=True):
    """Where one call was made: its scenario, attempt, turn and step, the last two from 0."""

    scenario: str
    attempt: int
    turn: int
    step: int
    seconds: float
    tokens: int | None


class Delta(Struct, frozen=True):
    """A change from before to after and how to read it: in the metric's own unit, or, for a
    scenario's time and tokens on the comparison, a percent of the old value."""

    value: float | None
    tone: Tone


NO_CHANGE = Delta(None, "none")
NO_CHANGES = PerStat(NO_CHANGE, NO_CHANGE, NO_CHANGE, NO_CHANGE)


class Answered(Struct, frozen=True):
    """An answer and where it was given: its scenario, attempt and turn, from 0."""

    scenario: str
    attempt: int
    number: int
    turn: TurnView


class Category(Struct, frozen=True):
    """The agent's calls of one name, as its answers report them. Its seconds are per answer it
    has calls in."""

    name: str
    answers: int  # the answers kept that it has calls in
    calls: int
    total: float  # its seconds together
    spread: Spread  # per answer it has a number in
    places: tuple[CallPlace, ...]  # its calls in the answers kept, the slowest first
    average: float  # its total over every answer kept: what it adds to an answer on average
    tokens: float | None  # its calls' tokens over every answer kept; None: none reported
    share: float  # its part of every call name's seconds together, 0..1


class Measure(Struct, frozen=True):
    """One number per answer over the run, its time or its tokens, with or without outliers."""

    spread: Spread | None  # over the answers kept
    answers: int  # the answers kept with the number


class ScenarioNumbers(Struct, frozen=True):
    seconds: Spread | None  # per answer kept
    tokens: Spread | None


class View(Struct, frozen=True):
    """The run's time and token numbers with or without outliers: every tile, chart and table of
    them on the run's page."""

    seconds: Measure
    tokens: Measure
    scenarios: tuple[ScenarioNumbers, ...]  # in the page's order of the scenarios
    time: tuple[Category, ...]  # the most in total first, then by name, uncovered time first
    parts: Parts | None  # the tokens per answer by part, over the answers kept that report them
    shares: Shares | None
    out: tuple[str, ...] = ()  # the scenarios cut, in the page's order: every number leaves them


class Views(Struct, frozen=True):
    """The run's numbers with every scenario, and with the scenarios of outliers cut."""

    all: View
    cut: View


class Share(Struct, frozen=True):
    """The scenarios at one pass rate."""

    rate: float | None  # None: no verdict
    result: Result
    scenarios: tuple[str, ...]
    part: float  # their share of the run's scenarios, 0..1


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


class Deltas(Struct, frozen=True):
    rate: Delta  # percentage points
    stable: Delta
    seconds: PerStat[Delta]  # each statistic's change in seconds; Max's is noise
    tokens: PerStat[Delta]  # and in tokens
    cached: Delta  # percentage points
    errors: Delta


class RunPage(Struct, frozen=True):
    run: RunHead
    metrics: Metrics
    scenarios: tuple[ScenarioView, ...]  # failing, flaky, no verdict, passing; each by id
    results: tuple[Share, ...]  # by pass rate from 0, no verdict last
    views: Views


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
    held: Delta  # the change in passed attempts, in the tone of the row's group
    seconds: PerStat[Delta]  # the change of each statistic of the time per answer, a percent
    tokens: PerStat[Delta]  # and of the tokens per attempt


class ComparePage(Struct, frozen=True):
    before: RunHead
    after: RunHead
    was: Metrics
    now: Metrics
    deltas: Deltas
    differences: tuple[str, ...]  # the models and the convy that differ, as "judge: a → b"
    rows: tuple[CompareRow, ...]  # worse, better, same, not compared; each by id
    by_seconds: PerStat[tuple[str, ...]]  # compared ids with a change, the largest rise first
    by_tokens: PerStat[tuple[str, ...]]
    turns: tuple[TurnPair, ...]  # every turn number either run has tokens at
    by_parts: PerStat[
        tuple[str, ...]
    ]  # compared ids with parts in both runs, the after's most first


class IndexRow(Struct, frozen=True):
    run: RunHead
    rate: float | None
    passed: int
    judged: int
    cut: int  # attempts not trusted
    errors: int
    result: Result
    changes: tuple[str, ...]  # the setup changed since the agent's run before: `judge: a → b`
    order: int  # the run's place among every run of the index, 0 the newest
    report: str  # the run's report, relative to the index


class AgentRuns(Struct, frozen=True):
    agent: str
    rows: tuple[IndexRow, ...]  # newest first


class IndexPage(Struct, frozen=True):
    agents: tuple[AgentRuns, ...]  # by name


class Evidence(Struct, frozen=True):
    """What the scenarios both runs played unchanged say about a change: each scenario's tally
    before and after."""

    scenarios: tuple[tuple[Tally, Tally], ...]

    def shows(self) -> Literal["better", "worse"] | None:
        """The change the evidence shows: where the passes moved against what chance expects;
        None when `chance()` is 5% or more."""
        if self.chance() >= 0.05:
            return None
        return "better" if self.seen() > self.expected() else "worse"

    def chance(self) -> float:
        """How often chance alone — the same agent on the same scenarios — gives a result as
        unlikely as this one or more: the exact two-sided test over the scenarios' attempts."""
        totals = self.totals()
        limit = totals[self.seen()] * (1 + 1e-7)  # floats that should be equal, as R allows
        return min(1.0, sum(p for p in totals.values() if p <= limit))

    def totals(self) -> dict[int, float]:
        """How the after run's passes add up over the scenarios, if nothing changed."""
        # ponytail: the work grows with scenarios times attempts (200 scenarios of 50 attempts
        # take up to ~18 s); use the CMH chi-square past that size
        totals = {0: 1.0}
        for before, after in self.scenarios:
            law = self.law(before, after)
            sums: dict[int, float] = {}
            for total, p in totals.items():
                for passes, q in law.items():
                    sums[total + passes] = sums.get(total + passes, 0.0) + p * q
            totals = sums
        return totals

    def law(self, before: Tally, after: Tally) -> dict[int, float]:
        """How the after run's passes of one scenario fall if nothing changed: drawn from the
        scenario's attempts and passes, a hypergeometric law."""
        attempts, passes = before.judged + after.judged, before.held + after.held
        drawn = after.judged
        ways = comb(attempts, drawn)
        return {
            x: comb(passes, x) * comb(attempts - passes, drawn - x) / ways
            for x in range(max(0, drawn - (attempts - passes)), min(passes, drawn) + 1)
        }

    def seen(self) -> int:
        return sum(after.held for _, after in self.scenarios)

    def expected(self) -> float:
        return sum(
            after.judged * (before.held + after.held) / (before.judged + after.judged)
            for before, after in self.scenarios
        )


class Template(Struct, frozen=True):
    """A page in `convy/pages/`, assembled from the shared parts its `/*include <file>*/`
    placeholders name and filled with its data: a written page stands alone."""

    name: str

    def html(self, data: Struct) -> str:
        # ponytail: every dialogue of a run is in its page (~5 KB per attempt, more with what the
        # agent's calls sent and received); load attempts.jsonl lazily when pages get heavy
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
        busy = sum(a.stop == "agent_busy" for a in attempts)
        model_errors = sum(a.stop == "model_failure" for a in attempts)
        return Metrics(
            passed=sum(judged),
            judged=len(judged),
            cut=sum(a.cut for a in attempts),
            open=sum(a.passed is None and not a.cut for a in attempts),
            rate=Tally(sum(judged), len(judged)).rate(),
            stable=sum(
                len(v.attempts) == k and all(a.passed is True for a in v.attempts) for v in views
            ),
            flaky=sum(v.result == "flaky" for v in views),
            seconds=self.spread(turns),
            tokens=self.spread(a.tokens for a in attempts),
            cached=self.share(turn for attempt in attempts for turn in attempt.turns),
            agent_errors=agent_errors,
            busy=busy,
            model_errors=model_errors,
            errors=agent_errors + busy + model_errors,
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
        parts, shares = self.split(self.parts(attempts))
        return ScenarioView(
            id=scenario.id,
            user=scenario.instructions,
            max_turns=scenario.max_turns,
            held=tally.held,
            judged=tally.judged,
            rate=tally.rate(),
            result=tally.result(),
            claims=tuple(
                self.claim(claim, [a.claims[i] for a in attempts])
                for i, claim in enumerate(scenario.claims)
            ),
            seconds=self.spread(turns),
            tokens=self.spread(a.tokens for a in attempts),
            parts=parts,
            shares=shares,
            attempts=attempts,
        )

    def parts(self, attempts: Sequence[AttemptView | TurnView]) -> Parts | None:
        """The mean tokens per attempt, or per answer, by part, from the sums over those that
        report tokens; cache reads and thinking over the answers that report them."""
        counted = [a for a in attempts if a.tokens is not None]
        if not counted:
            return None
        cached = self.total(a.cache_read for a in counted)
        thinking = self.total(a.thinking_tokens for a in counted)
        spent = sum(a.input or 0 for a in counted)
        produced = sum(a.output or 0 for a in counted)
        n = len(counted)
        return Parts(
            cached=None if cached is None else cached / n,
            input=(spent - (cached or 0)) / n,
            output=(produced - (thinking or 0)) / n,
            thinking=None if thinking is None else thinking / n,
        )

    def turns(self, scenarios: Iterable[ScenarioView]) -> tuple[TurnStats, ...]:
        """Each turn number of the dialogues, from 1, with the tokens of its answers; a turn none
        of whose answers reports tokens is left out."""
        at: dict[int, list[tuple[str, TurnView]]] = {}
        for view in scenarios:
            for attempt in view.attempts:
                for number, turn in enumerate(attempt.turns, 1):
                    at.setdefault(number, []).append((view.id, turn))
        stats = []
        for number, answers in sorted(at.items()):
            spent = [turn for _, turn in answers if turn.tokens is not None]
            reads = [turn.cache_read for turn in spent]
            if spent:
                stats.append(
                    TurnStats(
                        turn=number,
                        answers=len(answers),
                        scenarios=len({id for id, _ in answers}),
                        input=self.spread(turn.input for turn in spent),
                        output=self.spread(turn.output for turn in spent),
                        cached=None if None in reads else self.spread(reads),
                        share=None if None in reads else self.share(spent),
                    )
                )
        return tuple(stats)

    def results(self, scenarios: Iterable[ScenarioView]) -> tuple[Share, ...]:
        """The scenarios by pass rate, from 0; those without a verdict last."""
        at: dict[float | None, list[ScenarioView]] = {}
        for view in scenarios:
            at.setdefault(view.rate, []).append(view)
        rates = sorted(at, key=lambda rate: (rate is None, rate or 0))
        total = sum(len(views) for views in at.values())
        return tuple(
            Share(
                rate,
                at[rate][0].result,
                tuple(sorted(v.id for v in at[rate])),
                len(at[rate]) / total,
            )
            for rate in rates
        )

    def views(self, scenarios: Sequence[ScenarioView]) -> Views:
        return Views(self.view(scenarios, cut=False), self.view(scenarios, cut=True))

    def view(self, scenarios: Sequence[ScenarioView], cut: bool) -> View:
        """The time and tokens of the answers of `scenarios`, with the outliers' scenarios left
        out when `cut` says so. The unit is the scenario: one answer past the fence of its time
        or of its tokens takes all of its scenario's answers out of every number, as an outlier
        is mostly a scenario where the agent works longer, not a stray answer. A cut that would
        leave no scenario cuts nothing."""
        answers = [
            Answered(view.id, attempt.attempt, number, turn)
            for view in scenarios
            for attempt in view.attempts
            for number, turn in enumerate(attempt.turns)
        ]
        late = self.fence([a.turn.seconds for a in answers]) if cut else None
        large = self.fence([a.turn.tokens for a in answers]) if cut else None
        out = {
            a.scenario
            for a in answers
            if self.beyond(a.turn.seconds, late) or self.beyond(a.turn.tokens, large)
        }
        if out >= {view.id for view in scenarios}:
            out = set()
        kept = [a for a in answers if a.scenario not in out]
        return View(
            self.measure([a.turn.seconds for a in kept]),
            self.measure([a.turn.tokens for a in kept]),
            tuple(
                ScenarioNumbers(
                    self.spread(a.turn.seconds for a in kept if a.scenario == view.id),
                    self.spread(a.turn.tokens for a in kept if a.scenario == view.id),
                )
                for view in scenarios
            ),
            self.time(kept),
            *self.split(self.parts([a.turn for a in kept])),
            tuple(view.id for view in scenarios if view.id in out),
        )

    def fence(self, values: list[float | None]) -> float | None:
        """Tukey's far-out fence of the values on a log scale: the upper quartile of their logs
        and three interquartile ranges more. Time and tokens have a long right tail, which the log
        makes even, so the fence cuts only what is far out, and nothing when nothing is. None,
        nothing cut, under four values above 0 or when half of them or more are the same."""
        logs = [math.log(value) for value in values if value is not None and value > 0]
        if len(logs) < 4:
            return None
        low, _, high = quantiles(logs, n=4, method="inclusive")
        if high == low:
            return None
        return math.exp(high + FAR * (high - low))

    def beyond(self, value: float | None, fence: float | None) -> bool:
        return value is not None and fence is not None and value > fence

    def measure(self, values: list[float | None]) -> Measure:
        known = [value for value in values if value is not None]
        return Measure(self.spread(known), len(known))

    def time(self, answers: list[Answered]) -> tuple[Category, ...]:
        """Where the answers' calls spent their time: each call name's seconds per answer it ran
        in, calls that ran together each with their own, and the tokens its calls report; the most
        in total first, then by name. The calls' times and tokens are the agent's own: convy sets
        them against neither its own time of the answer nor the answer's tokens (decision 10)."""
        per, places, tokens = self.called(answers)
        whole = sum(sum(amounts) for amounts in per.values())
        return tuple(
            self.category(
                name,
                per[name],
                sorted(places[name], key=lambda p: -p.seconds),
                len(answers),
                whole,
                tokens.get(name),
            )
            for name in sorted(per, key=lambda name: (-sum(per[name]), name))
        )

    def called(
        self, answers: list[Answered]
    ) -> tuple[dict[str, list[float]], dict[str, list[CallPlace]], dict[str, float]]:
        """By call name: its calls' seconds summed per answer, its calls, and the tokens its calls
        report in all, for the names whose calls report some."""
        per: dict[str, list[float]] = {}
        places: dict[str, list[CallPlace]] = {}
        tokens: dict[str, float] = {}
        for a in answers:
            here: dict[str, float] = {}
            for step, made in enumerate(a.turn.steps):
                match made:
                    case CallView(name=name, seconds=seconds, tokens=used):
                        place = CallPlace(a.scenario, a.attempt, a.number, step, seconds, used)
                        places.setdefault(name, []).append(place)
                        here[name] = here.get(name, 0.0) + seconds
                        if used is not None:
                            tokens[name] = tokens.get(name, 0.0) + used
                    case ThoughtView():
                        pass
            for name, value in here.items():
                per.setdefault(name, []).append(value)
        return per, places, tokens

    def category(
        self,
        name: str,
        amounts: list[float],
        places: list[CallPlace],
        answers: int,
        whole: float,
        tokens: float | None,
    ) -> Category:
        """A category over the `answers` kept, whose categories add up to `whole` seconds."""
        spread = self.spread(amounts)
        assert spread is not None  # a category has an answer
        total = sum(amounts)
        return Category(
            name=name,
            answers=len(amounts),
            calls=len(places),
            total=total,
            spread=spread,
            places=tuple(places),
            average=total / answers,
            tokens=None if tokens is None else tokens / answers,
            share=total / whole if whole else 0.0,
        )

    def split(self, parts: Parts | None) -> tuple[Parts | None, Shares | None]:
        """The parts, and their shares: each one's of their sum, and the cache's of the input."""
        if parts is None:
            return None, None
        whole = (parts.cached or 0) + parts.input + parts.output + (parts.thinking or 0)
        share = (lambda part: part / whole) if whole else (lambda part: 0.0)
        cached = parts.cached
        return parts, Shares(
            cached=None if cached is None else share(cached),
            input=share(parts.input),
            output=share(parts.output),
            thinking=None if parts.thinking is None else share(parts.thinking),
            read=None
            if cached is None or not cached + parts.input
            else cached / (cached + parts.input),
        )

    def claim(self, claim: str | Graded, decisions: list[ClaimView]) -> ClaimSummary:
        """A claim over the attempts the judge decided, cut or not: its trusted decisions are
        tallied, the rest counted as cut. A graded claim also counts each grade."""
        trusted = [d for d in decisions if d.passed is not None and d.trusted]
        tally = Tally(sum(d.passed is True for d in trusted), len(trusted))
        cut = sum(d.passed is not None and not d.trusted for d in decisions)
        match claim:
            case str():
                text, grades, typical = claim, (), None
            case Graded(text=text, levels=levels):
                ranks = sorted(levels.index(d.grade) for d in trusted if d.grade in levels)
                grades = tuple((level, ranks.count(i)) for i, level in enumerate(levels))
                typical = levels[ranks[(len(ranks) - 1) // 2]] if ranks else None
        return ClaimSummary(text, tally.held, tally.judged, tally.result(), cut, grades, typical)

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
            thinking_tokens=self.total(turn.thinking_tokens for turn in turns),
            cache_read=self.total(turn.cache_read for turn in turns),
            cache_write=self.total(turn.cache_write for turn in turns),
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
        match claim.reason:
            case Reason(text=text):
                reason = text
            case NoReason():
                reason = ""
        return ClaimView(claim.passed, reason, sure, claim.trusted(trust), grade)

    def turn(self, turn: Turn) -> TurnView:
        match turn.answer.usage:
            case Usage(input=spent, output=produced) as usage:
                tokens: tuple[
                    int | None, int | None, int | None, int | None, int | None, int | None
                ] = (
                    spent,
                    produced,
                    spent + produced,
                    self.count(usage.thinking),
                    self.count(usage.cache_read),
                    self.count(usage.cache_write),
                )
            case NoUsage():
                tokens = (None, None, None, None, None, None)
        first, length = self.line(turn.answer.steps)
        thoughts = calls = 0
        for step in turn.answer.steps:
            match step:
                case Thought():
                    thoughts += 1
                case Call():
                    calls += 1
        steps = tuple(self.step(step, first, length) for step in turn.answer.steps)
        return TurnView(
            turn.message.text,
            turn.answer.text,
            turn.seconds,
            *tokens,
            steps,
            thoughts,
            calls,
            length,
        )

    def count(self, count: int | NotReported) -> int | None:
        """A part of an answer's tokens; None when the agent did not report it."""
        match count:
            case int():
                return count
            case NotReported():
                return None

    def line(self, steps: tuple[Thought | Call, ...]) -> tuple[float, float]:
        """Where an answer's calls start and how long they last, from the earliest start to the
        latest end, in float seconds by the agent's clock. `timestamp()` of an aware time does not
        overflow, and no `datetime` is made from the agent's numbers."""
        starts: list[float] = []
        ends: list[float] = []
        for step in steps:
            match step:
                case Call(started=started, seconds=seconds):
                    start = started.timestamp()
                    starts.append(start)
                    ends.append(start + seconds)
                case Thought():
                    pass
        first = min(starts, default=0.0)
        return first, max(ends, default=first) - first

    def step(self, step: Thought | Call, first: float, length: float) -> ThoughtView | CallView:
        """A step for the page; a call's bar as shares of the line, 0 on a line of no length."""
        match step:
            case Thought(text=text):
                return ThoughtView(text)
            case Call():
                offset = step.started.timestamp() - first
                return CallView(
                    name=step.name,
                    seconds=step.seconds,
                    left=offset / length if length else 0.0,
                    width=step.seconds / length if length else 0.0,
                    start=offset,
                    tokens=self.tokens(step.usage),
                    sent=self.reported(step.sent),
                    received=self.reported(step.received),
                )

    def tokens(self, usage: Usage | NoUsage) -> int | None:
        """Input and output tokens together; None when the agent did not report them."""
        match usage:
            case Usage(input=spent, output=produced):
                return spent + produced
            case NoUsage():
                return None

    def reported(self, text: Reported | NotReported) -> str | None:
        match text:
            case Reported(text=said):
                return said
            case NotReported():
                return None

    def total(self, counts: Iterable[int | None]) -> int | None:
        known = [count for count in counts if count is not None]
        return sum(known) if known else None

    def share(self, turns: Iterable[TurnView]) -> float | None:
        """The share of input read from the cache, over the turns that report it, so turns that
        do not report it do not pull it down; None when none does, or their input is 0."""
        read = spent = 0
        for turn in turns:
            if turn.cache_read is not None and turn.input is not None:
                read += turn.cache_read
                spent += turn.input
        return read / spent if spent else None

    def spread(self, values: Iterable[float | None]) -> Spread | None:
        """Every statistic of the values given, as floats; None when none is given. Percentiles
        are linear between the sorted values, numpy's default; one value is every statistic."""
        known = sorted(float(value) for value in values if value is not None)
        match known:
            case []:
                return None
            case [one]:
                return Spread(1, one, one, one, one, one)
            case _:
                cuts = quantiles(known, n=100, method="inclusive")
                return Spread(len(known), known[0], cuts[49], cuts[89], known[-1], mean(known))


class Report(Struct, frozen=True):
    """A run's page, `<agent>/<id>/report.html`. Every number and decision on it is made here;
    the page only draws."""

    run: Run

    def page(self) -> RunPage:
        summary = Summary(self.run)
        views = summary.scenarios().values()
        scenarios = sorted(views, key=lambda s: (ORDER[s.result], s.id))
        return RunPage(
            summary.head(),
            summary.metrics(views),
            tuple(scenarios),
            summary.results(scenarios),
            summary.views(scenarios),
        )

    def html(self) -> str:
        return Template("run.html").html(self.page())


class Setups(Struct, frozen=True):
    """Two runs' setups, before and after."""

    was: RunSpec
    now: RunSpec

    def differences(self, *more: tuple[str, str, str]) -> tuple[str, ...]:
        """What differs, as `judge: a → b`: the models and the convy that played them, a run that
        does not say which convy shown as `unknown`; then whatever else of `more` differs."""
        pairs = (
            ("user", self.was.user, self.now.user),
            ("judge", self.was.judge, self.now.judge),
            ("convy", self.was.convy or "unknown", self.now.convy or "unknown"),
            *more,
        )
        return tuple(f"{name}: {a} → {b}" for name, a, b in pairs if a != b)


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
        compared = [row for row in rows if row.group != "apart"]
        old, new = was.metrics(before.values()), now.metrics(after.values())
        return ComparePage(
            before=was.head(),
            after=now.head(),
            was=old,
            now=new,
            deltas=self.deltas(old, new, self.evidence(before, after, unchanged).shows()),
            differences=self.differences(),
            rows=tuple(rows),
            by_seconds=self.ranked((r.id, r.seconds) for r in compared),
            by_tokens=self.ranked((r.id, r.tokens) for r in compared),
            turns=self.pairs(was.turns(before.values()), now.turns(after.values())),
            by_parts=PerStat(
                *(
                    Ranking(
                        tuple(
                            (r.id, tokens)
                            for r in compared
                            if r.before is not None
                            and r.before.parted(stat) is not None
                            and r.after is not None
                            and (tokens := r.after.parted(stat)) is not None
                        )
                    ).ids()
                    for stat in STATS
                )
            ),
        )

    def pairs(
        self, before: tuple[TurnStats, ...], after: tuple[TurnStats, ...]
    ) -> tuple[TurnPair, ...]:
        """Each turn number either run has tokens at, with both runs' answers at it."""
        was, now = {t.turn: t for t in before}, {t.turn: t for t in after}
        return tuple(TurnPair(turn, was.get(turn), now.get(turn)) for turn in sorted({*was, *now}))

    def ranked(self, changes: Iterable[tuple[str, PerStat[Delta]]]) -> PerStat[tuple[str, ...]]:
        """The ids with a change of each statistic, the largest rise first, then by id."""
        pairs = tuple(changes)
        return PerStat(
            *(
                Ranking(
                    tuple(
                        (id, change.of(stat).value)
                        for id, change in pairs
                        if change.of(stat).value is not None
                    )
                ).ids()
                for stat in STATS
            )
        )

    def html(self) -> str:
        return Template("compare.html").html(self.page())

    def differences(self) -> tuple[str, ...]:
        """What differs between the runs besides the agent, as `judge: a → b`: the models, the
        convy that made them, and the agent's limits, since its load can change its answer time; a
        run that does not say which convy made it shows `unknown`."""
        was, now = self.before.spec.limits, self.after.spec.limits
        return Setups(self.before.spec, self.after.spec).differences(
            ("agent limit", f"{was.agent}", f"{now.agent}"),
            ("agent limit per minute", f"{was.agent_per_minute:g}", f"{now.agent_per_minute:g}"),
        )

    def unchanged(self) -> set[str]:
        """The scenarios both runs have, not edited between them."""
        before = {scenario.id: scenario for scenario in self.before.spec.scenarios}
        return {s.id for s in self.after.spec.scenarios if before.get(s.id) == s}

    def row(
        self, id: str, was: ScenarioView | None, now: ScenarioView | None, unchanged: set[str]
    ) -> CompareRow:
        if was is None or now is None:
            why = "only in the after run" if was is None else "only in the before run"
            return self.apart(id, why, was, now)
        if id not in unchanged:
            return self.apart(id, "edited between the runs", was, now)
        if was.rate is None or now.rate is None:
            return self.apart(id, "no verdict in one of the runs", was, now)
        group: Group = (
            "worse" if now.rate < was.rate else "better" if now.rate > was.rate else "same"
        )
        return CompareRow(
            id,
            group,
            "",
            was,
            now,
            self.claims(was, now),
            Delta(now.held - was.held, TONES[group]),
            self.changes(was.seconds, now.seconds),
            self.changes(was.tokens, now.tokens),
        )

    def apart(
        self, id: str, why: str, was: ScenarioView | None, now: ScenarioView | None
    ) -> CompareRow:
        """A scenario not compared: why, and no change of any number."""
        return CompareRow(id, "apart", why, was, now, (), NO_CHANGE, NO_CHANGES, NO_CHANGES)

    def claims(self, was: ScenarioView, now: ScenarioView) -> tuple[ClaimChange, ...]:
        changes = []
        for old, new in zip(was.claims, now.claims, strict=True):
            before = Tally(old.held, old.judged).rate()
            after = Tally(new.held, new.judged).rate()
            moved = self.moved(old, new)
            change = moved
            if before is not None and after is not None and before != after:
                change = "better" if after > before else "worse"
            changes.append(
                ClaimChange(
                    new.text, old.result, new.result, change, old.typical, new.typical, moved
                )
            )
        return tuple(changes)

    def moved(self, old: ClaimSummary, new: ClaimSummary) -> Change:
        """Where a claim's typical grade went. Its grades are the same in both runs: a scenario
        edited between them is not compared."""
        if not old.typical or not new.typical or old.typical == new.typical:
            return "unchanged"
        levels = [grade for grade, _ in new.grades]
        return "better" if levels.index(new.typical) > levels.index(old.typical) else "worse"

    def deltas(
        self, was: Metrics, now: Metrics, shown: Literal["better", "worse"] | None
    ) -> Deltas:
        if was.rate is None or now.rate is None:
            rate = NO_CHANGE
        else:
            points = round((now.rate - was.rate) * 100, 6)
            agrees = shown == ("better" if points > 0 else "worse")
            rate = Delta(points, self.tone(points, more_is_better=True, noisy=not agrees))
        return Deltas(
            rate=rate,
            stable=self.delta(was.stable, now.stable, more_is_better=True),
            seconds=self.units(was.seconds, now.seconds),
            tokens=self.units(was.tokens, now.tokens),
            cached=self.points(was.cached, now.cached),
            errors=self.delta(was.errors, now.errors, more_is_better=False),
        )

    def at(self, spread: Spread | None, stat: Stat) -> float | None:
        """A statistic of a spread; None without one."""
        return None if spread is None else spread.of(stat)

    def delta(self, was: float | None, now: float | None, more_is_better: bool) -> Delta:
        if was is None or now is None:
            return NO_CHANGE
        return Delta(now - was, self.tone(now - was, more_is_better=more_is_better, noisy=False))

    def points(self, was: float | None, now: float | None) -> Delta:
        """The change of a share in percentage points; a rise is better."""
        if was is None or now is None:
            return NO_CHANGE
        change = round((now - was) * 100, 6)
        shown = math.floor(now * 100 + 0.5) - math.floor(was * 100 + 0.5)  # as pct() in base.js
        return Delta(change, self.tone(shown, more_is_better=True, noisy=False))

    def units(self, was: Spread | None, now: Spread | None) -> PerStat[Delta]:
        """A tile's change of each statistic in its own unit. Max's is noise, as one answer moves
        it, unless it did not change."""
        p50, p90, top, average = (self.unit(self.at(was, s), self.at(now, s)) for s in STATS)
        return PerStat(p50, p90, Delta(top.value, "noise") if top.value else top, average)

    def unit(self, was: float | None, now: float | None) -> Delta:
        """A tile's change of a statistic in its own unit, toned as the scenarios' rows are; a
        rise from 0 is worse."""
        if was is None or now is None:
            return NO_CHANGE
        relative = self.relative(was, now)
        return Delta(now - was, "bad" if relative.value is None else relative.tone)

    def changes(self, was: Spread | None, now: Spread | None) -> PerStat[Delta]:
        """A row's change of each statistic, a percent of the old one."""
        return PerStat(*(self.relative(self.at(was, s), self.at(now, s)) for s in STATS))

    def relative(self, was: float | None, now: float | None) -> Delta:
        """The change of a statistic as a percent of the old one; none when either is missing, or
        the old one is 0 and the new one is not."""
        if was is None or now is None or (was == 0 and now != 0):
            return NO_CHANGE
        if was == now == 0:
            return Delta(0.0, "same")
        change = round((now - was) / was * 100, 6)
        return Delta(change, self.slight(change))

    def slight(self, percent: float) -> Tone:
        """A rise of time or tokens is worse; under 5% as the page rounds it, the same, so a
        change shown as 5% is never grey."""
        if math.floor(abs(percent) + 0.5) < SLIGHT:
            return "same"
        return "bad" if percent > 0 else "good"

    def tone(self, change: float, more_is_better: bool, noisy: bool) -> Tone:
        if change == 0:
            return "same"
        if noisy:
            return "noise"
        return "good" if (change > 0) == more_is_better else "bad"

    def evidence(
        self, before: dict[str, ScenarioView], after: dict[str, ScenarioView], unchanged: set[str]
    ) -> Evidence:
        """The tallies of the scenarios both runs played unchanged and judged."""
        return Evidence(
            tuple(
                (Tally(before[id].held, before[id].judged), Tally(after[id].held, after[id].judged))
                for id in sorted(unchanged)  # in one order, so the float sums never differ
                if before[id].judged and after[id].judged
            )
        )


class Index(Struct, frozen=True):
    """`index.html`: every run by agent, newest first, with what it was measured with and a link
    to its report."""

    runs: Iterable[Run]

    def page(self) -> IndexPage:
        played = sorted(self.runs, key=lambda run: run.spec.started, reverse=True)  # instants
        groups: dict[str, list[tuple[int, Run]]] = {}
        for order, run in enumerate(played):
            groups.setdefault(run.spec.agent, []).append((order, run))
        agents = []
        for agent in sorted(groups):
            runs = groups[agent]
            older: list[Run | None] = [run for _, run in runs[1:]]
            older.append(None)
            rows = tuple(
                self.row(order, run, previous)
                for (order, run), previous in zip(runs, older, strict=True)
            )
            agents.append(AgentRuns(agent, rows))
        return IndexPage(tuple(agents))

    def row(self, order: int, run: Run, previous: Run | None) -> IndexRow:
        summary = Summary(run)
        metrics = summary.metrics(summary.scenarios().values())
        return IndexRow(
            run=summary.head(),
            rate=metrics.rate,
            passed=metrics.passed,
            judged=metrics.judged,
            cut=metrics.cut,
            errors=metrics.errors,
            result=Tally(metrics.passed, metrics.judged).result(),
            changes=() if previous is None else self.changes(previous.spec, run.spec),
            order=order,
            report=f"{run.path.as_posix()}/report.html",
        )

    def changes(self, was: RunSpec, now: RunSpec) -> tuple[str, ...]:
        """What a run is measured with that differs from the agent's previous run, as
        `judge: a → b`, and the scenarios as `scenarios: +1 -2`, with a minus sign. Neither the
        agent's version (comparing versions is the point) nor the number of attempts counts; nor
        a scenario edited under the same id, which the comparison tells apart."""
        changes = list(Setups(was, now).differences(("trust", f"{was.trust:g}", f"{now.trust:g}")))
        before, ids = {s.id for s in was.scenarios}, {s.id for s in now.scenarios}
        moved = " ".join(
            f"{sign}{len(found)}"
            for sign, found in (("+", ids - before), ("\N{MINUS SIGN}", before - ids))
            if found
        )
        if moved:
            changes.append(f"scenarios: {moved}")
        return tuple(changes)

    def html(self) -> str:
        return Template("index.html").html(self.page())
