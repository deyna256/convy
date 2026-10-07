"""The report: journals read back, summed up, and rendered as one static HTML page."""

from collections.abc import Iterable, Iterator
from importlib.resources import files
from pathlib import Path
from statistics import mean

import msgspec
from msgspec import Struct

from convy.agent import NoUsage, Usage
from convy.bench import RunHeader
from convy.dialog import Failed, NoVerdict, Turn, Verdict
from convy.scenario import Outcome, Stop

UNREADABLE = (msgspec.DecodeError, msgspec.ValidationError, ValueError, OSError)


class Run(Struct, frozen=True):
    """A journal read back: where it is under the runs directory, its header, the outcomes it
    could read, and how many lines it could not."""

    path: Path
    header: RunHeader
    outcomes: tuple[Outcome, ...]
    unreadable: int = 0

    def group(self) -> str:
        """Runs of the same agent and version form a group in the report."""
        return f"{self.header.agent} {self.header.version}".strip()

    def complete(self) -> bool:
        return len(self.outcomes) >= self.header.planned


class Runs(Struct, frozen=True):
    """Every journal under a directory. Iterating skips a journal whose header cannot be read and
    the outcome lines that cannot; `broken` lists the journals with either. Paths in both are
    relative to the directory."""

    directory: Path

    def __iter__(self) -> Iterator[Run]:
        for path in self.paths():
            try:
                yield self.read(path)
            except UNREADABLE:
                continue

    def broken(self) -> tuple[Path, ...]:
        found = []
        for path in self.paths():
            try:
                if self.read(path).unreadable:
                    found.append(path.relative_to(self.directory))
            except UNREADABLE:
                found.append(path.relative_to(self.directory))
        return tuple(found)

    def paths(self) -> list[Path]:
        return sorted(self.directory.rglob("*.jsonl"))

    def read(self, path: Path) -> Run:
        header, *lines = path.read_bytes().splitlines() or [b""]
        outcomes = []
        for line in lines:
            try:
                outcomes.append(msgspec.json.decode(line, type=Outcome))
            except UNREADABLE:  # a line cut short by a crash, say
                continue
        return Run(
            path.relative_to(self.directory),
            msgspec.json.decode(header, type=RunHeader),
            tuple(outcomes),
            len(lines) - len(outcomes),
        )


# The page's data. It is JSON for the browser, so a number nobody reported is None (null).


class TurnView(Struct, frozen=True):
    user: str
    agent: str
    seconds: float
    input: int | None
    output: int | None


class AttemptView(Struct, frozen=True):
    run: str
    complete: bool
    attempt: int
    claims: tuple[str, ...]
    stop: Stop
    passed: bool | None
    reason: str
    seconds: float
    input: int | None
    output: int | None
    turns: tuple[TurnView, ...]


class CellView(Struct, frozen=True):
    passed: int
    judged: int
    seconds: float | None
    input: float | None
    attempts: tuple[AttemptView, ...]


class Rate(Struct, frozen=True):
    mean: float
    min: float
    max: float


class GroupView(Struct, frozen=True):
    id: str
    agent: str
    version: str
    user: str  # the models of the latest run
    judge: str
    started: str  # when the latest run started, ISO 8601
    runs: int
    stopped: int
    passed: Rate | None
    input: float | None
    output: float | None
    seconds: float | None
    turn_mean: float | None
    turn_max: float | None
    agent_failures: int
    model_failures: int


class Page(Struct, frozen=True):
    groups: tuple[GroupView, ...]
    scenarios: tuple[str, ...]
    cells: dict[str, CellView]  # keyed by "<scenario>|<group>"


class Report(Struct, frozen=True):
    """The page `results/index.html`: a summary per group, a matrix of scenarios, every attempt."""

    runs: Iterable[Run]

    def html(self) -> str:
        data = msgspec.json.encode(self.page()).decode().replace("<", "\\u003c")
        template = files("convy").joinpath("report.html").read_text(encoding="utf-8")
        return template.replace("__DATA__", data)

    def page(self) -> Page:
        runs = list(self.runs)
        names = sorted({run.group() for run in runs})
        cells: dict[str, list[AttemptView]] = {}
        for run in runs:
            for outcome in run.outcomes:
                key = f"{outcome.scenario}|{run.group()}"
                cells.setdefault(key, []).append(self.attempt(run, outcome))
        views = {key: self.cell(attempts) for key, attempts in cells.items()}
        scenarios = {outcome.scenario for run in runs for outcome in run.outcomes}
        return Page(
            groups=tuple(
                self.group(name, [run for run in runs if run.group() == name]) for name in names
            ),
            scenarios=tuple(
                sorted(scenarios, key=lambda s: (not self.differs(s, names, views), s))
            ),
            cells=views,
        )

    def attempt(self, run: Run, outcome: Outcome) -> AttemptView:
        turns = tuple(self.turn(turn) for turn in outcome.transcript.turns)
        match outcome.verdict:
            case Verdict(claims=claims) as verdict:
                reason = "\n".join(claim.reason for claim in claims)
                judged: tuple[bool | None, str] = (verdict.passed, reason)
            case Failed(reason=reason):
                judged = (False, reason)
            case NoVerdict(error=error):
                judged = (None, error)
        passed, reason = judged
        return AttemptView(
            run=run.path.as_posix(),
            complete=run.complete(),
            attempt=outcome.attempt,
            claims=outcome.claims,
            stop=outcome.stop,
            passed=passed,
            reason=reason,
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

    def cell(self, attempts: list[AttemptView]) -> CellView:
        judged = [a for a in attempts if a.passed is not None]
        return CellView(
            passed=sum(a.passed is True for a in judged),
            judged=len(judged),
            seconds=self.average(a.seconds for a in attempts),
            input=self.average(a.input for a in attempts),
            attempts=tuple(attempts),
        )

    def group(self, name: str, runs: list[Run]) -> GroupView:
        complete = [[self.attempt(run, o) for o in run.outcomes] for run in runs if run.complete()]
        attempts = [attempt for run in complete for attempt in run]
        rates = [rate for run in complete if (rate := self.rate(run)) is not None]
        turn_seconds = [turn.seconds for attempt in attempts for turn in attempt.turns]
        latest = max((run.header for run in runs), key=lambda header: header.started)
        return GroupView(
            id=name,
            agent=latest.agent,
            version=latest.version,
            user=latest.user,
            judge=latest.judge,
            started=latest.started.isoformat(),
            runs=len(runs),
            stopped=len(runs) - len(complete),
            passed=Rate(mean(rates), min(rates), max(rates)) if rates else None,
            input=self.average(a.input for a in attempts),
            output=self.average(a.output for a in attempts),
            seconds=self.average(a.seconds for a in attempts),
            turn_mean=self.average(turn_seconds),
            turn_max=max(turn_seconds, default=None),
            agent_failures=sum(a.stop == "agent_failure" for a in attempts),
            model_failures=sum(a.stop == "model_failure" for a in attempts),
        )

    def rate(self, attempts: list[AttemptView]) -> float | None:
        """The share passed among a run's attempts that have a verdict."""
        judged = [a for a in attempts if a.passed is not None]
        return sum(a.passed is True for a in judged) / len(judged) if judged else None

    def differs(self, scenario: str, groups: list[str], cells: dict[str, CellView]) -> bool:
        """Whether groups pass the scenario at different rates; such scenarios come first."""
        rates = {
            c.passed / c.judged for g in groups if (c := cells.get(f"{scenario}|{g}")) and c.judged
        }
        return len(rates) > 1

    def total(self, counts: Iterable[int | None]) -> int | None:
        known = [count for count in counts if count is not None]
        return sum(known) if known else None

    def average(self, values: Iterable[float | None]) -> float | None:
        known = [value for value in values if value is not None]
        return mean(known) if known else None
