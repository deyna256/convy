import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import msgspec
import pytest

from convy import (
    AnswerRow,
    AttemptRow,
    ClaimRow,
    DecisionRow,
    RunRow,
    ScenarioRow,
    StepRow,
    Table,
    Tables,
)
from convy.agent import Answer, Call, Message, Reported, Thought, Usage
from convy.bench import Files, Finished, Interrupted, Limits, Running, RunSpec
from convy.dialog import (
    Claim,
    Confidence,
    Failed,
    Grade,
    Graded,
    NoVerdict,
    Reason,
    Transcript,
    Turn,
    Verdict,
)
from convy.project import Project
from convy.report import Run
from convy.scenario import Outcome, Scenario

DAY = datetime(2026, 10, 6, tzinfo=UTC)
GRADED = Graded("solved", ("none", "partial", "full"), "partial")
REFUND = Scenario("refund", 4, "Ask for a refund.", ("asks for the order", GRADED))
HELLO = Scenario("hello", 2, "Say hi.", ("greets",))
SPEC = RunSpec(
    id="2026-10-06T00-00-00_ab12",
    agent="bot",
    version="2",
    user="user-model",
    judge="judge-model",
    k=2,
    turn_timeout=600,
    scenarios=(REFUND, HELLO),
    started=DAY,
    convy="0.6.0",
    files=Files(agent="aa", models="bb"),
    trust=0.5,
    limits=Limits(agent=2, user=3, judge=1, agent_per_minute=60, judge_per_minute=30),
)
CALL = Call(
    name="search",
    started=DAY,
    seconds=0.5,
    usage=Usage(10, 2, cache_read=4),
    sent=Reported("order 7"),
    received=Reported(""),
)
SILENT = Call(name="lookup", started=DAY, seconds=0.1)  # no tokens, no text: not reported
FULL = Answer(
    "Your order?", Usage(100, 20, 5, cache_read=60, cache_write=0), (Thought("ask"), CALL, SILENT)
)
VERDICT = Verdict(
    (
        Claim(True, Reason("asked"), Confidence(0.9)),
        Claim(False, grade=Grade("none")),
    )
)
TALK = Transcript(
    (Turn(Message("Refund,\nplease"), FULL, 1.5), Turn(Message("7"), Answer("Done"), 0.5))
)
OUTCOMES = (
    Outcome("hello", 1, Transcript(), NoVerdict("judge down"), "model_failure"),
    Outcome("refund", 2, Transcript(), Failed("agent down"), "agent_failure"),
    Outcome("refund", 1, TALK, VERDICT, "user_stop"),
)
RUN = Run(Path("bot/2026-10-06T00-00-00_ab12"), SPEC, Finished(DAY + timedelta(hours=1)), OUTCOMES)
LIVE = Run(
    Path("bot/2026-10-07T00-00-00_cd34"),
    msgspec.structs.replace(SPEC, id="2026-10-07T00-00-00_cd34", started=DAY + timedelta(days=1)),
    Running(),
    (),
    unreadable=1,
)
TABLES = Tables((LIVE, RUN))
RUN_ID = SPEC.id


def test_a_run_row_holds_every_value_of_its_spec_and_status():
    first, second = TABLES.runs().rows
    assert first == RunRow(
        run=RUN_ID,
        agent="bot",
        version="2",
        user_model="user-model",
        judge_model="judge-model",
        k=2,
        turn_timeout=600,
        trust=0.5,
        convy="0.6.0",
        started=DAY,
        status="finished",
        ended=DAY + timedelta(hours=1),
        agent_parallel=2,
        user_parallel=3,
        judge_parallel=1,
        agent_per_minute=60,
        user_per_minute=0,
        judge_per_minute=30,
        agent_file="aa",
        models_file="bb",
        format=6,
        path="bot/2026-10-06T00-00-00_ab12",
        unreadable=0,
    )
    assert (second.run, second.unreadable) == ("2026-10-07T00-00-00_cd34", 1)


@pytest.mark.parametrize(
    ("status", "shown", "ended"),
    [
        (Running(), "running", None),
        (Finished(DAY), "finished", DAY),
        (Interrupted(DAY), "interrupted", DAY),
    ],
)
def test_a_run_row_says_how_the_run_ended(status, shown, ended):
    (row,) = Tables((msgspec.structs.replace(RUN, status=status),)).runs().rows
    assert (row.status, row.ended) == (shown, ended)


def test_scenarios_and_claims_come_in_the_order_of_the_spec():
    assert TABLES.scenarios().rows[:2] == (
        ScenarioRow(run=RUN_ID, scenario="refund", instructions="Ask for a refund.", max_turns=4),
        ScenarioRow(run=RUN_ID, scenario="hello", instructions="Say hi.", max_turns=2),
    )
    assert TABLES.claims().rows[:3] == (
        ClaimRow(
            run=RUN_ID,
            scenario="refund",
            claim=1,
            text="asks for the order",
            grades=None,
            threshold=None,
        ),
        ClaimRow(
            run=RUN_ID,
            scenario="refund",
            claim=2,
            text="solved",
            grades=("none", "partial", "full"),
            threshold="partial",
        ),
        ClaimRow(run=RUN_ID, scenario="hello", claim=1, text="greets", grades=None, threshold=None),
    )


def test_attempts_come_by_scenario_then_number_with_their_verdict():
    assert TABLES.attempts().rows == (
        AttemptRow(
            run=RUN_ID,
            scenario="refund",
            attempt=1,
            verdict="verdict",
            error=None,
            stop="user_stop",
        ),
        AttemptRow(
            run=RUN_ID,
            scenario="refund",
            attempt=2,
            verdict="failed",
            error="agent down",
            stop="agent_failure",
        ),
        AttemptRow(
            run=RUN_ID,
            scenario="hello",
            attempt=1,
            verdict="no_verdict",
            error="judge down",
            stop="model_failure",
        ),
    )


def test_an_attempt_of_a_scenario_the_spec_lacks_is_kept_last():
    gone = Outcome("gone", 1, Transcript(), NoVerdict("judge down"), "model_failure")
    run = msgspec.structs.replace(RUN, outcomes=(gone, *OUTCOMES))
    rows = Tables((run,)).attempts().rows
    assert [(row.scenario, row.attempt) for row in rows] == [
        ("refund", 1),
        ("refund", 2),
        ("hello", 1),
        ("gone", 1),
    ]


def test_decisions_hold_what_the_judge_said_and_none_for_what_it_did_not():
    assert TABLES.decisions().rows == (
        DecisionRow(
            run=RUN_ID,
            scenario="refund",
            attempt=1,
            claim=1,
            passed=True,
            reason="asked",
            confidence=0.9,
            grade=None,
        ),
        DecisionRow(
            run=RUN_ID,
            scenario="refund",
            attempt=1,
            claim=2,
            passed=False,
            reason=None,
            confidence=None,
            grade="none",
        ),
    )


def test_answers_hold_the_dialogue_and_each_token_count_or_none():
    assert TABLES.answers().rows == (
        AnswerRow(
            run=RUN_ID,
            scenario="refund",
            attempt=1,
            turn=1,
            message="Refund,\nplease",
            answer="Your order?",
            seconds=1.5,
            input=100,
            output=20,
            thinking=5,
            cache_read=60,
            cache_write=0,
        ),
        AnswerRow(
            run=RUN_ID,
            scenario="refund",
            attempt=1,
            turn=2,
            message="7",
            answer="Done",
            seconds=0.5,
            input=None,
            output=None,
            thinking=None,
            cache_read=None,
            cache_write=None,
        ),
    )


def test_steps_hold_thoughts_and_calls_with_reported_empty_and_missing_values():
    assert TABLES.steps().rows == (
        StepRow(
            run=RUN_ID,
            scenario="refund",
            attempt=1,
            turn=1,
            step=1,
            kind="thought",
            text="ask",
            name=None,
            started=None,
            seconds=None,
            input=None,
            output=None,
            thinking=None,
            cache_read=None,
            cache_write=None,
            sent=None,
            received=None,
        ),
        StepRow(
            run=RUN_ID,
            scenario="refund",
            attempt=1,
            turn=1,
            step=2,
            kind="call",
            text=None,
            name="search",
            started=DAY,
            seconds=0.5,
            input=10,
            output=2,
            thinking=None,
            cache_read=4,
            cache_write=None,
            sent="order 7",
            received="",
        ),
        StepRow(
            run=RUN_ID,
            scenario="refund",
            attempt=1,
            turn=1,
            step=3,
            kind="call",
            text=None,
            name="lookup",
            started=DAY,
            seconds=0.1,
            input=None,
            output=None,
            thinking=None,
            cache_read=None,
            cache_write=None,
            sent=None,
            received=None,
        ),
    )


def test_every_row_finds_its_parent_by_its_keys():
    scenarios = {(r.run, r.scenario) for r in TABLES.scenarios().rows}
    attempts = {(r.run, r.scenario, r.attempt) for r in TABLES.attempts().rows}
    turns = {(r.run, r.scenario, r.attempt, r.turn) for r in TABLES.answers().rows}
    claims = {(r.run, r.scenario, r.claim) for r in TABLES.claims().rows}
    assert {(r.run, r.scenario) for r in TABLES.attempts().rows} <= scenarios
    assert {(r.run, r.scenario, r.attempt) for r in TABLES.decisions().rows} <= attempts
    assert {(r.run, r.scenario, r.claim) for r in TABLES.decisions().rows} <= claims
    assert {(r.run, r.scenario, r.attempt) for r in TABLES.answers().rows} <= attempts
    assert {(r.run, r.scenario, r.attempt, r.turn) for r in TABLES.steps().rows} <= turns


def test_records_keep_none_tuples_and_datetimes():
    assert TABLES.claims().records()[1]["grades"] == ("none", "partial", "full")
    assert TABLES.runs().records()[0]["started"] == DAY
    assert TABLES.runs().records()[1]["ended"] is None


def test_tables_come_in_order_with_their_rows_and_columns():
    keys = ["run", "scenario", "attempt"]
    tokens = ["input", "output", "thinking", "cache_read", "cache_write"]
    assert [
        (t.name, t.row, [f.encode_name for f in msgspec.structs.fields(t.row)]) for t in TABLES
    ] == [
        (
            "runs",
            RunRow,
            [
                "run",
                "agent",
                "version",
                "user_model",
                "judge_model",
                "k",
                "turn_timeout",
                "trust",
                "convy",
                "started",
                "status",
                "ended",
                "agent_parallel",
                "user_parallel",
                "judge_parallel",
                "agent_per_minute",
                "user_per_minute",
                "judge_per_minute",
                "agent_file",
                "models_file",
                "format",
                "path",
                "unreadable",
            ],
        ),
        ("scenarios", ScenarioRow, ["run", "scenario", "instructions", "max_turns"]),
        ("claims", ClaimRow, ["run", "scenario", "claim", "text", "grades", "threshold"]),
        ("attempts", AttemptRow, [*keys, "verdict", "error", "stop"]),
        ("decisions", DecisionRow, [*keys, "claim", "passed", "reason", "confidence", "grade"]),
        ("answers", AnswerRow, [*keys, "turn", "message", "answer", "seconds", *tokens]),
        (
            "steps",
            StepRow,
            [
                *keys,
                "turn",
                "step",
                "kind",
                "text",
                "name",
                "started",
                "seconds",
                *tokens,
                "sent",
                "received",
            ],
        ),
    ]


COLUMNS = {  # (class, field): the columns it fills; () for a field that only holds other objects
    ("Run", "path"): ("runs.path",),
    ("Run", "spec"): (),
    ("Run", "status"): ("runs.status",),
    ("Run", "outcomes"): (),
    ("Run", "unreadable"): ("runs.unreadable",),
    ("Run", "format"): ("runs.format",),
    ("RunSpec", "id"): ("runs.run",),
    ("RunSpec", "agent"): ("runs.agent",),
    ("RunSpec", "version"): ("runs.version",),
    ("RunSpec", "user"): ("runs.user_model",),
    ("RunSpec", "judge"): ("runs.judge_model",),
    ("RunSpec", "k"): ("runs.k",),
    ("RunSpec", "turn_timeout"): ("runs.turn_timeout",),
    ("RunSpec", "scenarios"): (),
    ("RunSpec", "started"): ("runs.started",),
    ("RunSpec", "convy"): ("runs.convy",),
    ("RunSpec", "files"): (),
    ("RunSpec", "trust"): ("runs.trust",),
    ("RunSpec", "limits"): (),
    ("Files", "agent"): ("runs.agent_file",),
    ("Files", "models"): ("runs.models_file",),
    ("Limits", "agent"): ("runs.agent_parallel",),
    ("Limits", "user"): ("runs.user_parallel",),
    ("Limits", "judge"): ("runs.judge_parallel",),
    ("Limits", "agent_per_minute"): ("runs.agent_per_minute",),
    ("Limits", "user_per_minute"): ("runs.user_per_minute",),
    ("Limits", "judge_per_minute"): ("runs.judge_per_minute",),
    ("Finished", "ended"): ("runs.ended",),
    ("Interrupted", "ended"): ("runs.ended",),
    ("Scenario", "id"): ("scenarios.scenario",),
    ("Scenario", "max_turns"): ("scenarios.max_turns",),
    ("Scenario", "instructions"): ("scenarios.instructions",),
    ("Scenario", "claims"): ("claims.text",),  # a plain claim is its text
    ("Graded", "text"): ("claims.text",),
    ("Graded", "grades"): ("claims.grades",),
    ("Graded", "threshold"): ("claims.threshold",),
    ("Outcome", "scenario"): ("attempts.scenario",),
    ("Outcome", "attempt"): ("attempts.attempt",),
    ("Outcome", "transcript"): (),
    ("Outcome", "verdict"): ("attempts.verdict",),
    ("Outcome", "stop"): ("attempts.stop",),
    ("Transcript", "turns"): (),
    ("Verdict", "claims"): (),
    ("Failed", "reason"): ("attempts.error",),
    ("NoVerdict", "error"): ("attempts.error",),
    ("Claim", "passed"): ("decisions.passed",),
    ("Claim", "reason"): (),
    ("Claim", "confidence"): (),
    ("Claim", "grade"): (),
    ("Reason", "text"): ("decisions.reason",),
    ("Confidence", "value"): ("decisions.confidence",),
    ("Grade", "value"): ("decisions.grade",),
    ("Turn", "message"): (),
    ("Turn", "answer"): (),
    ("Turn", "seconds"): ("answers.seconds",),
    ("Message", "text"): ("answers.message",),
    ("Answer", "text"): ("answers.answer",),
    ("Answer", "usage"): (),
    ("Answer", "steps"): ("steps.kind",),  # which kind of step
    ("Usage", "input"): ("answers.input", "steps.input"),
    ("Usage", "output"): ("answers.output", "steps.output"),
    ("Usage", "thinking"): ("answers.thinking", "steps.thinking"),
    ("Usage", "cache_read"): ("answers.cache_read", "steps.cache_read"),
    ("Usage", "cache_write"): ("answers.cache_write", "steps.cache_write"),
    ("Thought", "text"): ("steps.text",),
    ("Call", "name"): ("steps.name",),
    ("Call", "started"): ("steps.started",),
    ("Call", "seconds"): ("steps.seconds",),
    ("Call", "usage"): (),
    ("Call", "sent"): (),
    ("Call", "received"): (),
    ("Reported", "text"): ("steps.sent", "steps.received"),
}
CHILDREN = ("scenarios", "claims", "attempts", "decisions", "answers", "steps")
KEYS = {  # copied from the parent row, or a position from 1: no field of their own
    *(f"{table}.run" for table in CHILDREN),
    *(f"{table}.scenario" for table in ("claims", "decisions", "answers", "steps")),
    *(f"{table}.attempt" for table in ("decisions", "answers", "steps")),
    *("claims.claim", "decisions.claim", "answers.turn", "steps.turn", "steps.step"),
}


def fields(kind: msgspec.inspect.Type, seen: set[str]) -> set[tuple[str, str]]:
    """Every (class, field) reachable from `kind`."""
    match kind:
        case msgspec.inspect.StructType(cls=cls, fields=found) if cls.__name__ not in seen:
            seen.add(cls.__name__)
            own = {(cls.__name__, field.name) for field in found}
            return own.union(*(fields(field.type, seen) for field in found))
        case msgspec.inspect.UnionType(types=types):
            return set().union(*(fields(item, seen) for item in types))
        case (
            msgspec.inspect.VarTupleType(item_type=item) | msgspec.inspect.ListType(item_type=item)
        ):
            return fields(item, seen)
        case _:
            return set()


def test_every_field_of_a_run_has_a_column():
    assert fields(msgspec.inspect.type_info(Run), set()) == set(COLUMNS)


def test_every_column_but_the_keys_holds_a_field_of_a_run():
    named = {column for columns in COLUMNS.values() for column in columns}
    columns = {
        f"{t.name}.{f.encode_name}" for t in Tables(()) for f in msgspec.structs.fields(t.row)
    }
    assert named == columns - KEYS


class Cells(msgspec.Struct, frozen=True, kw_only=True):
    text: str | None
    flag: bool
    grades: tuple[str, ...] | None
    at: datetime | None
    number: float


CELLS = Table(
    "cells",
    Cells,
    (
        Cells(text='two\nlines, "quoted"', flag=True, grades=("a", "b"), at=DAY, number=0.5),
        Cells(text="", flag=False, grades=None, at=None, number=2),
    ),
)  # Table("cells", Cells, (...)): the row type comes second


def test_csv_quotes_every_value_and_leaves_a_missing_one_empty():
    assert CELLS.csv() == (
        '"text","flag","grades","at","number"\r\n'
        '"two\nlines, ""quoted""","true","[""a"",""b""]","2026-10-06T00:00:00+00:00","0.5"\r\n'
        '"","false",,,"2"\r\n'
    )


def test_an_empty_table_still_has_its_header():
    assert Table("cells", Cells, ()).csv() == '"text","flag","grades","at","number"\r\n'


def test_json_lines_give_every_row_back_with_null_and_empty_text_apart():
    assert CELLS.jsonl().endswith("}\n")
    lines = [json.loads(line) for line in CELLS.jsonl().splitlines()]
    assert lines == [
        {
            "text": 'two\nlines, "quoted"',
            "flag": True,
            "grades": ["a", "b"],
            "at": "2026-10-06T00:00:00Z",
            "number": 0.5,
        },
        {"text": "", "flag": False, "grades": None, "at": None, "number": 2},
    ]


def test_export_writes_each_table_s_text_as_it_is(tmp_path: Path):
    folder = Project(tmp_path).export(TABLES)
    answers = TABLES.answers()
    assert (folder / "answers.csv").read_bytes() == b"\xef\xbb\xbf" + answers.csv().encode()
    assert (folder / "answers.jsonl").read_bytes() == answers.jsonl().encode()
