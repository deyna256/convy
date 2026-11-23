import json
import re
import secrets
import shutil
import subprocess
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import msgspec
import pytest

from convy import Requirement
from convy.agent import Answer, Call, Message, NoUsage, Reported, Thought, Usage
from convy.bench import CONVY, Files, Finished, Interrupted, Limits, RunJournal, RunSpec
from convy.busy import Patience, Places
from convy.dialog import (
    Claim,
    Confidence,
    Failed,
    NoVerdict,
    Reason,
    Transcript,
    Turn,
    Verdict,
)
from convy.fakes import FakeAgent, FakeJudge, FakeModel
from convy.model import Models
from convy.report import (
    CallPlace,
    CallView,
    Category,
    Comparison,
    Evidence,
    Index,
    Parts,
    Report,
    ResultBucket,
    Run,
    Runs,
    ScenarioNumbers,
    Share,
    Shares,
    Spread,
    Summary,
    Tally,
    ThoughtView,
    TurnView,
)
from convy.scenario import Outcome, Scenario

DAY = datetime(2026, 10, 6, tzinfo=UTC)
DEFAULT_LIMITS = Limits()
PASSED = Verdict((Claim(True),))
FAILED = Verdict((Claim(False),))


def unsure(passed: bool, value: float) -> Verdict:
    return Verdict((Claim(passed, confidence=Confidence(value)),))


def outcome(
    scenario: str,
    verdict: Verdict | Failed | NoVerdict,
    text: str = "hello",
    tokens: int = 10,
    attempt: int = 1,
) -> Outcome:
    turn = Turn(Message("hi"), Answer(text, Usage(tokens, tokens)), 2.0)
    match verdict:
        case NoVerdict():
            stop = "model_failure"
        case Failed():
            stop = "agent_failure"
        case _:
            stop = "max_turns"
    return Outcome(scenario, attempt, Transcript((turn,)), verdict, stop)


def journal(
    directory: Path,
    agent: str,
    version: str,
    scenarios: int,
    *outcomes: Outcome,
    started: datetime | None = None,
    models: tuple[str, str] = ("fake", "fake"),
    id: str = "",
    k: int = 1,
    asks: str = "Say hi.",
    claims: tuple[Requirement, ...] = (Requirement("greets"),),
    trust: float = 0.0,
    claim_threshold: float = 1.0,
    convy: str = CONVY,
    limits: Limits = DEFAULT_LIMITS,
) -> RunJournal:
    """A run of `scenarios` scenarios, `a`, `b`, …, `k` attempts each, holding `outcomes`."""
    started = started or datetime.now(UTC)
    played = tuple(Scenario(chr(97 + i), 1, asks, claims) for i in range(scenarios))
    user, judge = models
    spec = RunSpec(
        id=id or f"{started:%Y-%m-%dT%H-%M-%S}_{secrets.token_hex(2)}",
        agent=agent,
        version=version,
        user=user,
        judge=judge,
        k=k,
        turn_timeout=600,
        scenarios=played,
        started=started,
        trust=trust,
        claim_threshold=claim_threshold,
        convy=convy,
        limits=limits,
    )
    written = RunJournal(directory, spec)
    written.create()
    for item in outcomes:
        written.record(item)
    return written


@pytest.mark.parametrize("format", [1, 2, 3, 4, 5, 6, 7, 8, 10])
def test_unsupported_runs_are_rejected_without_changing_their_files(tmp_path, format):
    written = journal(tmp_path, "bot", "1", 1, outcome("a", PASSED))
    folder = written.folder()
    path = folder / "run.json"
    data = json.loads(path.read_text())
    path.write_text(json.dumps({**data, "format": format}))
    before = {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}
    with pytest.raises(ValueError, match="start a new run"):
        Runs(tmp_path).read(folder)
    assert list(Runs(tmp_path)) == []
    assert Runs(tmp_path).broken([]) == (folder.relative_to(tmp_path),)
    assert {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()} == before


def test_runs_read_back_what_journals_wrote(tmp_path):
    steps = (
        Thought("plan"),
        Call(kind="tool", name="search", started=DAY, seconds=1.5, received=Reported("")),
    )
    turn = Turn(
        Message("hi"), Answer("hello", Usage(10, 5, cache_read=4), steps, steps_complete=True), 2.0
    )
    written = Outcome("a", 1, Transcript((turn,)), NoVerdict("judge down"), "model_failure")
    run_journal = journal(tmp_path, "bot", "1", 1, written)
    run_journal.write(Finished(datetime.now(UTC)))
    (run,) = Runs(tmp_path)
    assert run.outcomes == (written,)
    assert run.spec == run_journal.spec
    assert isinstance(run.status, Finished)
    assert run.done() == set(run.spec.pairs()) == {("a", 1)}
    assert Runs(tmp_path).broken([run]) == ()


def test_runs_skip_and_list_a_broken_run(tmp_path):
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED))
    (tmp_path / "bot" / "broken").mkdir()
    (tmp_path / "bot" / "broken" / "run.json").write_text("not json\n")
    (tmp_path / "bot" / "older").mkdir()
    (tmp_path / "bot" / "older" / "run.json").write_text('{"format": 1}\n')  # another format
    read = list(Runs(tmp_path))
    assert len(read) == 1
    assert Runs(tmp_path).broken(read) == (Path("bot/broken"), Path("bot/older"))


def test_runs_keep_the_lines_they_can_read(tmp_path):
    good = outcome("a", PASSED)
    written = journal(tmp_path, "bot", "1", 2, good, outcome("b", PASSED))
    attempts = written.folder() / "attempts.jsonl"
    attempts.write_bytes(attempts.read_bytes()[:-20])  # the last line cut short, as by a crash
    (run,) = Runs(tmp_path)
    assert run.outcomes == (good,)
    assert (run.unreadable, run.done() == set(run.spec.pairs())) == (1, False)
    assert Runs(tmp_path).broken([run]) == (run.path,) == (written.folder().relative_to(tmp_path),)


def test_runs_count_a_line_the_scenarios_cannot_explain_as_unreadable(tmp_path):
    good = outcome("a", PASSED)
    two = Verdict((Claim(True), Claim(True)))  # scenario a has one claim
    written = journal(
        tmp_path, "bot", "1", 1, good, outcome("zzz", PASSED), outcome("a", two, attempt=2), k=2
    )
    (run,) = Runs(tmp_path)
    assert run.outcomes == (good,)
    assert run.unreadable == 2
    assert Runs(tmp_path).broken([run]) == (written.folder().relative_to(tmp_path),)
    assert run.spec.id in Report(run).html()  # the page is still written


def test_runs_read_an_attempt_written_twice_once(tmp_path):
    first = outcome("a", PASSED)
    journal(tmp_path, "bot", "1", 1, first, outcome("a", FAILED))
    (run,) = Runs(tmp_path)
    assert run.outcomes == (first,)


def test_a_run_without_attempts_is_read(tmp_path):
    journal(tmp_path, "bot", "1", 2)
    (run,) = Runs(tmp_path)
    assert run.outcomes == ()


def test_old_journals_are_not_runs(tmp_path):
    (tmp_path / "runs" / "bot").mkdir(parents=True)
    (tmp_path / "runs" / "bot" / "2026-10-06T14-05-00.000000.jsonl").write_text("{}\n")
    assert list(Runs(tmp_path)) == []
    assert Runs(tmp_path).broken([]) == ()


def test_a_run_is_found_by_its_id_or_its_random_part(tmp_path):
    written = journal(tmp_path, "bot", "1", 1)
    other = journal(tmp_path, "other", "1", 1)
    spec = written.spec
    assert Runs(tmp_path).run(spec.id).spec == spec
    assert Runs(tmp_path).run(spec.short()).spec == spec
    assert Runs(tmp_path).run(other.spec.id).spec == other.spec


def test_a_run_that_is_not_there_or_not_one_is_an_error(tmp_path):
    journal(tmp_path, "bot", "1", 1, id="2026-10-06T14-05-00_a3f9")
    journal(tmp_path, "bot", "1", 1, id="2026-10-07T09-30-00_a3f9")
    with pytest.raises(ValueError, match="no run 'nope'"):
        Runs(tmp_path).run("nope")
    with pytest.raises(ValueError, match="'a3f9' names several runs"):
        Runs(tmp_path).run("a3f9")


def at(day: int) -> datetime:
    return DAY.replace(day=day)


def only(directory: Path, agent: str = "bot") -> Run:
    """The one run of `agent` under `directory`."""
    (run,) = (run for run in Runs(directory) if run.spec.agent == agent)
    return run


def both(directory: Path) -> tuple[Run, Run]:
    """The two runs under `directory`, oldest first."""
    first, second = sorted(Runs(directory), key=lambda run: run.spec.started)
    return first, second


def test_an_agent_whose_service_stayed_busy_counts_as_busy_not_in_the_pass_rate(tmp_path):
    busy = msgspec.structs.replace(outcome("a", NoVerdict("busy")), stop="agent_busy")
    journal(tmp_path, "bot", "1", 1, busy, outcome("a", PASSED, attempt=2), k=2)
    metrics = Report(only(tmp_path)).page().metrics
    assert (metrics.passed, metrics.judged) == (1, 1)
    assert (metrics.agent_errors, metrics.busy, metrics.model_errors, metrics.errors) == (
        0,
        1,
        0,
        1,
    )


def test_a_scenario_is_failing_flaky_passing_or_without_a_verdict(tmp_path):
    journal(
        tmp_path,
        "bot",
        "1",
        4,
        outcome("a", PASSED),
        outcome("a", PASSED, attempt=2),
        outcome("b", FAILED),
        outcome("b", Failed("down"), attempt=2),
        outcome("c", PASSED),
        outcome("c", FAILED, attempt=2),
        outcome("d", NoVerdict("judge down")),
        outcome("d", NoVerdict("judge down"), attempt=2),
        k=2,
    )
    page = Report(only(tmp_path)).page()
    assert [(s.id, s.result) for s in page.scenarios] == [
        ("b", "failing"),
        ("c", "flaky"),
        ("d", "none"),
        ("a", "passing"),
    ]


def test_tiles_count_attempts_stable_scenarios_time_tokens_and_errors(tmp_path):
    journal(
        tmp_path,
        "bot",
        "1",
        3,
        outcome("a", PASSED, tokens=10),
        outcome("a", PASSED, attempt=2, tokens=20),
        outcome("b", PASSED, tokens=30),
        outcome("b", Failed("down"), attempt=2, tokens=40),
        outcome("c", NoVerdict("judge down"), tokens=50),
        k=2,
    )
    page = Report(only(tmp_path)).page()
    metrics = page.metrics
    assert (metrics.passed, metrics.judged, metrics.rate) == (3, 4, 0.75)
    assert (metrics.stable, metrics.flaky) == (1, 1)  # a passed both, b one of two
    assert metrics.seconds == Spread(5, 2, 2, 2, 2, 2)  # five answers of 2 s
    # tokens 20, 40, 60, 80, 100: p50 the
    # third, 60; p90 at 3.6, 0.6 of the way from 80 to 100, 92
    assert metrics.tokens == Spread(5, 20, 60, 92, 100, 60)
    assert metrics.open == 1  # c's judge was down
    assert (metrics.agent_errors, metrics.busy, metrics.model_errors, metrics.errors) == (
        1,
        0,
        1,
        2,
    )
    assert (page.run.short, page.run.agent, page.run.status, page.run.k, page.run.scenarios) == (
        page.run.id.rpartition("_")[2],
        "bot",
        "running",
        2,
        3,
    )
    a = next(s for s in page.scenarios if s.id == "a")
    # 20 then 40 tokens: p50 halfway, 30; p90 0.9 of the way, 38
    assert (a.rate, a.tokens) == (1, Spread(2, 20, 30, 38, 40, 30))
    first = a.attempts[0]
    assert (first.tokens, first.slowest, first.turns[0].tokens) == (20, 2.0, 20)


def test_a_run_head_says_whether_the_run_finished_or_was_interrupted(tmp_path):
    finished = journal(tmp_path, "bot", "1", 1, started=at(5))
    finished.write(Finished(at(5)))
    interrupted = journal(tmp_path, "bot", "1", 1, started=at(6))
    interrupted.write(Interrupted(at(6)))
    first, second = both(tmp_path)
    assert Report(first).page().run.status == "finished"
    assert Report(second).page().run.status == "interrupted"


def test_with_one_attempt_each_a_passing_scenario_is_stable(tmp_path):
    journal(tmp_path, "bot", "1", 2, outcome("a", PASSED), outcome("b", FAILED))
    assert Report(only(tmp_path)).page().metrics.stable == 1


def test_a_run_without_verdicts_or_usage_reports_none(tmp_path):
    turn = Turn(Message("hi"), Answer("hello", NoUsage()), 1.0)
    written = Outcome("a", 1, Transcript((turn,)), NoVerdict("judge down"), "model_failure")
    journal(tmp_path, "bot", "1", 1, written)
    page = Report(only(tmp_path)).page()
    assert (page.metrics.rate, page.metrics.tokens) == (None, None)
    (scenario,) = page.scenarios
    (attempt,) = scenario.attempts
    assert (attempt.input, attempt.output, attempt.tokens) == (None, None, None)
    assert (attempt.turns[0].input, attempt.turns[0].tokens) == (None, None)
    assert attempt.thinking_tokens is None
    assert (attempt.passed, attempt.error) == (None, "judge down")


def test_a_turn_shows_its_thinking_tokens_when_reported(tmp_path):
    turns = (
        Turn(Message("hi"), Answer("a", Usage(10, 30, 20)), 1.0),
        Turn(Message("and?"), Answer("b", Usage(5, 10, 0)), 1.0),  # none spent on thinking
        Turn(Message("so?"), Answer("c", Usage(5, 10)), 1.0),  # not reported
        Turn(Message("ok"), Answer("d"), 1.0),  # no usage
    )
    journal(tmp_path, "bot", "1", 1, Outcome("a", 1, Transcript(turns), PASSED, "max_turns"))
    page = Report(only(tmp_path)).page()
    (attempt,) = page.scenarios[0].attempts
    assert [t.thinking_tokens for t in attempt.turns] == [20, 0, None, None]
    assert (attempt.output, attempt.thinking_tokens) == (None, 20)  # output is incomplete


def test_cache_tokens_add_up_and_their_share_skips_turns_without_them(tmp_path):
    turns = (
        Turn(Message("hi"), Answer("a", Usage(100, 10, cache_read=80, cache_write=20)), 1.0),
        Turn(Message("and?"), Answer("b", Usage(50, 10, cache_read=0)), 1.0),  # none hit
        Turn(Message("so?"), Answer("c", Usage(1000, 10)), 1.0),  # left out of the share
    )
    journal(tmp_path, "bot", "1", 1, Outcome("a", 1, Transcript(turns), PASSED, "max_turns"))
    page = Report(only(tmp_path)).page()
    (attempt,) = page.scenarios[0].attempts
    assert [(t.cache_read, t.cache_write) for t in attempt.turns] == [
        (80, 20),
        (0, None),
        (None, None),
    ]
    assert (attempt.cache_read, attempt.cache_write) == (80, 20)
    assert page.metrics.cached == 80 / 150  # the code computes the same expression


def test_the_cache_share_weighs_every_attempt_by_its_input(tmp_path):
    def played(attempt: int, usage: Usage) -> Outcome:
        turn = Turn(Message("hi"), Answer("a", usage), 1.0)
        return Outcome("a", attempt, Transcript((turn,)), PASSED, "max_turns")

    first, second = (
        played(1, Usage(100, 10, cache_read=90)),
        played(2, Usage(300, 10, cache_read=0)),
    )
    journal(tmp_path, "bot", "1", 1, first, second, k=2)
    assert Report(only(tmp_path)).page().metrics.cached == 90 / 400  # not the mean of 90% and 0%


@pytest.mark.parametrize(
    "usage",
    [Usage(10, 5), Usage(0, 5, cache_read=0), NoUsage()],
    ids=["no cache", "no input", "no usage"],
)
def test_the_cache_share_is_none_without_cache_counts_or_input(tmp_path, usage):
    turn = Turn(Message("hi"), Answer("a", usage), 1.0)
    journal(tmp_path, "bot", "1", 1, Outcome("a", 1, Transcript((turn,)), PASSED, "max_turns"))
    assert Report(only(tmp_path)).page().metrics.cached is None


AGENT_CLOCK = datetime(2001, 1, 1, tzinfo=UTC)  # far from the time convy measures


NO_USAGE = NoUsage()


def call(
    name: str,
    at: float,
    seconds: float,
    usage: Usage | NoUsage = NO_USAGE,
    *,
    kind: Literal["model", "tool"] = "tool",
) -> Call:
    """A call `at` seconds after the agent's first, by the agent's clock."""
    return Call(
        kind=kind,
        name=name,
        started=AGENT_CLOCK + timedelta(seconds=at),
        seconds=seconds,
        usage=usage,
    )


def shown(tmp_path: Path, *steps: Thought | Call) -> TurnView:
    """How the run's page shows one answer with `steps`."""
    turn = Turn(Message("hi"), Answer("hello", steps=steps), 2.0)
    journal(tmp_path, "bot", "1", 1, Outcome("a", 1, Transcript((turn,)), PASSED, "max_turns"))
    return Report(only(tmp_path)).page().scenarios[0].attempts[0].turns[0]


def bar(
    name: str,
    seconds: float,
    left: float,
    width: float,
    tokens: int | None = None,
    sent: str | None = None,
    received: str | None = None,
    start: float = 0.0,
    kind: Literal["model", "tool"] = "tool",
) -> CallView:
    return CallView(
        kind=kind,
        name=name,
        seconds=seconds,
        left=left,
        width=width,
        start=start,
        tokens=tokens,
        sent=sent,
        received=received,
    )


def test_calls_sit_on_their_own_time_line(tmp_path):
    turn = shown(tmp_path, call("search", 0, 1), call("gpt", 2, 2, kind="model"))
    assert turn.steps == (bar("search", 1, 0, 0.25), bar("gpt", 2, 0.5, 0.5, start=2, kind="model"))
    assert turn.span == 4


def test_overlapping_calls_share_the_time_line(tmp_path):
    turn = shown(tmp_path, call("search", 0, 4), call("embed", 1, 1, kind="model"))
    assert turn.steps == (
        bar("search", 4, 0, 1),
        bar("embed", 1, 0.25, 0.25, start=1, kind="model"),
    )
    assert turn.span == 4


def test_an_instant_call_has_a_time_line(tmp_path):
    assert shown(tmp_path, call("cache", 0, 0)).steps == (bar("cache", 0, 0, 0),)


def test_a_huge_call_does_not_break_the_report(tmp_path):
    """A time in ms given as seconds: no `datetime` is made from it, so nothing overflows."""
    assert shown(tmp_path, call("search", 0, 1.7e12)).steps == (bar("search", 1.7e12, 0, 1),)


def test_a_call_shows_what_it_reported_and_what_it_did_not(tmp_path):
    searched = Call(
        kind="tool",
        name="search",
        started=AGENT_CLOCK,
        seconds=1,
        sent=Reported("refund rules"),
        received=Reported(""),
    )
    turn = shown(tmp_path, searched, call("gpt", 1, 1, Usage(3, 4, 2), kind="model"))
    assert turn.steps == (
        bar("search", 1, 0, 0.5, sent="refund rules", received=""),
        bar("gpt", 1, 0.5, 0.5, tokens=7, start=1, kind="model"),
    )


def test_steps_keep_their_order_and_counts(tmp_path):
    turn = shown(tmp_path, Thought("look it up"), call("search", 0, 1), Thought("found it"))
    assert turn.steps == (
        ThoughtView("look it up"),
        bar("search", 1, 0, 1),
        ThoughtView("found it"),
    )
    assert (turn.thoughts, turn.calls) == (2, 1)


def test_an_answer_without_calls_has_no_time_line(tmp_path):
    bare = shown(tmp_path)
    thought = shown(tmp_path / "thought", Thought("hmm"))
    assert (bare.span, thought.span) == (0, 0)
    assert (bare.steps, bare.thoughts, bare.calls) == ((), 0, 0)


def test_calls_in_other_time_zones_share_the_time_line(tmp_path):
    moment = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
    utc = Call(kind="tool", name="a", started=moment, seconds=1)
    plus3 = Call(
        kind="tool", name="b", started=moment.astimezone(timezone(timedelta(hours=3))), seconds=1
    )
    assert shown(tmp_path, utc, plus3).steps == (bar("a", 1, 0, 1), bar("b", 1, 0, 1))


def test_a_claim_is_summed_up_over_the_attempts_the_judge_decided(tmp_path):
    decided = Verdict((Claim(True, Reason("said hi")), Claim(False, Reason("too long"))))
    held = Verdict((Claim(True), Claim(True)))
    played = (outcome("a", v, attempt=n) for n, v in enumerate((decided, held, Failed("down")), 1))
    journal(
        tmp_path,
        "bot",
        "1",
        1,
        *played,
        k=3,
        claims=(Requirement("greets"), Requirement("is brief")),
    )
    (scenario,) = Report(only(tmp_path)).page().scenarios
    assert [(c.text, c.held, c.judged, c.result) for c in scenario.claims] == [
        ("greets", 2, 2, "passing"),
        ("is brief", 1, 2, "flaky"),
    ]
    first, held, failed = scenario.attempts
    assert [(c.passed, c.reason) for c in first.claims] == [(True, "said hi"), (False, "too long")]
    assert [c.reason for c in held.claims] == ["", ""]  # no reason, never "None"
    assert (failed.passed, failed.error, [c.passed for c in failed.claims]) == (
        False,
        "down",
        [None, None],
    )


def test_a_run_rate_and_its_evidence_must_agree_to_fail_ci(tmp_path):
    def attempts(scenario: str, verdict: Verdict | NoVerdict, count: int) -> list[Outcome]:
        return [outcome(scenario, verdict, attempt=n) for n in range(1, count + 1)]

    # a to e go from failing to passing; f, played k times, loses half its passes
    k = 20
    journal(tmp_path, "bot", "1", 6, *[outcome(s, FAILED) for s in "abcde"],
            *attempts("f", PASSED, k), k=k, started=at(4))  # fmt: skip
    journal(tmp_path, "bot", "1", 6, *[outcome(s, PASSED) for s in "abcde"],
            *attempts("f", PASSED, 10), *attempts("f", FAILED, k)[10:], k=k,
            started=at(5))  # fmt: skip
    # a falls from 20/20 to 12/20; b fails 20 times, then gets no verdict, so it leaves the rate
    journal(tmp_path, "mixed", "1", 2, *attempts("a", PASSED, k), *attempts("b", FAILED, k),
            k=k, started=at(4))  # fmt: skip
    journal(tmp_path, "mixed", "1", 2, *attempts("a", PASSED, 12), *attempts("a", FAILED, k)[12:],
            *attempts("b", NoVerdict("down"), k), k=k, started=at(5))  # fmt: skip
    runs = [
        msgspec.structs.replace(run, status=Finished(at(6)))
        for run in sorted(Runs(tmp_path), key=lambda run: (run.spec.agent, run.spec.started))
    ]
    assert Comparison(runs[0], runs[1]).check() == (
        "pass rate 80% → 60%: may be chance\nlower pass rate: f",
        False,
    )
    assert Comparison(runs[2], runs[3]).check() == (
        "pass rate 50% → 60%: may be chance\nlower pass rate: a",
        False,
    )


def evidence(*scenarios: tuple[tuple[int, int], tuple[int, int]]) -> Evidence:
    """Evidence from ((held, judged) before, (held, judged) after), one pair per scenario."""
    return Evidence(tuple((Tally(*before), Tally(*after)) for before, after in scenarios))


@pytest.mark.parametrize(
    ("scenarios", "chance"),
    [
        ([((0, 1), (1, 1))] * 3, 0.25),  # three from fail to pass, one attempt each: 1 in 4
        ([((3, 3), (0, 3))], 0.1),  # 3/3 to 0/3: 1 in 20 each way
        ([((2, 3), (2, 3))], 1.0),  # no change
        ([], 1.0),  # nothing in common
        ([((0, 19), (1, 1))], 0.05),  # unequal attempts between the runs: 1 in 20
        ([((0, 1), (1, 3)), ((0, 1), (2, 4))], 1.0),  # floats that should be equal count as equal
    ],
)
def test_evidence_counts_the_chance_of_a_change_by_hand(scenarios: list, chance: float):
    assert evidence(*scenarios).chance() == pytest.approx(chance)


@pytest.mark.parametrize(
    ("scenarios", "shows"),
    [
        ([((0, 19), (1, 1))], None),  # exactly 5%: not below it
        ([((0, 1), (1, 1))] * 6, "better"),  # the same change over six: 1 in 32
        ([((10, 40), (8, 10))], "better"),  # fewer attempts after, more of them passed
        ([((20, 20), (10, 20))] + [((20, 20), (20, 20))] * 5, "worse"),  # many attempts
        ([((1, 1), (0, 1))] + [((1, 1), (1, 1))] * 5, None),  # the same fall, one attempt
    ],
)
def test_evidence_shows_a_change_only_when_the_attempts_support_it(scenarios: list, shows):
    assert evidence(*scenarios).shows() == shows


def test_index_puts_every_run_on_one_time_axis_with_full_run_results(tmp_path):
    east = timezone(timedelta(hours=3))
    first = journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), started=at(5))
    first.write(Finished(at(6)))
    journal(
        tmp_path,
        "other",
        "1",
        1,
        outcome("a", FAILED),
        started=datetime(2026, 10, 7, 12, tzinfo=east),
    )
    journal(
        tmp_path,
        "bot",
        "2",
        1,
        outcome("a", PASSED),
        outcome("a", FAILED, attempt=2),
        k=2,
        started=datetime(2026, 10, 7, 10, tzinfo=UTC),
    )
    newest, other, oldest = Index(Runs(tmp_path)).page().rows
    assert [(r.run.agent, r.rate) for r in (newest, other, oldest)] == [
        ("bot", 0.5),
        ("other", 0),
        ("bot", 1),
    ]
    assert (newest.passed, newest.judged, newest.numbers.attempts) == (1, 2, 2)
    assert newest.scenarios[0].passed == 1
    assert oldest.report == f"./bot/{first.spec.id}/report.html"
    assert oldest.quality_note == "Model fingerprint not recorded"
    assert newest.quality_note == "Incomplete evaluation"


def test_no_runs_make_an_empty_workspace(tmp_path):
    assert Index(Runs(tmp_path)).page().rows == ()


def test_workspace_uses_each_runs_uncut_resource_samples(tmp_path):
    known = Turn(Message("hi"), Answer("ok", Usage(4, 6), steps_complete=True), 1)
    missing = Turn(Message("again"), Answer("ok"), 8)
    played = (
        Outcome("a", 1, Transcript((known, missing)), PASSED, "max_turns"),
        Outcome("a", 2, Transcript((known,)), FAILED, "max_turns"),
        Outcome("a", 3, Transcript(()), Failed("unavailable"), "agent_failure"),
    )
    journal(tmp_path, "bot", "1", 1, *played, k=3)
    (row,) = Index(Runs(tmp_path)).page().rows
    n = row.numbers
    assert n.attempts == 3
    assert n.seconds and (n.seconds.n, n.seconds.p50) == (3, 1)
    assert n.attempt_seconds and (n.attempt_seconds.n, n.attempt_seconds.p50) == (2, 5)
    assert n.tokens and (n.tokens.n, n.tokens.mean) == (2, 10)
    assert n.attempt_tokens and (n.attempt_tokens.n, n.attempt_tokens.mean) == (1, 10)
    assert n.tool_calls and (n.tool_calls.n, n.tool_calls.mean) == (1, 0)
    assert (row.passed, row.judged, row.errors) == (1, 3, 1)
    assert row.traced_answers == 2


def test_workspace_keeps_the_run_reports_quality_counts_and_exact_rate_buckets(tmp_path):
    busy = msgspec.structs.replace(outcome("c", NoVerdict("busy")), stop="agent_busy")
    journal(
        tmp_path,
        "bot",
        "1",
        5,
        outcome("a", PASSED),
        outcome("a", PASSED, attempt=2),
        outcome("b", Failed("down")),
        outcome("b", PASSED, attempt=2),
        busy,
        outcome("d", NoVerdict("judge down")),
        outcome("e", FAILED),
        k=2,
    )
    run = only(tmp_path)
    (row,) = Index([run]).page().rows
    page = Report(run).page()
    assert (row.stable, row.flaky, row.open) == (1, 1, 2)
    assert (row.agent_errors, row.busy, row.model_errors, row.errors) == (1, 1, 1, 3)
    assert row.results == tuple(
        ResultBucket(s.rate, len(s.scenarios), s.part) for s in page.results
    )
    assert row.results[-1] == ResultBucket(None, 2, 2 / 5)


def test_workspace_preserves_partial_token_reporting_and_the_cache_denominators(tmp_path):
    journal(tmp_path, "bot", "1", 1, talk("a", Usage(100, 20, 10, cache_read=60), Usage(50, 10, 0)))
    run = only(tmp_path)
    (row,) = Index([run]).page().rows
    view = Report(run).page().views.all
    assert row.parts == view.parts == Parts(30, 45, 10, 5)
    assert row.shares == view.shares == Shares(30 / 90, 45 / 90, 10 / 90, 5 / 90, 0.4)
    assert row.cached == 0.6
    assert (row.cache_answers, row.thinking_answers) == (1, 2)


def test_workspace_has_no_measurements_before_the_first_answer(tmp_path):
    journal(tmp_path, "bot", "1", 2)
    (row,) = Index(Runs(tmp_path)).page().rows
    assert row.results == (ResultBucket(None, 2, 1),)
    assert (row.parts, row.shares, row.cached, row.time) == (None, None, None, ())
    assert (row.stable, row.flaky, row.open, row.errors) == (0, 0, 0, 0)
    assert (row.cache_answers, row.thinking_answers, row.traced_answers) == (0, 0, 0)


@pytest.mark.parametrize(
    ("options", "field"),
    [
        ({"models": ("other", "fake")}, "User"),
        ({"models": ("fake", "other")}, "Judge"),
        ({"asks": "Ask a different question."}, "Scenario suite"),
        ({"claims": (Requirement("greets", True),)}, "Scenario suite"),
        ({"trust": 0.6666667}, "Trust"),
        ({"claim_threshold": 0.6666667}, "Claim threshold"),
        ({"limits": Limits(user_per_minute=10)}, "User requests/min"),
        ({"convy": "another"}, "Convy"),
        ({"k": 2}, "Repetitions"),
    ],
)
def test_workspace_identifies_the_setting_that_prevents_a_quality_delta(tmp_path, options, field):
    journal(tmp_path, "a", "v1", 1, started=at(5))
    journal(tmp_path, "b", "v2", 1, started=at(6), **options)
    page = Index(Runs(tmp_path)).page()
    new, old = page.rows
    before, after = page.setups[old.setup], page.setups[new.setup]
    assert [key for key in before if before[key] != after[key]] == [field]
    assert (old.scenarios[0].revision != new.scenarios[0].revision) == (field == "Scenario suite")


@pytest.mark.parametrize(
    ("missing", "note"),
    [
        ("convy", "Convy not recorded"),
        ("user", "User not recorded"),
        ("judge", "Judge not recorded"),
        ("", ""),
    ],
)
def test_reference_requires_a_recorded_evaluator_even_for_matching_setups(tmp_path, missing, note):
    journal(tmp_path, "bot", "v1", 1, outcome("a", PASSED))
    run = only(tmp_path)
    spec = msgspec.structs.replace(run.spec, files=Files(models="known"))
    if missing:
        spec = msgspec.structs.replace(spec, **{missing: ""})
    run = msgspec.structs.replace(run, spec=spec, status=Finished(at(6)))
    other = msgspec.structs.replace(run, outcomes=(outcome("a", FAILED),))
    first, second = Index((run, other)).page().rows
    assert (first.rate, second.rate) == (1, 0)
    assert first.setup == second.setup
    assert first.quality_note == second.quality_note == note


def test_workspace_matches_suites_across_order_and_distinguishes_added_scenarios(tmp_path):
    original = journal(tmp_path, "a", "v1", 2)
    run = Runs(tmp_path).read(original.folder())
    reordered = msgspec.structs.replace(run.spec, scenarios=run.spec.scenarios[::-1])
    reduced = msgspec.structs.replace(run.spec, scenarios=run.spec.scenarios[:1])
    first, second, third = (
        Index(
            (
                run,
                msgspec.structs.replace(run, spec=reordered),
                msgspec.structs.replace(run, spec=reduced),
            )
        )
        .page()
        .rows
    )
    assert first.setup == second.setup
    assert first.scenarios == second.scenarios[::-1]
    assert third.setup != first.setup
    assert third.scenarios == first.scenarios[:1]


@pytest.mark.parametrize("partial", ["unplayed", "unjudged", "unreadable", "interrupted"])
def test_workspace_keeps_partial_results_visible_without_a_quality_delta(tmp_path, partial):
    played = [outcome("a", PASSED)]
    if partial != "unplayed":
        played.append(outcome("b", NoVerdict("unavailable") if partial == "unjudged" else FAILED))
    written = journal(tmp_path, "bot", "1", 2, *played)
    written.write(Interrupted(at(6)) if partial == "interrupted" else Finished(at(6)))
    if partial == "unreadable":
        with (written.folder() / "attempts.jsonl").open("ab") as attempts:
            attempts.write(b"broken\n")
    (row,) = Index(Runs(tmp_path)).page().rows
    assert row.rate == (1 if partial in ("unplayed", "unjudged") else 0.5)
    assert row.quality_note == "Incomplete evaluation"
    assert len(row.scenarios) == 2


def data(html: str) -> object:
    start = html.index("const DATA = ") + len("const DATA = ")
    return json.loads(html[start : html.index(";\n", start)])


def test_pages_show_dialogues_as_data_only(tmp_path):
    hostile = "</script><img src=x onerror=alert(1)>"
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED, text=hostile), started=at(6))
    run = only(tmp_path)
    pages = (Report(run).html(), Index(Runs(tmp_path)).html())
    for html in pages:
        assert "</script><img" not in html
        assert "innerHTML" not in html
    page = data(pages[0])
    assert isinstance(page, dict)
    assert page["scenarios"][0]["attempts"][0]["turns"][0]["agent"] == hostile


def test_every_use_of_storage_is_guarded(tmp_path):
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), started=at(6))
    run = only(tmp_path)
    for html in (Report(run).html(), Index([run]).html()):
        lines = [line for line in html.splitlines() if "localStorage" in line]
        assert lines
        assert all("try {" in line for line in lines)


def test_a_written_page_stands_alone(tmp_path):
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), started=at(6))
    run = only(tmp_path)
    pages = (Report(run).html(), Index([run]).html())
    for html in pages:
        assert "/*include" not in html
        assert "function el(" in html
    assert "function dialogue(" in pages[0]
    assert "function dialogue(" not in pages[1]  # the index has no scenario window


def test_every_page_has_the_icon(tmp_path):
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), started=at(6))
    run = only(tmp_path)
    for html in (Report(run).html(), Index([run]).html()):
        assert '<link rel="icon" href="data:image/svg+xml,' in html


def test_attempts_below_trust_fail_and_are_counted(tmp_path):
    journal(
        tmp_path,
        "bot",
        "1",
        2,
        outcome("a", unsure(True, 0.9)),
        outcome("a", unsure(True, 0.5), attempt=2),
        outcome("b", unsure(False, 0.6)),
        outcome("b", unsure(True, 0.7), attempt=2),
        k=2,
        trust=0.8,
    )
    page = Report(only(tmp_path)).page()
    assert (page.metrics.passed, page.metrics.judged) == (1, 4)
    assert page.metrics.open == 0  # low confidence still gives a verdict
    assert page.run.trust == 0.8
    a, b = sorted(page.scenarios, key=lambda s: s.id)
    assert (a.result, b.result) == ("flaky", "failing")
    assert [x.passed for x in a.attempts] == [True, False]
    assert [(c.held, c.judged) for c in a.claims] == [(1, 2)]
    assert [(c.confidence, c.trusted) for c in a.attempts[1].claims] == [(0.5, False)]
    assert page.metrics.stable == 0  # a low-confidence attempt is not a pass


def test_trust_zero_counts_even_low_confidence(tmp_path):
    journal(tmp_path, "bot", "1", 1, outcome("a", unsure(False, 0.1)))
    page = Report(only(tmp_path)).page()
    assert (page.metrics.passed, page.metrics.judged) == (0, 1)
    assert page.scenarios[0].result == "failing"


def test_a_decision_without_confidence_is_trusted_and_shown_as_such(tmp_path):
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), trust=0.9)
    (scenario,) = Report(only(tmp_path)).page().scenarios
    (claim,) = scenario.attempts[0].claims
    assert (claim.passed, claim.confidence, claim.trusted) == (True, None, True)
    assert scenario.result == "passing"


def test_a_run_says_whether_its_judge_said_how_sure_it_was(tmp_path):
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), started=at(5))
    journal(tmp_path, "bot", "1", 1, outcome("a", unsure(True, 0.9)), started=at(6))
    without, with_confidence = both(tmp_path)
    assert Report(without).page().run.confident is False
    assert Report(with_confidence).page().run.confident is True


def test_multi_turn_report_keeps_mean_and_total_time_distinct(tmp_path):
    turns = tuple(Turn(Message("hi"), Answer("hello"), seconds) for seconds in (1.0, 2.0, 3.0, 6.0))
    played = Outcome("a", 1, Transcript(turns), PASSED, "max_turns")
    journal(tmp_path, "bot", "1", 1, played)
    page = Report(only(tmp_path)).page()
    # 1, 2, 3, 6: p50 halfway from 2 to 3, 2.5; p90 at
    # 2.7, 0.7 of the way from 3 to 6, 5.1; mean 12 / 4 = 3
    assert page.metrics.seconds == Spread(4, 1, 2.5, 5.1, 6, 3)
    assert page.scenarios[0].seconds == page.metrics.seconds
    assert page.scenarios[0].attempts[0].seconds == 12.0


def answers(scenario: str, *seconds: float, attempt: int = 1, tokens: int = 10) -> Outcome:
    """A passed attempt of `scenario` whose answers took `seconds`, each `tokens` in and out."""
    turns = tuple(Turn(Message("hi"), Answer("hello", Usage(tokens, tokens)), s) for s in seconds)
    return Outcome(scenario, attempt, Transcript(turns), PASSED, "max_turns")


def single(value: float) -> Spread:
    """The spread of one value: every statistic is the value."""
    return Spread(1, value, value, value, value, value)


@pytest.mark.parametrize(
    ("values", "spread"),
    [
        ([], None),
        ([None, None], None),
        ([7], single(7)),
        # two: p50 halfway, 2; p90 0.9 of the way, 2.8
        ([3.0, 1.0], Spread(2, 1, 2, 2.8, 3, 2)),
        # ties, even count: p50 at 1.5, between two 2s;
        # p90 at 2.7, 0.7 of the way from 2 to 8, 6.2; mean 14 / 4 = 3.5
        ([2, 2, 8, 2], Spread(4, 2, 2, 6.2, 8, 3.5)),
        # odd count: p50 the third, 3; p90 at 3.6, 0.6 of
        # the way from 4 to 5, 4.6
        ([5, 1, None, 4, 2, 3], Spread(5, 1, 3, 4.6, 5, 3)),
        # eleven values: p50 at 5, p90 at 9: the values there
        (list(range(1, 12)), Spread(11, 1, 6, 10, 11, 6)),
    ],
    ids=["none", "none reported", "one", "two", "ties", "odd", "on a value"],
)
def test_a_spread_holds_every_statistic_of_its_values(tmp_path, values, spread):
    journal(tmp_path, "bot", "1", 1)
    assert Summary(only(tmp_path)).spread(values) == spread


def test_a_spread_of_ints_is_of_floats(tmp_path):
    journal(tmp_path, "bot", "1", 1)
    spread = Summary(only(tmp_path)).spread([2, 2, 8, 2])
    assert msgspec.json.encode(spread) == (
        b'{"n":4,"min":2.0,"p50":2.0,"p90":6.2,"max":8.0,"mean":3.5}'
    )


def test_a_scenario_spreads_its_answers_time_and_its_attempts_tokens(tmp_path):
    played = (answers("a", 3.0, 1.0, tokens=5), answers("a", 2.0, attempt=2, tokens=50))
    journal(tmp_path, "bot", "1", 1, *played, k=2)
    (view,) = Report(only(tmp_path)).page().scenarios
    # answers 1, 2, 3: p90 at 1.8, 0.8 from 2 to 3, 2.8
    assert view.seconds == Spread(3, 1, 2, 2.8, 3, 2)
    # attempts of 2 * 2 * 5 = 20 and 2 * 50 = 100 tokens: p90 at 0.9, 92
    assert view.tokens == Spread(2, 20, 60, 92, 100, 60)


def test_a_scenario_without_reported_tokens_has_a_time_spread_only(tmp_path):
    silent = Turn(Message("hi"), Answer("hello"), 2.0)
    unreported = Outcome("a", 1, Transcript((silent,)), PASSED, "max_turns")
    journal(tmp_path, "bot", "1", 2, unreported, answers("b", 1.0))
    page = Report(only(tmp_path)).page()
    assert [(v.id, v.seconds, v.tokens) for v in page.scenarios] == [
        ("a", single(2.0), None),
        ("b", single(1.0), single(20)),
    ]
    assert page.metrics.tokens == single(20)


def test_counts_not_reported_stay_none_at_every_level(tmp_path):
    turn = Turn(Message("hi"), Answer("a", Usage(10, 5)), 1.0)
    journal(tmp_path, "bot", "1", 1, Outcome("a", 1, Transcript((turn,)), PASSED, "max_turns"))
    page = Report(only(tmp_path)).page()
    (attempt,) = page.scenarios[0].attempts
    assert (attempt.cache_read, attempt.cache_write, attempt.thinking_tokens) == (None, None, None)


def talk(scenario: str, *usages: Usage | NoUsage, attempt: int = 1) -> Outcome:
    """A passed attempt of `scenario` with an answer of 1 s per usage."""
    turns = tuple(Turn(Message("hi"), Answer("hello", usage), 1.0) for usage in usages)
    return Outcome(scenario, attempt, Transcript(turns), PASSED, "max_turns")


@pytest.mark.parametrize(
    ("attempts", "parts"),
    [
        (
            [
                [Usage(100, 40, 10, cache_read=60, cache_write=5), Usage(50, 20, 0, cache_read=30)],
                [Usage(30, 10, 4, cache_read=0)],
            ],
            # over 2 attempts: 90 from the cache; 180 - 90 new input, the 5 written included;
            # 70 - 14 output besides the 14 thinking
            Parts(45, 45, 28, 7),
        ),
        ([[NoUsage()]], None),
        ([[Usage(100, 40, 10)], [NoUsage()]], Parts(None, 100, 30, 10)),  # one attempt counts
        ([[Usage(0, 0)]], Parts(None, 0, 0, None)),
    ],
    ids=["every part", "none reported", "thinking without cache", "no tokens at all"],
)
def test_a_scenario_splits_its_mean_tokens_per_attempt_into_the_parts_reported(
    tmp_path, attempts, parts
):
    played = (talk("a", *usages, attempt=n) for n, usages in enumerate(attempts, 1))
    journal(tmp_path, "bot", "1", 1, *played, k=len(attempts))
    page = Report(only(tmp_path)).page()
    assert page.scenarios[0].parts == parts


def test_a_scenario_without_input_has_no_cache_share_of_it(tmp_path):
    journal(tmp_path, "bot", "1", 1, talk("a", Usage(0, 10, cache_read=0)))
    (view,) = Report(only(tmp_path)).page().scenarios
    assert view.shares == Shares(0, 0, 1, None, None)


def test_calls_of_no_time_have_no_share_of_it(tmp_path):
    steps = (call("ping", 0, 0), call("ping", 0, 0, Usage(0, 0)))
    turn = Turn(Message("hi"), Answer("hello", steps=steps), 1.0)
    journal(tmp_path, "bot", "1", 1, Outcome("a", 1, Transcript((turn,)), PASSED, "max_turns"))
    (ping,) = Report(only(tmp_path)).page().views.all.time
    assert (ping.total, ping.share) == (0, 0)
    (row,) = Index(Runs(tmp_path)).page().rows
    (observed,) = row.time
    assert (observed.calls, observed.token_calls, observed.tokens) == (2, 1, 0)


def test_a_scenario_gives_each_parts_share_and_the_caches_share_of_its_input(tmp_path):
    journal(tmp_path, "bot", "1", 1, talk("a", Usage(100, 10, cache_read=60)))
    (view,) = Report(only(tmp_path)).page().scenarios
    # 60 from the cache, 40 new input, 10 output: 110 in all; the cache is 60 of the 100 input
    assert view.shares == Shares(60 / 110, 40 / 110, 10 / 110, None, 0.6)


def test_the_agents_calls_are_summed_up_by_name(tmp_path):
    first = Answer(
        "hello",
        steps=(Thought("plan"), call("search", 0, 1, Usage(3, 4)), call("gpt", 1, 2, kind="model")),
    )
    second = Answer("hello", steps=(call("search", 0, 3, Usage(5, 6)),))
    other = Answer("hello", steps=(call("gpt", 0, 2, kind="model"), call("lookup", 0, 5)))
    played = (
        Outcome(
            "a",
            1,
            Transcript((Turn(Message("hi"), first, 2.0), Turn(Message("hi"), second, 3.0))),
            PASSED,
            "max_turns",
        ),
        Outcome("b", 1, Transcript((Turn(Message("hi"), other, 5.0),)), PASSED, "max_turns"),
    )
    journal(tmp_path, "bot", "1", 2, *played)
    view = Report(only(tmp_path)).page().views.all
    assert [(c.name, c.answers, c.calls, c.total) for c in view.time] == [
        ("lookup", 1, 1, 5),
        ("gpt", 2, 2, 4),
        ("search", 2, 2, 4),
    ]
    # three answers: what each call name adds to an answer on average, its total over three
    assert [c.average for c in view.time] == [5 / 3, 4 / 3, 4 / 3]
    gpt = view.time[1]
    assert gpt.places == (CallPlace("a", 1, 0, 2, 2, None), CallPlace("b", 1, 0, 0, 2, None))
    # only search reports tokens, 7 and 11: 18 over three answers; no answer reports its own
    assert [c.tokens for c in view.time] == [None, None, 6]
    assert view.time[2] == Category(
        "search",
        2,
        2,
        4,
        Spread(2, 1, 2, 2.8, 3, 2),
        (CallPlace("a", 1, 1, 0, 3, 11), CallPlace("a", 1, 0, 1, 1, 7)),
        4 / 3,
        6,
        4 / 13,  # of 5 + 4 + 4 s
    )
    assert view.parts is None
    (row,) = Index(Runs(tmp_path)).page().rows
    assert [c.token_calls for c in row.time] == [0, 0, 2]
    for compact, category in zip(row.time, view.time, strict=True):
        expected = msgspec.to_builtins(category)
        del expected["places"]
        expected["token_calls"] = compact.token_calls
        assert msgspec.to_builtins(compact) == expected


def test_calls_that_ran_together_each_count_their_own_time_and_nothing_else_is_timed(tmp_path):
    steps = (call("search", 0, 1), call("gpt", 0.5, 1, kind="model"), call("lookup", 2.5, 0.5))
    turn = Turn(Message("hi"), Answer("hello", Usage(10, 20), steps=steps), 4.0)
    journal(tmp_path, "bot", "1", 1, Outcome("a", 1, Transcript((turn,)), PASSED, "max_turns"))
    view = Report(only(tmp_path)).page().views.all
    # the answer's own 4 s are convy's clock and stay out: only the calls' 2.5 s count
    assert [(c.name, c.total, c.average) for c in view.time] == [
        ("gpt", 1, 1),
        ("search", 1, 1),
        ("lookup", 0.5, 0.5),
    ]
    assert [c.share for c in view.time] == [1 / 2.5, 1 / 2.5, 0.5 / 2.5]
    assert view.parts == Parts(None, 10, 20, None)
    assert view.shares == Shares(None, 1 / 3, 2 / 3, None, None)


def test_a_cut_takes_out_the_scenario_of_an_answer_past_the_far_out_fence(tmp_path):
    slow = Turn(Message("hi"), Answer("hello", Usage(30, 30), steps=(call("slow", 0, 100),)), 100.0)
    fast = Turn(Message("hi"), Answer("hello", Usage(30, 30)), 1.0)
    played = (
        answers("a", *[1.0] * 10),
        answers("b", *[2.0] * 10),
        Outcome("c", 1, Transcript((fast, slow)), PASSED, "max_turns"),
    )
    journal(tmp_path, "bot", "1", 3, *played)
    views = Report(only(tmp_path)).page().views
    assert views.all.out == ()
    # logs of the times: 11 at 0, 10 at ln 2; quartiles 0 and ln 2, so the fence is
    # e^(4 ln 2) = 16 s: c's 100 s is past it, and c leaves with its 1 s answer too
    assert views.cut.out == ("c",)
    assert views.cut.seconds.answers == 20
    assert views.cut.seconds.spread is not None and views.cut.seconds.spread.max == 2
    assert views.cut.scenarios[2] == ScenarioNumbers(None, None, None, None, 0, None)
    assert (views.all.attempts, views.cut.attempts) == (3, 2)
    assert views.cut.attempt_seconds == Spread(2, 10, 15, 19, 20, 15)
    assert views.cut.attempt_tokens == Spread(2, 200, 200, 200, 200, 200)
    # c leaves every other number too: its call and its larger answers
    assert [c.name for c in views.all.time] == ["slow"]
    assert views.cut.time == ()
    assert views.all.parts is not None and views.all.parts.input == (20 * 10 + 2 * 30) / 22
    assert views.cut.parts == Parts(None, 10, 10, None)


def test_a_cut_takes_nothing_when_nothing_is_far_out(tmp_path):
    journal(tmp_path, "bot", "1", 1, answers("a", *(float(n) for n in range(1, 11))))
    assert Report(only(tmp_path)).page().views.cut.out == ()


def test_a_scenario_is_cut_by_its_tokens_out_of_its_time_too(tmp_path):
    played = (
        answers("a", *[1.0] * 10, tokens=10),
        answers("b", *[1.0] * 10, tokens=20),
        answers("c", 1.0, tokens=5000),  # 10000 tokens; the fence is at 40 · 2³ = 320
    )
    journal(tmp_path, "bot", "1", 3, *played)
    views = Report(only(tmp_path)).page().views
    assert views.cut.out == ("c",)
    assert views.cut.seconds.answers == 20


@pytest.mark.parametrize(
    "played",
    [
        (answers("a", *[1.0] * 7, 100.0),),  # the one scenario: cutting it would leave nothing
        (answers("a", 1.0, 1.0), answers("b", 100.0)),  # three answers: too few for quartiles
        (answers("a", *[1.0] * 7), answers("b", 100.0)),  # quartiles equal: no spread to judge
    ],
    ids=["only scenario", "few answers", "alike answers"],
)
def test_a_cut_takes_nothing_it_cannot_judge(tmp_path, played):
    journal(tmp_path, "bot", "1", len(played), *played)
    assert Report(only(tmp_path)).page().views.cut.out == ()


def test_the_scenarios_are_grouped_by_pass_rate_without_a_verdict_last(tmp_path):
    journal(
        tmp_path,
        "bot",
        "1",
        4,
        outcome("a", PASSED),
        outcome("a", FAILED, attempt=2),
        outcome("b", FAILED),
        outcome("c", PASSED),
        outcome("c", PASSED, attempt=2),
        k=2,
    )
    assert Report(only(tmp_path)).page().results == (
        Share(0, "failing", ("b",), 1 / 4),
        Share(0.5, "flaky", ("a",), 1 / 4),
        Share(1, "passing", ("c",), 1 / 4),
        Share(None, "none", ("d",), 1 / 4),
    )


def test_the_views_and_parts_reach_the_pages(tmp_path):
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), started=at(6))
    run = only(tmp_path)
    page = data(Report(run).html())
    assert isinstance(page, dict)
    assert set(page["views"]) == {"all", "cut"}
    assert page["results"] == [{"rate": 1.0, "result": "passing", "scenarios": ["a"], "part": 1.0}]
    parts = {"cached": None, "input": 10.0, "output": 10.0, "thinking": None}
    assert page["views"]["all"]["parts"] == parts


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_scripts_of_every_page_parse(tmp_path):
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), started=at(6))
    run = only(tmp_path)
    pages = (Report(run).html(), Index([run]).html())
    scripts = [body for html in pages for body in re.findall(r"<script>(.*?)</script>", html, re.S)]
    assert len(scripts) == 4
    for number, body in enumerate(scripts):
        file = tmp_path / f"script{number}.js"
        file.write_text(body, encoding="utf-8")
        done = subprocess.run(["node", "--check", str(file)], check=False, capture_output=True)
        assert done.returncode == 0, done.stderr.decode()


@pytest.mark.parametrize("threshold", [0.5, 1])
def test_attempt_details_keep_raw_decisions_and_explain_both_failure_causes(tmp_path, threshold):
    journal(
        tmp_path,
        "bot",
        "1",
        1,
        outcome("a", Verdict((Claim(True, Reason("said hi"), Confidence(0.5)), Claim(True)))),
        claims=(Requirement("greets", True), Requirement("brief")),
        trust=0.8,
        claim_threshold=threshold,
    )
    page = Report(only(tmp_path)).page()
    (scenario,) = page.scenarios
    (attempt,) = scenario.attempts
    assert not attempt.passed
    assert attempt.completion is not None
    assert (attempt.completion.held, attempt.completion.total, attempt.completion.fraction) == (
        1,
        2,
        0.5,
    )
    assert "Required claims failed: 1." in attempt.completion.failures
    assert len(attempt.completion.failures) == (2 if threshold == 1 else 1)
    first, second = attempt.claims
    assert (first.passed, first.held, first.required, first.trusted, first.reason) == (
        True,
        False,
        True,
        False,
        "said hi",
    )
    assert (second.passed, second.held, second.required) == (True, True, False)
    assert [(c.required, c.held, c.judged) for c in scenario.claims] == [
        (True, 0, 1),
        (False, 1, 1),
    ]
    assert (page.metrics.passed, page.metrics.judged) == (0, 1)
    assert page.run.claim_threshold == threshold


def test_threshold_zero_accepts_valid_verdicts_but_not_errors(tmp_path):
    journal(
        tmp_path,
        "bot",
        "1",
        1,
        outcome("a", FAILED),
        outcome("a", Failed("agent down"), attempt=2),
        outcome("a", NoVerdict("judge down"), attempt=3),
        k=3,
        claim_threshold=0,
    )
    page = Report(only(tmp_path)).page()
    attempts = page.scenarios[0].attempts
    assert [a.passed for a in attempts] == [True, False, None]
    assert attempts[0].completion is not None
    assert attempts[0].completion.fraction == 0
    assert [a.completion for a in attempts[1:]] == [None, None]
    assert (page.metrics.passed, page.metrics.judged, page.metrics.open) == (1, 2, 1)


def test_changing_only_a_required_flag_changes_the_scenario_for_comparison(tmp_path):
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), started=at(5))
    journal(
        tmp_path,
        "bot",
        "1",
        1,
        outcome("a", PASSED),
        started=at(6),
        claims=(Requirement("greets", True),),
    )
    before, after = (msgspec.structs.replace(r, status=Finished(at(7))) for r in both(tmp_path))
    assert Comparison(before, after).check() == ("no scenario can be compared", True)


@pytest.mark.parametrize("setting", ["trust", "claim_threshold"])
def test_setup_changes_preserve_precision_that_can_change_acceptance(tmp_path, setting):
    verdict = Verdict(
        (Claim(True, confidence=Confidence(2 / 3)), Claim(True), Claim(setting == "trust"))
    )
    for hour, value in ((5, 0.6666666), (6, 0.6666667)):
        journal(
            tmp_path,
            "bot",
            "1",
            1,
            outcome("a", verdict),
            started=at(hour),
            claims=tuple(Requirement(str(i)) for i in range(3)),
            trust=value if setting == "trust" else 0.0,
            claim_threshold=value if setting == "claim_threshold" else 1.0,
        )
    rows = Index(Runs(tmp_path)).page().rows
    assert [row.rate for row in rows] == [0, 1]
    assert [getattr(row.run, setting) for row in rows] == [0.6666667, 0.6666666]
    assert Comparison(*both(tmp_path)).check() == (
        "Quality not compared: different trust or claim threshold.",
        True,
    )


def test_run_and_scenario_medians_use_answers_and_task_totals_as_distinct_samples(tmp_path):
    played = (
        answers("a", 1, 1, tokens=1),
        answers("a", 1, attempt=2, tokens=1),
        answers("a", 10, attempt=3, tokens=50),
        answers("b", 2, 2, tokens=5),
    )
    journal(tmp_path, "bot", "1", 2, *played, k=3)
    view = Report(only(tmp_path)).page().views.all
    first, second = view.scenarios
    assert view.attempts == 4  # the two unrecorded attempts do not enter the sample
    assert view.seconds.spread is not None and view.tokens.spread is not None
    assert (view.seconds.spread.n, view.seconds.spread.mean, view.seconds.spread.p50) == (
        6,
        17 / 6,
        1.5,
    )
    assert (view.tokens.spread.n, view.tokens.spread.mean, view.tokens.spread.p50) == (6, 21, 6)
    assert view.attempt_seconds is not None and view.attempt_tokens is not None
    assert (view.attempt_seconds.n, view.attempt_seconds.mean, view.attempt_seconds.p50) == (
        4,
        17 / 4,
        3,
    )
    assert (view.attempt_tokens.n, view.attempt_tokens.mean, view.attempt_tokens.p50) == (
        4,
        31.5,
        12,
    )
    assert first.attempts == 3
    assert first.seconds is not None and first.tokens is not None
    assert (first.seconds.mean, first.seconds.p50) == (13 / 4, 1)
    assert (first.tokens.mean, first.tokens.p50) == (26.5, 2)
    assert first.attempt_seconds is not None and first.attempt_tokens is not None
    assert (first.attempt_seconds.mean, first.attempt_seconds.p50) == (13 / 3, 2)
    assert (first.attempt_tokens.mean, first.attempt_tokens.p50) == (106 / 3, 4)
    assert second.attempts == 1
    assert (second.attempt_seconds, second.attempt_tokens) == (single(4), single(20))


def test_partial_token_tasks_are_unknown_but_known_answers_and_zero_tasks_still_count(tmp_path):
    journal(
        tmp_path,
        "bot",
        "1",
        1,
        talk("a", Usage(20, 10), NoUsage()),
        talk("a", Usage(0, 0), attempt=2),
        started=at(5),
        k=2,
    )
    before = only(tmp_path)
    page = Report(before).page()
    partial, zero = page.scenarios[0].attempts
    assert (partial.input, partial.output, partial.tokens) == (None, None, None)
    assert (zero.input, zero.output, zero.tokens) == (0, 0, 0)
    view = page.views.all
    assert (view.attempts, view.seconds.answers, view.tokens.answers) == (2, 3, 2)
    assert view.tokens.spread == Spread(2, 0, 15, 27, 30, 15)
    assert view.attempt_tokens == single(0)
    assert page.scenarios[0].tokens == page.metrics.tokens == single(0)
    assert page.scenarios[0].parts == Parts(None, 0, 0, None)
    assert view.scenarios[0].attempt_tokens == single(0)


def test_resource_samples_include_recorded_errors_without_inventing_empty_task_measurements(
    tmp_path,
):
    failure = Outcome(
        "a",
        1,
        Transcript((Turn(Message("hi"), Answer("error"), 4),)),
        Failed("agent failed"),
        "agent_failure",
    )
    unjudged = Outcome(
        "b",
        1,
        Transcript((Turn(Message("hi"), Answer("hello", Usage(10, 5)), 2),)),
        NoVerdict("judge failed"),
        "model_failure",
    )
    empty = Outcome("b", 2, Transcript(), NoVerdict("busy"), "agent_busy")
    written = journal(tmp_path, "bot", "1", 2, failure, unjudged, empty, k=3)
    written.write(Interrupted(at(5)))
    page = Report(only(tmp_path)).page()
    view = page.views.all
    assert (view.attempts, view.seconds.answers, view.tokens.answers) == (3, 2, 1)
    assert view.attempt_seconds == Spread(2, 2, 3, 3.8, 4, 3)
    assert view.attempt_tokens == single(15)
    by_id = dict(zip((s.id for s in page.scenarios), view.scenarios, strict=True))
    assert by_id["a"].attempts == 1
    assert (by_id["a"].attempt_seconds, by_id["a"].attempt_tokens) == (single(4), None)
    assert by_id["b"].attempts == 2
    assert (by_id["b"].attempt_seconds, by_id["b"].attempt_tokens) == (single(2), single(15))


def test_tool_calls_count_each_invocation_across_the_task(tmp_path):
    tool = call("same-name", 0, 0)
    model = call("same-name", 0, 1, Usage(3, 4), kind="model")
    failed = msgspec.structs.replace(tool, received=Reported("error: unavailable"))
    first = Answer("retrying", steps=(Thought("plan"), model, failed, tool), steps_complete=True)
    second = Answer("done", steps=(tool, model), steps_complete=True)
    played = Outcome(
        "a",
        1,
        Transcript((Turn(Message("hi"), first, 1), Turn(Message("next"), second, 1))),
        PASSED,
        "max_turns",
    )
    journal(tmp_path, "bot", "1", 1, played)
    page = Report(only(tmp_path)).page()
    (attempt,) = page.scenarios[0].attempts
    assert [turn.tool_calls for turn in attempt.turns] == [2, 1]
    assert (attempt.turns[0].thoughts, attempt.turns[0].calls) == (1, 3)
    assert [step.kind for step in attempt.turns[0].steps if isinstance(step, CallView)] == [
        "model",
        "tool",
        "tool",
    ]
    assert attempt.tool_calls == 3
    assert page.views.all.tool_calls == page.views.all.scenarios[0].tool_calls == single(3)


@pytest.mark.parametrize(
    ("answers", "counts", "total"),
    [
        ((Answer("zero", steps_complete=True),), [0], 0),
        (
            (
                Answer(
                    "model only",
                    steps=(Thought("plan"), call("search", 0, 1, kind="model")),
                    steps_complete=True,
                ),
            ),
            [0],
            0,
        ),
        ((Answer("missing"),), [None], None),
        ((Answer("partial", steps=(call("search", 0, 1),)),), [None], None),
        (
            (
                Answer("complete", steps=(call("search", 0, 1),), steps_complete=True),
                Answer("missing"),
            ),
            [1, None],
            None,
        ),
        ((), [], None),
    ],
    ids=["known-zero", "model-and-thought", "missing", "partial", "mixed", "no-answers"],
)
def test_tool_calls_require_every_answers_complete_trace(tmp_path, answers, counts, total):
    turns = tuple(Turn(Message("hi"), answer, 1) for answer in answers)
    journal(tmp_path, "bot", "1", 1, Outcome("a", 1, Transcript(turns), PASSED, "max_turns"))
    page = Report(only(tmp_path)).page()
    (attempt,) = page.scenarios[0].attempts
    assert [turn.tool_calls for turn in attempt.turns] == counts
    assert attempt.tool_calls == total
    spread = None if total is None else single(total)
    assert page.views.all.tool_calls == page.views.all.scenarios[0].tool_calls == spread


def test_tool_call_samples_include_failed_and_unjudged_recorded_tasks(tmp_path):
    played = []
    for attempt, (count, verdict) in enumerate(
        [(0, PASSED), (1, FAILED), (3, Failed("close failed")), (8, NoVerdict("judge down"))], 1
    ):
        answer = Answer("done", steps=(call("search", 0, 1),) * count, steps_complete=True)
        base = outcome("a", verdict, attempt=attempt)
        played.append(
            msgspec.structs.replace(base, transcript=Transcript((Turn(Message("hi"), answer, 1),)))
        )
    played.extend(
        (
            outcome("a", PASSED, attempt=5),
            Outcome("a", 6, Transcript(), NoVerdict("busy"), "agent_busy"),
        )
    )
    written = journal(tmp_path, "bot", "1", 1, *played, k=8)
    written.write(Interrupted(at(5)))
    page = Report(only(tmp_path)).page()
    view = page.views.all
    assert view.attempts == view.scenarios[0].attempts == 6
    assert view.tool_calls == view.scenarios[0].tool_calls == Spread(4, 0, 2, 6.5, 8, 3)
    assert [a.tool_calls for a in page.scenarios[0].attempts] == [0, 1, 3, 8, None, None]


def test_tool_call_statistics_follow_the_same_scenario_outlier_cut(tmp_path):
    tool = call("search", 0, 1)
    played = []
    for scenario, seconds, count in [("a", 1, 1), ("b", 2, 2), ("c", 100, 9)]:
        turns = tuple(
            Turn(Message("hi"), Answer("done", steps=(tool,) * count, steps_complete=True), seconds)
            for _ in range(1 if scenario == "c" else 10)
        )
        played.append(Outcome(scenario, 1, Transcript(turns), PASSED, "max_turns"))
    journal(tmp_path, "bot", "1", 3, *played)
    page = Report(only(tmp_path)).page()
    views = page.views
    assert (views.all.attempts, views.cut.attempts, views.cut.out) == (3, 2, ("c",))
    assert views.all.tool_calls == Spread(3, 9, 10, 18, 20, 13)
    assert views.cut.tool_calls == Spread(2, 10, 15, 19, 20, 15)
    by_id = dict(zip((s.id for s in page.scenarios), views.cut.scenarios, strict=True))
    assert by_id["a"].tool_calls == single(10)
    assert by_id["b"].tool_calls == single(20)
    assert (by_id["c"].tool_calls, by_id["c"].attempts) == (None, 0)


@pytest.mark.parametrize(("failure", "count"), [("open", None), ("turn", None), ("close", 1)])
async def test_tool_call_measurement_preserves_agent_failure_semantics(tmp_path, failure, count):
    complete = Answer("hello", steps=(call("search", 0, 1),), steps_complete=True)

    class Broken:
        @asynccontextmanager
        async def conversation(self):
            if failure == "open":
                raise RuntimeError("open failed")
            async with FakeAgent(complete, RuntimeError("turn failed")).conversation() as talk:
                yield talk
            if failure == "close":
                raise RuntimeError("close failed")

    scenario = Scenario("a", 2 if failure == "turn" else 1, "Say hi.", (Requirement("greets"),))
    judge = FakeJudge((Claim(True),))
    played = await scenario.outcome(
        Broken(), Models(FakeModel("hi"), judge), 1, Places(1, Patience())
    )
    assert played.stop == "agent_failure"
    assert judge.calls == []
    journal(tmp_path, "bot", "1", 1, played)
    page = Report(only(tmp_path)).page()
    (attempt,) = page.scenarios[0].attempts
    assert attempt.tool_calls == count
    assert page.views.all.attempts == 1
    assert page.views.all.tool_calls == (None if count is None else single(count))
