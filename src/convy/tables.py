"""A run as data: flat tables, one for each kind of object a run holds, for tools outside convy.
The tables compute nothing and drop nothing. A row may hold `None` for a value the agent or the
judge did not give, or that does not apply to it: rows are data for the outside, where `None` is a
missing value."""

import csv
import io
from collections.abc import Iterator
from datetime import datetime
from typing import Any, Literal

import msgspec
from msgspec import Struct

from convy.agent import Call, NotReported, NoUsage, Reported, Thought, Usage
from convy.bench import Finished, Interrupted, Running
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
from convy.report import Run
from convy.scenario import Outcome, Stop

type Tokens = tuple[int | None, int | None, int | None, int | None, int | None]


class RunRow(Struct, frozen=True, kw_only=True):
    run: str
    agent: str
    version: str
    user_model: str
    judge_model: str
    k: int
    turn_timeout: float
    trust: float
    convy: str
    started: datetime
    status: Literal["running", "finished", "interrupted"]
    ended: datetime | None
    agent_parallel: int
    user_parallel: int
    judge_parallel: int
    agent_per_minute: float
    user_per_minute: float
    judge_per_minute: float
    agent_file: str
    models_file: str
    format: int
    path: str
    unreadable: int


class ScenarioRow(Struct, frozen=True, kw_only=True):
    run: str
    scenario: str
    instructions: str
    max_turns: int


class ClaimRow(Struct, frozen=True, kw_only=True):
    run: str
    scenario: str
    claim: int
    text: str
    grades: tuple[str | int, ...] | None
    threshold: str | int | None


class AttemptRow(Struct, frozen=True, kw_only=True):
    run: str
    scenario: str
    attempt: int
    verdict: Literal["verdict", "failed", "no_verdict"]
    error: str | None
    stop: Stop


class DecisionRow(Struct, frozen=True, kw_only=True):
    run: str
    scenario: str
    attempt: int
    claim: int
    passed: bool
    reason: str | None
    confidence: float | None
    grade: str | None


class AnswerRow(Struct, frozen=True, kw_only=True):
    run: str
    scenario: str
    attempt: int
    turn: int
    message: str
    answer: str
    seconds: float
    input: int | None
    output: int | None
    thinking: int | None
    cache_read: int | None
    cache_write: int | None


class StepRow(Struct, frozen=True, kw_only=True):
    run: str
    scenario: str
    attempt: int
    turn: int
    step: int
    kind: Literal["thought", "call"]
    text: str | None
    name: str | None
    started: datetime | None
    seconds: float | None
    input: int | None
    output: int | None
    thinking: int | None
    cache_read: int | None
    cache_write: int | None
    sent: str | None
    received: str | None


class Table[R: Struct](Struct, frozen=True):
    """One table: its name, which is its file's name in an export, the type of its rows, so an
    empty table still knows its columns, and its rows."""

    name: str
    row: type[R]
    rows: tuple[R, ...]

    def records(self) -> list[dict[str, Any]]:
        """The rows as dicts, for pandas or polars, datetimes kept."""
        return list(msgspec.to_builtins(self.rows, builtin_types=(datetime,)))

    def csv(self) -> str:
        """The table for spreadsheets: a missing value is an empty cell and every other value is
        quoted, so readers that respect quotes keep "" apart from it; a value that is not text is
        written as in JSON Lines: a list, `true`, a number, a time. JSON Lines is the complete
        form."""
        out = io.StringIO()
        writer = csv.writer(out, quoting=csv.QUOTE_NOTNULL)
        writer.writerow(field.encode_name for field in msgspec.structs.fields(self.row))
        for record in msgspec.to_builtins(self.rows):
            writer.writerow(self.cell(value) for value in record.values())
        return out.getvalue()

    def jsonl(self) -> str:
        """The table's complete form: one JSON object a line."""
        return msgspec.json.Encoder().encode_lines(self.rows).decode()

    def cell(self, value: object) -> str | None:
        match value:
            case str() | None:
                return value
            case _:
                return msgspec.json.encode(value).decode()


class Tables(Struct, frozen=True):
    """Runs as seven tables, one for each kind of object a run holds. A tuple, not any iterable:
    each table walks the runs again."""

    played: tuple[Run, ...]

    def __iter__(self) -> Iterator[Table]:
        yield self.runs()
        yield self.scenarios()
        yield self.claims()
        yield self.attempts()
        yield self.decisions()
        yield self.answers()
        yield self.steps()

    def runs(self) -> Table[RunRow]:
        return Table("runs", RunRow, tuple(self.head(run) for run in self.ordered()))

    def scenarios(self) -> Table[ScenarioRow]:
        return Table(
            "scenarios",
            ScenarioRow,
            tuple(
                ScenarioRow(
                    run=run.spec.id,
                    scenario=s.id,
                    instructions=s.instructions,
                    max_turns=s.max_turns,
                )
                for run in self.ordered()
                for s in run.spec.scenarios
            ),
        )

    def claims(self) -> Table[ClaimRow]:
        return Table(
            "claims",
            ClaimRow,
            tuple(
                self.claim(run, scenario.id, number, claim)
                for run in self.ordered()
                for scenario in run.spec.scenarios
                for number, claim in enumerate(scenario.claims, 1)
            ),
        )

    def attempts(self) -> Table[AttemptRow]:
        return Table(
            "attempts",
            AttemptRow,
            tuple(
                self.attempt(run, outcome)
                for run in self.ordered()
                for outcome in self.outcomes(run)
            ),
        )

    def decisions(self) -> Table[DecisionRow]:
        return Table(
            "decisions",
            DecisionRow,
            tuple(
                self.decision(run, outcome, number, claim)
                for run in self.ordered()
                for outcome in self.outcomes(run)
                for number, claim in enumerate(self.decided(outcome), 1)
            ),
        )

    def answers(self) -> Table[AnswerRow]:
        return Table(
            "answers",
            AnswerRow,
            tuple(
                self.answer(run, outcome, number, turn)
                for run in self.ordered()
                for outcome in self.outcomes(run)
                for number, turn in enumerate(outcome.transcript.turns, 1)
            ),
        )

    def steps(self) -> Table[StepRow]:
        return Table(
            "steps",
            StepRow,
            tuple(
                self.step(run, outcome, turn, number, step)
                for run in self.ordered()
                for outcome in self.outcomes(run)
                for turn, said in enumerate(outcome.transcript.turns, 1)
                for number, step in enumerate(said.answer.steps, 1)
            ),
        )

    def ordered(self) -> list[Run]:
        return sorted(self.played, key=lambda run: (run.spec.started, run.spec.id))

    def outcomes(self, run: Run) -> list[Outcome]:
        """The run's attempts by the scenario's place in the spec, then number; `outcomes` is in
        the order the attempts ended. An attempt of a scenario the spec lacks, which only a run
        made in Python can hold, comes last."""
        place = {scenario.id: number for number, scenario in enumerate(run.spec.scenarios)}
        return sorted(
            run.outcomes,
            key=lambda outcome: (place.get(outcome.scenario, len(place)), outcome.attempt),
        )

    def head(self, run: Run) -> RunRow:
        spec, limits = run.spec, run.spec.limits
        match run.status:
            case Running():
                status, ended = "running", None
            case Finished(ended=at):
                status, ended = "finished", at
            case Interrupted(ended=at):
                status, ended = "interrupted", at
        return RunRow(
            run=spec.id,
            agent=spec.agent,
            version=spec.version,
            user_model=spec.user,
            judge_model=spec.judge,
            k=spec.k,
            turn_timeout=spec.turn_timeout,
            trust=spec.trust,
            convy=spec.convy,
            started=spec.started,
            status=status,
            ended=ended,
            agent_parallel=limits.agent,
            user_parallel=limits.user,
            judge_parallel=limits.judge,
            agent_per_minute=limits.agent_per_minute,
            user_per_minute=limits.user_per_minute,
            judge_per_minute=limits.judge_per_minute,
            agent_file=spec.files.agent,
            models_file=spec.files.models,
            format=run.format,
            path=run.path.as_posix(),
            unreadable=run.unreadable,
        )

    def claim(self, run: Run, scenario: str, number: int, claim: str | Graded) -> ClaimRow:
        match claim:
            case str():
                text, grades, threshold = claim, None, None
            case Graded(text=text, grades=grades, threshold=threshold):
                pass
        return ClaimRow(
            run=run.spec.id,
            scenario=scenario,
            claim=number,
            text=text,
            grades=grades,
            threshold=threshold,
        )

    def attempt(self, run: Run, outcome: Outcome) -> AttemptRow:
        match outcome.verdict:
            case Verdict():
                verdict, error = "verdict", None
            case Failed(reason=reason):
                verdict, error = "failed", reason
            case NoVerdict(error=failure):
                verdict, error = "no_verdict", failure
        return AttemptRow(
            run=run.spec.id,
            scenario=outcome.scenario,
            attempt=outcome.attempt,
            verdict=verdict,
            error=error,
            stop=outcome.stop,
        )

    def decided(self, outcome: Outcome) -> tuple[Claim, ...]:
        match outcome.verdict:
            case Verdict(claims=claims):
                return claims
            case Failed() | NoVerdict():
                return ()

    def decision(self, run: Run, outcome: Outcome, number: int, claim: Claim) -> DecisionRow:
        match claim.reason:
            case Reason(text=text):
                reason = text
            case NoReason():
                reason = None
        match claim.confidence:
            case Confidence(value=value):
                confidence = value
            case NoConfidence():
                confidence = None
        match claim.grade:
            case Grade(value=value):
                grade = value
            case NoGrade():
                grade = None
        return DecisionRow(
            run=run.spec.id,
            scenario=outcome.scenario,
            attempt=outcome.attempt,
            claim=number,
            passed=claim.passed,
            reason=reason,
            confidence=confidence,
            grade=grade,
        )

    def answer(self, run: Run, outcome: Outcome, number: int, turn: Turn) -> AnswerRow:
        input, output, thinking, cache_read, cache_write = self.tokens(turn.answer.usage)
        return AnswerRow(
            run=run.spec.id,
            scenario=outcome.scenario,
            attempt=outcome.attempt,
            turn=number,
            message=turn.message.text,
            answer=turn.answer.text,
            seconds=turn.seconds,
            input=input,
            output=output,
            thinking=thinking,
            cache_read=cache_read,
            cache_write=cache_write,
        )

    def step(
        self, run: Run, outcome: Outcome, turn: int, number: int, step: Thought | Call
    ) -> StepRow:
        match step:
            case Thought(text=said):
                kind, text, name, started, seconds = "thought", said, None, None, None
                usage, sent, received = NoUsage(), None, None
            case Call(name=name, started=started, seconds=seconds, usage=usage):
                kind, text = "call", None
                sent, received = self.text(step.sent), self.text(step.received)
        input, output, thinking, cache_read, cache_write = self.tokens(usage)
        return StepRow(
            run=run.spec.id,
            scenario=outcome.scenario,
            attempt=outcome.attempt,
            turn=turn,
            step=number,
            kind=kind,
            text=text,
            name=name,
            started=started,
            seconds=seconds,
            input=input,
            output=output,
            thinking=thinking,
            cache_read=cache_read,
            cache_write=cache_write,
            sent=sent,
            received=received,
        )

    def tokens(self, usage: Usage | NoUsage) -> Tokens:
        """input, output, thinking, cache_read, cache_write: None when not reported."""
        match usage:
            case Usage():
                return (
                    usage.input,
                    usage.output,
                    self.count(usage.thinking),
                    self.count(usage.cache_read),
                    self.count(usage.cache_write),
                )
            case NoUsage():
                return (None, None, None, None, None)

    def count(self, count: int | NotReported) -> int | None:
        match count:
            case int():
                return count
            case NotReported():
                return None

    def text(self, text: Reported | NotReported) -> str | None:
        match text:
            case Reported(text=said):
                return said
            case NotReported():
                return None
