"""The report: runs read back, summed up, and rendered as static HTML pages."""

import math
import re
from collections.abc import Iterable, Iterator
from importlib.resources import files
from math import comb
from pathlib import Path
from statistics import mean
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

ORDER: dict[Result, int] = {"failing": 0, "flaky": 1, "none": 2, "passing": 3}
GROUPS: dict[Group, int] = {"worse": 0, "better": 1, "same": 2, "apart": 3}
SLIGHT = 5  # percent: a smaller change of a mean time or token count is drawn as the same
TONES: dict[Group, Tone] = {"worse": "bad", "better": "good", "same": "same", "apart": "none"}


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


class ScenarioView(Struct, frozen=True):
    id: str
    user: str
    max_turns: int
    held: int  # attempts that passed, of the judged
    judged: int
    rate: float | None
    result: Result
    claims: tuple[ClaimSummary, ...]
    seconds: float | None  # mean per answer
    slowest: float | None
    fastest: float | None  # the quickest answer
    input: float | None  # mean per attempt
    output: float | None
    tokens: float | None
    fewest: int | None  # the tokens of its cheapest attempt that reports them
    most: int | None  # and of its costliest
    thinking_tokens: float | None
    cache_read: float | None  # mean per attempt
    cache_write: float | None
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
    thinking_tokens: float | None
    cache_read: float | None  # mean per attempt
    cache_write: float | None
    cached: float | None  # share of input read from the cache, over the turns that report it
    agent_errors: int
    busy: int  # attempts whose agent's service stayed busy
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
    by_seconds: tuple[str, ...]  # the scenario ids, slowest answer first: the time panel's order
    by_tokens: tuple[str, ...]  # costliest attempt first: the tokens panel's order


class Delta(Struct, frozen=True):
    """A change from before to after and how to read it: in the metric's own unit, or, for a
    scenario's time and tokens on the comparison, a percent of the old value."""

    value: float | None
    tone: Tone


NO_CHANGE = Delta(None, "none")


class Deltas(Struct, frozen=True):
    rate: Delta  # percentage points
    stable: Delta
    seconds: Delta
    tokens: Delta
    cached: Delta  # percentage points
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
    held: Delta  # the change in passed attempts, in the tone of the row's group
    seconds: Delta  # the change of the mean time per answer, a percent
    tokens: Delta  # the change of the mean tokens per attempt, a percent


class ComparePage(Struct, frozen=True):
    before: RunHead
    after: RunHead
    was: Metrics
    now: Metrics
    deltas: Deltas
    differences: tuple[str, ...]  # the models and the convy that differ, as "judge: a → b"
    rows: tuple[CompareRow, ...]  # worse, better, same, not compared; each by id
    by_seconds: tuple[str, ...]  # compared scenarios with both times, the largest rise first
    by_tokens: tuple[str, ...]


class IndexRow(Struct, frozen=True):
    run: RunHead
    passed: int
    judged: int
    cut: int
    rate: float | None
    report: str  # the run's report, relative to the index


class IndexPage(Struct, frozen=True):
    runs: tuple[IndexRow, ...]  # newest first


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
            rate=Tally(sum(judged), len(judged)).rate(),
            stable=sum(
                len(v.attempts) == k and all(a.passed is True for a in v.attempts) for v in views
            ),
            seconds=self.average(turns),
            slowest=max(turns, default=None),
            input=self.average(a.input for a in attempts),
            output=self.average(a.output for a in attempts),
            tokens=self.average(a.tokens for a in attempts),
            thinking_tokens=self.average(a.thinking_tokens for a in attempts),
            cache_read=self.average(a.cache_read for a in attempts),
            cache_write=self.average(a.cache_write for a in attempts),
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
        spent = [a.tokens for a in attempts if a.tokens is not None]
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
            seconds=self.average(turns),
            slowest=max(turns, default=None),
            fastest=min(turns, default=None),
            input=self.average(a.input for a in attempts),
            output=self.average(a.output for a in attempts),
            tokens=self.average(a.tokens for a in attempts),
            fewest=min(spent, default=None),
            most=max(spent, default=None),
            thinking_tokens=self.average(a.thinking_tokens for a in attempts),
            cache_read=self.average(a.cache_read for a in attempts),
            cache_write=self.average(a.cache_write for a in attempts),
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
            turn.message.text, turn.answer.text, turn.seconds, *tokens, steps, thoughts, calls
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
        return RunPage(
            summary.head(),
            summary.metrics(views),
            tuple(scenarios),
            Ranking(tuple((s.id, s.slowest) for s in views)).ids(),
            Ranking(tuple((s.id, s.most) for s in views)).ids(),
        )

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
            by_seconds=Ranking(
                tuple((r.id, r.seconds.value) for r in compared if r.seconds.value is not None)
            ).ids(),
            by_tokens=Ranking(
                tuple((r.id, r.tokens.value) for r in compared if r.tokens.value is not None)
            ).ids(),
        )

    def html(self) -> str:
        return Template("compare.html").html(self.page())

    def differences(self) -> tuple[str, ...]:
        """What differs between the runs besides the agent, as `judge: a → b`: the models, the
        convy that made them, and the agent's limits, since its load can change its answer time; a
        run that does not say which convy made it shows `unknown`."""
        before, after = self.before.spec, self.after.spec
        was, now = before.limits, after.limits
        pairs = (
            ("user", before.user, after.user),
            ("judge", before.judge, after.judge),
            ("convy", before.convy or "unknown", after.convy or "unknown"),
            ("agent limit", f"{was.agent}", f"{now.agent}"),
            ("agent limit per minute", f"{was.agent_per_minute:g}", f"{now.agent_per_minute:g}"),
        )
        return tuple(f"{name}: {was} → {now}" for name, was, now in pairs if was != now)

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
            self.relative(was.seconds, now.seconds),
            self.relative(was.tokens, now.tokens),
        )

    def apart(
        self, id: str, why: str, was: ScenarioView | None, now: ScenarioView | None
    ) -> CompareRow:
        """A scenario not compared: why, and no change of any number."""
        return CompareRow(id, "apart", why, was, now, (), NO_CHANGE, NO_CHANGE, NO_CHANGE)

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
            rate = Delta(None, "none")
        else:
            points = round((now.rate - was.rate) * 100, 6)
            agrees = shown == ("better" if points > 0 else "worse")
            rate = Delta(points, self.tone(points, more_is_better=True, noisy=not agrees))
        return Deltas(
            rate=rate,
            stable=self.delta(was.stable, now.stable, more_is_better=True),
            seconds=self.mean(was.seconds, now.seconds),
            tokens=self.mean(was.tokens, now.tokens),
            cached=self.points(was.cached, now.cached),
            errors=self.delta(was.errors, now.errors, more_is_better=False),
        )

    def delta(self, was: float | None, now: float | None, more_is_better: bool) -> Delta:
        if was is None or now is None:
            return Delta(None, "none")
        return Delta(now - was, self.tone(now - was, more_is_better=more_is_better, noisy=False))

    def points(self, was: float | None, now: float | None) -> Delta:
        """The change of a share in percentage points; a rise is better."""
        if was is None or now is None:
            return Delta(None, "none")
        change = round((now - was) * 100, 6)
        shown = math.floor(now * 100 + 0.5) - math.floor(was * 100 + 0.5)  # as pct() in base.js
        return Delta(change, self.tone(shown, more_is_better=True, noisy=False))

    def mean(self, was: float | None, now: float | None) -> Delta:
        """A tile's change of a mean in its own unit, toned as the scenarios' rows are; a rise
        from 0 is worse."""
        if was is None or now is None:
            return NO_CHANGE
        relative = self.relative(was, now)
        return Delta(now - was, "bad" if relative.value is None else relative.tone)

    def relative(self, was: float | None, now: float | None) -> Delta:
        """The change of a mean as a percent of the old one; none when either is missing, or the
        old one is 0 and the new one is not."""
        if was is None or now is None or (was == 0 and now != 0):
            return NO_CHANGE
        change = round((now - was) / was * 100, 6) if was else 0.0
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
