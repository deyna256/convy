"""The report: runs read back, summed up, and rendered as static HTML pages."""

import math
import re
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from importlib.resources import files
from math import comb
from pathlib import Path
from statistics import mean, quantiles
from typing import Literal
from urllib.parse import quote

import msgspec
from msgspec import Struct

from convy.agent import Call, NotReported, NoUsage, Reported, Thought, Usage
from convy.bench import Finished, Interrupted, Pair, RunFile, Running, RunSpec, Status
from convy.dialog import (
    Claim,
    Confidence,
    Failed,
    NoConfidence,
    NoReason,
    NoVerdict,
    Reason,
    Turn,
    Verdict,
)
from convy.scenario import Outcome, Requirement, Scenario, Stop

UNREADABLE = (msgspec.DecodeError, OSError)  # ValidationError is a DecodeError


class RunFormat(Struct, frozen=True):
    """Check the format before decoding a specification with a different schema."""

    format: int

    def __post_init__(self) -> None:
        if self.format != 9:
            raise ValueError(f"unsupported run format {self.format}; expected 9; start a new run")


class Run(Struct, frozen=True):
    """A run's folder read back: where it is under the results directory, its specification and
    status, the outcomes it could read, how many lines it could not, and the format it was written
    in."""

    path: Path
    spec: RunSpec
    status: Status
    outcomes: tuple[Outcome, ...]
    unreadable: int = 0
    format: Literal[9] = 9

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
            for folder in self.folders():
                if wanted in (folder.name, folder.name.rpartition("_")[2]):
                    try:
                        self.read(folder)
                    except UNREADABLE as error:
                        raise ValueError(f"{folder}: {error}") from error
            raise ValueError(f"no run {wanted!r} in {self.directory}")
        if len(found) > 1:
            names = ", ".join(run.path.as_posix() for run in found)
            raise ValueError(f"{wanted!r} names several runs: {names}; give the whole id")
        return found[0]

    def folders(self) -> list[Path]:
        return sorted(path.parent for path in self.directory.glob("*/*/run.json"))

    def read(self, folder: Path) -> Run:
        raw = (folder / "run.json").read_bytes()
        msgspec.json.decode(raw, type=RunFormat)
        file = msgspec.json.decode(raw, type=RunFile)
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
            file.format,
        )


# The pages' data. It is JSON for the browser, so a number nobody reported is None (null).

type Result = Literal["failing", "flaky", "passing", "none"]
ORDER: dict[Result, int] = {"failing": 0, "flaky": 1, "none": 2, "passing": 3}
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


class Spread(Struct, frozen=True):
    """How numbers spread: how many, the least, the 50th and 90th percentiles, the most and the
    mean."""

    n: int
    min: float
    p50: float
    p90: float
    max: float
    mean: float


class ClaimView(Struct, frozen=True):
    """The judge's decision on one claim in one attempt."""

    passed: bool | None  # None: the judge was not asked, or gave no verdict
    reason: str
    held: bool | None  # effective decision after applying trust
    required: bool
    confidence: float | None = None  # None: the judge did not say
    trusted: bool = True  # False: less sure than the run's trust


class ThoughtView(Struct, frozen=True, tag="thought"):
    text: str


class CallView(Struct, frozen=True, tag="call", kw_only=True):
    name: str
    kind: Literal["model", "tool"]
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
    tool_calls: int | None  # None: the answer's trace is missing or partial


class Completion(Struct, frozen=True):
    """A valid verdict's effective claim completion and reasons the attempt failed."""

    held: int
    total: int
    fraction: float
    failures: tuple[str, ...]


class AttemptView(Struct, frozen=True):
    attempt: int
    passed: bool | None  # None: no verdict, left out of pass rates
    completion: Completion | None  # None: no measured claim completion
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
    tool_calls: int | None  # None: no answers, or any answer's trace is incomplete
    turns: tuple[TurnView, ...]


class ClaimSummary(Struct, frozen=True):
    """A claim over a scenario's attempts that have a verdict."""

    text: str
    held: int
    judged: int
    result: Result
    required: bool


class Parts(Struct, frozen=True):
    """Mean tokens per answer by part, over the answers that report tokens: the
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
    attempts: tuple[AttemptView, ...]

    def order(self) -> tuple[int, str]:
        return ORDER[self.result], self.id


class Metrics(Struct, frozen=True):
    """The tiles of a run: the numbers behind them."""

    passed: int  # judged attempts that passed
    judged: int
    open: int  # attempts without a verdict: convy's models failed, or the agent stayed busy
    rate: float | None
    stable: int  # scenarios whose k attempts all passed
    flaky: int  # scenarios with passed and failed attempts
    cached: float | None  # share of input read from the cache, over the turns that report it
    agent_errors: int
    busy: int  # attempts whose agent's service stayed busy
    model_errors: int
    errors: int


class CallPlace(Struct, frozen=True):
    """Where one call was made: its scenario, attempt, turn and step, the last two from 0."""

    scenario: str
    attempt: int
    turn: int
    step: int
    seconds: float
    tokens: int | None


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


class ResourceStats(Struct, frozen=True):
    seconds: Spread | None  # per answer kept
    tokens: Spread | None
    attempt_seconds: Spread | None  # sum of recorded answer times per attempt with answers
    attempt_tokens: Spread | None  # per attempt with every answer's usage reported
    attempts: int  # recorded attempts kept, including those without measurements
    tool_calls: Spread | None  # per attempt whose answers all report complete traces


class View(Struct, frozen=True):
    """The run's time and token numbers with or without outliers: every tile, chart and table of
    them on the run's page."""

    numbers: ResourceStats
    scenarios: tuple[ResourceStats, ...]  # in the page's order of the scenarios
    time: tuple[Category, ...]  # the most in total first, then by name
    parts: Parts | None  # the tokens per answer by part, over the answers kept that report them
    shares: Shares | None
    out: tuple[str, ...] = ()  # the scenarios cut, in the page's order: every number leaves them


class Views(Struct, frozen=True):
    """The run's numbers with every scenario, and with the scenarios of outliers cut."""

    all: View
    cut: View


class ResultBucket(Struct, frozen=True):
    """The scenarios at one pass rate."""

    rate: float | None  # None: no verdict
    result: Result
    count: int
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
    claim_threshold: float
    confident: bool  # some decision of the run says how sure the judge was


class RunPage(Struct, frozen=True):
    run: RunHead
    metrics: Metrics
    scenarios: tuple[ScenarioView, ...]  # failing, flaky, no verdict, passing; each by id
    results: tuple[ResultBucket, ...]  # by pass rate from 0, no verdict last
    views: Views


class ScenarioCell(Struct, frozen=True):
    """One run's recorded results for a numbered revision of a scenario."""

    id: str
    revision: int
    recorded: int
    passed: int
    judged: int


class CallMetrics(Struct, frozen=True):
    """One named call's whole-run measurements, without individual call locations."""

    name: str
    answers: int
    calls: int
    total: float
    spread: Spread
    average: float
    tokens: float | None
    share: float
    token_calls: int

    @classmethod
    def from_category(cls, category: Category) -> "CallMetrics":
        return cls(
            name=category.name,
            answers=category.answers,
            calls=category.calls,
            total=category.total,
            spread=category.spread,
            average=category.average,
            tokens=category.tokens,
            share=category.share,
            token_calls=sum(p.tokens is not None for p in category.places),
        )


class IndexRow(Struct, frozen=True):
    run: RunHead
    report: str
    passed: int
    judged: int
    rate: float | None
    open: int
    stable: int
    flaky: int
    agent_errors: int
    busy: int
    model_errors: int
    errors: int
    results: tuple[ResultBucket, ...]
    numbers: ResourceStats
    cached: float | None
    cache_answers: int
    thinking_answers: int
    traced_answers: int
    parts: Parts | None
    shares: Shares | None
    time: tuple[CallMetrics, ...]
    scenarios: tuple[ScenarioCell, ...]
    setup: int  # position in the page's distinct evaluation setups
    quality_note: str  # why a whole-run difference is unavailable, empty when comparable


class IndexPage(Struct, frozen=True):
    rows: tuple[IndexRow, ...]  # newest first
    setups: tuple[dict[str, str | float | int], ...]


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
            claim_threshold=spec.claim_threshold,
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
        k = self.run.spec.k
        agent_errors = sum(a.stop == "agent_failure" for a in attempts)
        busy = sum(a.stop == "agent_busy" for a in attempts)
        model_errors = sum(a.stop == "model_failure" for a in attempts)
        return Metrics(
            passed=sum(judged),
            judged=len(judged),
            open=sum(a.passed is None for a in attempts),
            rate=Tally(sum(judged), len(judged)).rate(),
            stable=sum(
                len(v.attempts) == k and all(a.passed is True for a in v.attempts) for v in views
            ),
            flaky=sum(v.result == "flaky" for v in views),
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
            attempts=attempts,
        )

    def parts(self, turns: Iterable[TurnView]) -> Parts | None:
        """The mean tokens per answer by part, from the sums over those that
        report tokens; cache reads and thinking over the answers that report them."""
        counted = [a for a in turns if a.tokens is not None]
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

    def results(self, scenarios: Iterable[ScenarioView]) -> tuple[ResultBucket, ...]:
        """The scenarios by pass rate, from 0; those without a verdict last."""
        counts = Counter((view.rate, view.result) for view in scenarios)
        total = counts.total()
        return tuple(
            ResultBucket(rate, result, counts[rate, result], counts[rate, result] / total)
            for rate, result in sorted(counts, key=lambda key: (key[0] is None, key[0] or 0))
        )

    def views(self, scenarios: Sequence[ScenarioView]) -> Views:
        return Views(self.view(scenarios, cut=False), self.view(scenarios, cut=True))

    def answers(self, scenarios: Iterable[ScenarioView]) -> list[Answered]:
        return [
            Answered(view.id, attempt.attempt, number, turn)
            for view in scenarios
            for attempt in view.attempts
            for number, turn in enumerate(attempt.turns)
        ]

    def view(self, scenarios: Sequence[ScenarioView], cut: bool) -> View:
        """The time and tokens of the answers of `scenarios`, with the outliers' scenarios left
        out when `cut` says so. The unit is the scenario: one answer past the fence of its time
        or of its tokens takes all of its scenario's answers out of every number, as an outlier
        is mostly a scenario where the agent works longer, not a stray answer. A cut that would
        leave no scenario cuts nothing."""
        answers = self.answers(scenarios)
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
        attempts = [a for view in scenarios if view.id not in out for a in view.attempts]
        return View(
            self.numbers(attempts),
            tuple(self.numbers(view.attempts if view.id not in out else ()) for view in scenarios),
            self.time(kept),
            *self.split(self.parts(a.turn for a in kept)),
            tuple(view.id for view in scenarios if view.id in out),
        )

    def numbers(self, attempts: Sequence[AttemptView]) -> ResourceStats:
        """Answer and task distributions over the same recorded attempts."""
        turns = [turn for attempt in attempts for turn in attempt.turns]
        return ResourceStats(
            self.spread(t.seconds for t in turns),
            self.spread(t.tokens for t in turns),
            self.spread(a.seconds for a in attempts if a.turns),
            self.spread(a.tokens for a in attempts),
            len(attempts),
            self.spread(a.tool_calls for a in attempts),
        )

    def fence(self, values: list[float | None]) -> float | None:
        """Tukey's far-out fence of the values on a log scale: the upper quartile of their logs
        and three interquartile ranges more. Time and tokens have a long right tail, which the log
        makes even, so the fence cuts only what is far out, and nothing when nothing is. None,
        nothing cut, under four values above 0 or when the middle half of them are the same
        (equal quartiles)."""
        logs = [math.log(value) for value in values if value is not None and value > 0]
        if len(logs) < 4:
            return None
        low, _, high = quantiles(logs, n=4, method="inclusive")
        if high == low:
            return None
        return math.exp(high + FAR * (high - low))

    def beyond(self, value: float | None, fence: float | None) -> bool:
        return value is not None and fence is not None and value > fence

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

    def claim(self, claim: Requirement, decisions: list[ClaimView]) -> ClaimSummary:
        """Count every effective decision, including confidence failures."""
        judged = [d.held for d in decisions if d.held is not None]
        tally = Tally(sum(judged), len(judged))
        return ClaimSummary(claim.text, tally.held, tally.judged, tally.result(), claim.required)

    def attempt(self, scenario: Scenario, outcome: Outcome) -> AttemptView:
        turns = tuple(self.turn(turn) for turn in outcome.transcript.turns)
        spec = self.run.spec
        completion = None
        match outcome.verdict:
            case Verdict(claims=decided) as verdict:
                score = scenario.score(verdict, spec.trust, spec.claim_threshold)
                failures = []
                if score.required_failed:
                    numbers = ", ".join(str(i) for i in score.required_failed)
                    failures.append(f"Required claims failed: {numbers}.")
                if score.fraction < score.threshold:
                    failures.append(
                        f"Claim completion is below the {score.threshold * 100:.6g}% threshold."
                    )
                completion = Completion(score.held, score.total, score.fraction, tuple(failures))
                judged: tuple[bool | None, str] = (score.passed, "")
                claims = tuple(
                    self.decision(claim, requirement, spec.trust)
                    for claim, requirement in zip(decided, scenario.claims, strict=True)
                )
            case Failed(reason=reason):
                judged = (False, reason)
                claims = tuple(ClaimView(None, "", None, c.required) for c in scenario.claims)
            case NoVerdict(error=error):
                judged = (None, error)
                claims = tuple(ClaimView(None, "", None, c.required) for c in scenario.claims)
        passed, error = judged
        return AttemptView(
            attempt=outcome.attempt,
            passed=passed,
            completion=completion,
            stop=outcome.stop,
            error=error,
            claims=claims,
            seconds=sum(turn.seconds for turn in turns),
            slowest=max((turn.seconds for turn in turns), default=None),
            input=self.complete_total(turn.input for turn in turns),
            output=self.complete_total(turn.output for turn in turns),
            tokens=self.complete_total(turn.tokens for turn in turns),
            thinking_tokens=self.total(turn.thinking_tokens for turn in turns),
            cache_read=self.total(turn.cache_read for turn in turns),
            cache_write=self.total(turn.cache_write for turn in turns),
            tool_calls=self.complete_total(turn.tool_calls for turn in turns),
            turns=turns,
        )

    def decision(self, claim: Claim, requirement: Requirement, trust: float) -> ClaimView:
        match claim.confidence:
            case Confidence(value=value):
                sure: float | None = value
            case NoConfidence():
                sure = None
        match claim.reason:
            case Reason(text=text):
                reason = text
            case NoReason():
                reason = ""
        return ClaimView(
            claim.passed,
            reason,
            claim.holds(trust),
            requirement.required,
            sure,
            claim.trusted(trust),
        )

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
        thoughts = calls = tools = 0
        for step in turn.answer.steps:
            match step:
                case Thought():
                    thoughts += 1
                case Call(kind=kind):
                    calls += 1
                    tools += kind == "tool"
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
            tools if turn.answer.steps_complete else None,
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
                    kind=step.kind,
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

    def complete_total(self, counts: Iterable[int | None]) -> int | None:
        """A task total needs every answer's measurement; no answers is not a measured zero."""
        values = list(counts)
        if not values or any(value is None for value in values):
            return None
        return sum(value for value in values if value is not None)

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
        scenarios = sorted(views, key=ScenarioView.order)
        return RunPage(
            summary.head(),
            summary.metrics(views),
            tuple(scenarios),
            summary.results(scenarios),
            summary.views(scenarios),
        )

    def html(self) -> str:
        return Template("run.html").html(self.page())


class Comparison(Struct, frozen=True):
    """The pass-rate regression check on two runs."""

    before: Run
    after: Run

    def check(self) -> tuple[str, bool]:
        """The terminal summary and whether the CI check fails."""
        was, now = self.before.spec, self.after.spec
        if was.trust != now.trust or was.claim_threshold != now.claim_threshold:
            return "Quality not compared: different trust or claim threshold.", True
        if not isinstance(self.before.status, Finished) or not isinstance(
            self.after.status, Finished
        ):
            return "both runs must be finished to check for regression", True

        before, after = self.tallies(self.before), self.tallies(self.after)
        common = sorted(before.keys() & after.keys(), key=lambda scenario: scenario.id)
        pairs = {
            s.id: (before[s], after[s]) for s in common if before[s].judged and after[s].judged
        }
        if not pairs:
            return "no scenario can be compared", True

        # The displayed rates use all judged attempts. Only unchanged scenarios supply evidence.
        old = sum(t.held for t in before.values()) / sum(t.judged for t in before.values())
        new = sum(t.held for t in after.values()) / sum(t.judged for t in after.values())
        points = round((new - old) * 100, 6)
        verdict = "same"
        if points:
            direction = "better" if points > 0 else "worse"
            verdict = (
                direction
                if Evidence(tuple(pairs.values())).shows() == direction
                else "may be chance"
            )
        text = f"pass rate {old:.0%} → {new:.0%}: {verdict}"
        lower = [id for id, (a, b) in pairs.items() if b.held / b.judged < a.held / a.judged]
        if lower:
            text += f"\nlower pass rate: {', '.join(lower)}"
        return text, verdict == "worse"

    def tallies(self, run: Run) -> dict[Scenario, Tally]:
        """Judged attempts by the full scenario definition, so edits cannot supply evidence."""
        spec = run.spec
        scenarios = {s.id: s for s in spec.scenarios}
        judged: dict[Scenario, list[bool]] = {s: [] for s in spec.scenarios}
        for outcome in run.outcomes:
            scenario = scenarios[outcome.scenario]
            match outcome.verdict:
                case Verdict() as verdict:
                    judged[scenario].append(
                        scenario.score(verdict, spec.trust, spec.claim_threshold).passed
                    )
                case Failed():
                    judged[scenario].append(False)
        return {s: Tally(sum(passed), len(passed)) for s, passed in judged.items()}


class Index(Struct, frozen=True):
    """Every run on its original population. Revision and suite numbers belong to this page."""

    runs: Iterable[Run]

    def page(self) -> IndexPage:
        revisions: dict[Scenario, int] = {}
        suites: dict[frozenset[int], int] = {}
        setups: dict[tuple[tuple[str, str | float | int], ...], int] = {}
        rows = []
        for run in sorted(self.runs, key=lambda r: r.spec.started, reverse=True):
            spec = run.spec
            cells = {s.id: revisions.setdefault(s, len(revisions) + 1) for s in spec.scenarios}
            suite = suites.setdefault(frozenset(cells.values()), len(suites) + 1)
            settings = tuple(self.settings(spec, suite).items())
            missing = ", ".join(name for name, value in settings if value == "")
            rows.append(self.row(run, cells, setups.setdefault(settings, len(setups)), missing))
        return IndexPage(tuple(rows), tuple(dict(items) for items in setups))

    def settings(self, spec: RunSpec, suite: int) -> dict[str, str | float | int]:
        return {
            "Scenario suite": suite,
            "User": spec.user,
            "Judge": spec.judge,
            "Model fingerprint": spec.files.models,
            "Convy": spec.convy,
            "Trust": spec.trust,
            "Claim threshold": spec.claim_threshold,
            "Repetitions": spec.k,
            "Turn timeout (s)": spec.turn_timeout,
            "Agent concurrency": spec.limits.agent,
            "User concurrency": spec.limits.user,
            "Judge concurrency": spec.limits.judge,
            "Agent requests/min": spec.limits.agent_per_minute,
            "User requests/min": spec.limits.user_per_minute,
            "Judge requests/min": spec.limits.judge_per_minute,
        }

    def row(self, run: Run, revisions: dict[str, int], setup: int, missing: str) -> IndexRow:
        summary = Summary(run)
        scenarios = summary.scenarios().values()
        metrics = summary.metrics(scenarios)
        answers = summary.answers(sorted(scenarios, key=ScenarioView.order))
        turns = [a.turn for a in answers]
        parts, shares = summary.split(summary.parts(turns))
        spec = run.spec
        head = summary.head()
        complete = (
            head.status == "finished"
            and not run.unreadable
            and metrics.judged > 0
            and all(
                s.judged == len(s.attempts) == spec.k
                and all(a.attempt == i for i, a in enumerate(s.attempts, 1))
                for s in scenarios
            )
        )
        quality_note = f"{missing} not recorded" if missing else ""
        if not complete:
            quality_note = "Incomplete evaluation"
        return IndexRow(
            run=head,
            report=f"./{quote(run.path.as_posix())}/report.html",
            passed=metrics.passed,
            judged=metrics.judged,
            rate=metrics.rate,
            open=metrics.open,
            stable=metrics.stable,
            flaky=metrics.flaky,
            agent_errors=metrics.agent_errors,
            busy=metrics.busy,
            model_errors=metrics.model_errors,
            errors=metrics.errors,
            results=summary.results(scenarios),
            numbers=summary.numbers([a for s in scenarios for a in s.attempts]),
            cached=metrics.cached,
            cache_answers=sum(t.cache_read is not None for t in turns),
            thinking_answers=sum(t.thinking_tokens is not None for t in turns),
            traced_answers=sum(t.tool_calls is not None for t in turns),
            parts=parts,
            shares=shares,
            time=tuple(CallMetrics.from_category(c) for c in summary.time(answers)),
            scenarios=tuple(
                ScenarioCell(s.id, revisions[s.id], len(s.attempts), s.held, s.judged)
                for s in scenarios
            ),
            setup=setup,
            quality_note=quality_note,
        )

    def html(self) -> str:
        return Template("index.html").html(self.page())
