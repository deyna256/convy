import json
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean

import msgspec
import pytest

from convy import (
    AnswerRow,
    AttemptRow,
    ClaimRow,
    DecisionRow,
    Report,
    RunRow,
    ScenarioRow,
    StepRow,
    Table,
    Tables,
)
from convy.agent import Answer, Call, Message, NoUsage, Reported, Thought, Usage
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
    ids=["running", "finished", "interrupted"],
)
def test_a_run_row_says_how_the_run_ended(status, shown, ended):
    (row,) = Tables((msgspec.structs.replace(RUN, status=status),)).runs().rows
    assert (row.status, row.ended) == (shown, ended)


def test_runs_come_by_start_time_then_id():
    early = msgspec.structs.replace(RUN, spec=msgspec.structs.replace(SPEC, id="z"))
    tie = msgspec.structs.replace(RUN, spec=msgspec.structs.replace(SPEC, id="b"))
    late = msgspec.structs.replace(LIVE, spec=msgspec.structs.replace(LIVE.spec, id="a"))
    assert [row.run for row in Tables((late, early, tie)).runs().rows] == ["b", "z", "a"]


def test_scenarios_come_in_the_order_of_the_spec():
    assert TABLES.scenarios().rows[:2] == (
        ScenarioRow(run=RUN_ID, scenario="refund", instructions="Ask for a refund.", max_turns=4),
        ScenarioRow(run=RUN_ID, scenario="hello", instructions="Say hi.", max_turns=2),
    )


def test_claims_come_in_the_order_of_their_scenario():
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
    runs = {r.run for r in TABLES.runs().rows}
    scenarios = {(r.run, r.scenario) for r in TABLES.scenarios().rows}
    attempts = {(r.run, r.scenario, r.attempt) for r in TABLES.attempts().rows}
    turns = {(r.run, r.scenario, r.attempt, r.turn) for r in TABLES.answers().rows}
    claims = {(r.run, r.scenario, r.claim) for r in TABLES.claims().rows}
    assert {r.run for r in TABLES.scenarios().rows} <= runs
    assert {(r.run, r.scenario) for r in TABLES.claims().rows} <= scenarios
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


def reachable_fields(kind: msgspec.inspect.Type, seen: set[str]) -> set[tuple[str, str]]:
    """Every (class, field) reachable from `kind`."""
    match kind:
        case msgspec.inspect.StructType(cls=cls, fields=found) if cls.__name__ not in seen:
            seen.add(cls.__name__)
            own = {(cls.__name__, field.name) for field in found}
            return own.union(*(reachable_fields(field.type, seen) for field in found))
        case msgspec.inspect.UnionType(types=items) | msgspec.inspect.TupleType(item_types=items):
            return set().union(*(reachable_fields(item, seen) for item in items))
        case (
            msgspec.inspect.VarTupleType(item_type=item)
            | msgspec.inspect.ListType(item_type=item)
            | msgspec.inspect.DictType(value_type=item)
        ):
            return reachable_fields(item, seen)
        case _:
            return set()


def test_every_field_of_a_run_has_a_column():
    assert reachable_fields(msgspec.inspect.type_info(Run), set()) == set(COLUMNS)


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
)


def test_csv_quotes_every_value_writes_what_is_not_text_as_json_and_leaves_a_missing_one_empty():
    assert CELLS.csv() == (
        '"text","flag","grades","at","number"\r\n'
        '"two\nlines, ""quoted""","true","[""a"",""b""]","2026-10-06T00:00:00Z","0.5"\r\n'
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


def trusted(decision: DecisionRow, trust: float) -> bool:
    """Pass rate: a decision without a confidence is trusted; else it is trusted at `trust`."""
    return decision.confidence is None or decision.confidence >= trust


def counted(tables: Tables, trust: float) -> dict[tuple[str, int], bool]:
    """Pass rate: the counted attempts and whether each passed. One counts when the agent failed,
    or when every decision is trusted or a trusted decision failed."""
    decisions: defaultdict[tuple[str, int], list[DecisionRow]] = defaultdict(list)
    for d in tables.decisions().rows:
        decisions[d.scenario, d.attempt].append(d)
    found: dict[tuple[str, int], bool] = {}
    for a in tables.attempts().rows:
        made = decisions[a.scenario, a.attempt]
        sure = [d for d in made if trusted(d, trust)]
        match a.verdict:
            case "failed":
                found[a.scenario, a.attempt] = False
            case "verdict" if len(sure) == len(made) or any(not d.passed for d in sure):
                found[a.scenario, a.attempt] = all(d.passed for d in made)
    return found


def stable(tables: Tables, k: int, trust: float) -> int:
    """Stable scenarios: those whose `k` attempts were all played, counted and passed."""
    passed = Counter(scenario for (scenario, _), held in counted(tables, trust).items() if held)
    return sum(times == k for times in passed.values())


def seconds_per_answer(tables: Tables) -> float:
    """Time per answer: the mean of the answers' seconds."""
    return mean(a.seconds for a in tables.answers().rows)


def tokens_per_attempt(tables: Tables) -> float:
    """Tokens per attempt: the mean, over the attempts that report them, of the sum of their
    answers' input and output."""
    tokens: defaultdict[tuple[str, int], int] = defaultdict(int)
    for a in tables.answers().rows:
        if a.input is not None and a.output is not None:
            tokens[a.scenario, a.attempt] += a.input + a.output
    return mean(tokens.values())


def cache_share(tables: Tables) -> float:
    """Tokens per attempt: the sum of `cache_read` over the sum of input, both over the answers
    that report `cache_read`."""
    pairs = [
        (a.cache_read, a.input)
        for a in tables.answers().rows
        if a.cache_read is not None and a.input is not None
    ]
    return sum(read for read, _ in pairs) / sum(spent for _, spent in pairs)


def claim_counts(tables: Tables, trust: float) -> list[tuple[int, int]]:
    """Scenarios: a claim's count, held of judged, is over its trusted decisions."""
    counts = []
    for c in tables.claims().rows:
        made = [
            d.passed
            for d in tables.decisions().rows
            if (d.scenario, d.claim) == (c.scenario, c.claim) and trusted(d, trust)
        ]
        counts.append((sum(made), len(made)))
    return counts


def typical_grade(tables: Tables, trust: float, scenario: str) -> str | None:
    """Scenarios: a claim's typical grade is the middle one of its trusted grades, in the claim's
    order; with two in the middle, the worse."""
    ((number, levels),) = [
        (c.claim, c.grades)
        for c in tables.claims().rows
        if c.scenario == scenario and c.grades is not None
    ]
    grades = sorted(
        (
            d.grade
            for d in tables.decisions().rows
            if (d.scenario, d.claim) == (scenario, number)
            and trusted(d, trust)
            and d.grade is not None
        ),
        key=levels.index,
    )
    return grades[(len(grades) - 1) // 2] if grades else None


def answered(usage: Usage | NoUsage, seconds: float) -> Turn:
    return Turn(Message("hi"), Answer("a", usage), seconds)


def played(
    scenario: str, attempt: int, verdict: Verdict | Failed | NoVerdict, *turns: Turn
) -> Outcome:
    return Outcome(scenario, attempt, Transcript(turns), verdict, "user_stop")


def sure(passed: bool, value: float) -> Claim:
    return Claim(passed, confidence=Confidence(value))


NUMBERS = Run(
    Path("bot/numbers"),
    msgspec.structs.replace(
        SPEC, k=6, trust=0.8, scenarios=(Scenario("s", 2, "Ask.", ("one", "two")),)
    ),
    Finished(DAY),
    (  # 0.8 is the trust: trusted at >=, so attempt 1 counts and claim one holds 3 of 3
        played(
            "s",
            1,
            Verdict((sure(True, 0.8), sure(True, 0.9))),
            answered(Usage(100, 10, cache_read=80), 1.0),
        ),
        played("s", 2, Verdict((sure(True, 0.9), sure(True, 0.5))), answered(Usage(100, 10), 2.0)),
        played(
            "s",
            3,
            Verdict((sure(False, 0.5), sure(False, 0.9))),
            answered(Usage(200, 10, cache_read=20), 3.0),
        ),
        played("s", 4, Verdict((Claim(True), Claim(True))), answered(NoUsage(), 1.0)),
        played("s", 5, Failed("down")),
        played("s", 6, NoVerdict("judge down")),
    ),
)
NUMBERS_PAGE = Report(NUMBERS).page()
NUMBERS_TABLES = Tables((NUMBERS,))
GRADES = Run(
    Path("bot/grades"),
    msgspec.structs.replace(
        SPEC,
        k=2,
        trust=0.5,
        scenarios=(
            Scenario("a", 2, "Ask.", ("one",)),
            Scenario("b", 2, "Ask.", (GRADED,)),
            Scenario("c", 2, "Ask.", ("one",)),
            Scenario("d", 2, "Ask.", ("one",)),
            Scenario("e", 2, "Ask.", ("one",)),
        ),
    ),
    Finished(DAY),
    (
        played("a", 1, Verdict((Claim(True),))),
        played("a", 2, Verdict((Claim(True),))),
        played("b", 1, Verdict((Claim(True, confidence=Confidence(0.9), grade=Grade("full")),))),
        played("b", 2, Verdict((Claim(False, confidence=Confidence(0.1), grade=Grade("none")),))),
        played("c", 1, Verdict((Claim(True),))),
        played("d", 1, Verdict((Claim(True),))),
        played("d", 2, Verdict((Claim(False),))),
        played("e", 1, Verdict((Claim(True),))),
        played("e", 2, Verdict((sure(True, 0.1),))),
    ),  # with the unsure grade, b's grades are none and full, and the worse of two is none
)  # stable: a only; c has an attempt not played, d one that failed, e one not counted
GRADES_PAGE = Report(GRADES).page()
GRADES_TABLES = Tables((GRADES,))


def test_the_pass_rate_is_the_share_of_counted_attempts_that_passed():
    passed = list(counted(NUMBERS_TABLES, 0.8).values())
    metrics = NUMBERS_PAGE.metrics
    assert (sum(passed), len(passed)) == (metrics.passed, metrics.judged) == (2, 4)


def test_a_stable_scenario_has_its_k_attempts_counted_and_passed():
    assert stable(GRADES_TABLES, 2, 0.5) == GRADES_PAGE.metrics.stable == 1


def test_the_time_per_answer_is_the_mean_of_the_answers_seconds():
    assert seconds_per_answer(NUMBERS_TABLES) == NUMBERS_PAGE.metrics.seconds == 1.75


def test_the_tokens_per_attempt_are_the_mean_over_the_attempts_that_report_them():
    assert tokens_per_attempt(NUMBERS_TABLES) == NUMBERS_PAGE.metrics.tokens == 430 / 3


def test_the_cache_share_is_over_the_answers_that_report_a_cache_read():
    assert cache_share(NUMBERS_TABLES) == NUMBERS_PAGE.metrics.cached == 100 / 300


def test_a_claim_s_count_is_over_its_trusted_decisions():
    (scenario,) = NUMBERS_PAGE.scenarios
    assert (
        claim_counts(NUMBERS_TABLES, 0.8)
        == [(c.held, c.judged) for c in scenario.claims]
        == [(3, 3), (2, 3)]
    )


def test_a_claim_s_typical_grade_is_the_middle_of_its_trusted_grades():
    (b,) = (scenario for scenario in GRADES_PAGE.scenarios if scenario.id == "b")
    assert typical_grade(GRADES_TABLES, 0.5, "b") == b.claims[0].typical == "full"
