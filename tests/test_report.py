import json
import re
import secrets
import shutil
import subprocess
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import msgspec
import pytest

from convy.agent import Answer, Call, Message, NotReported, NoUsage, Reported, Thought, Usage
from convy.bench import CONVY, Finished, Interrupted, Limits, RunJournal, RunSpec
from convy.dialog import (
    Claim,
    Confidence,
    Failed,
    Grade,
    Graded,
    NoReason,
    NoVerdict,
    Reason,
    Transcript,
    Turn,
    Verdict,
)
from convy.report import (
    CallView,
    Comparison,
    Evidence,
    Index,
    Report,
    Run,
    Runs,
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
    claims: tuple[str | Graded, ...] = ("greets",),
    trust: float = 0.0,
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
        convy=convy,
        limits=limits,
    )
    written = RunJournal(directory, spec)
    written.create()
    for item in outcomes:
        written.record(item)
    return written


def test_a_run_of_format_2_reads_its_reasons(tmp_path):
    """Format 2 kept a claim's reason as a string; it is read as a reason, or none if empty."""
    written = journal(tmp_path, "bot", "1", 2)
    folder = written.folder()
    data = json.loads((folder / "run.json").read_text())
    assert data["format"] == 6
    older = {**data, "format": 2, "spec": {**data["spec"], "parallel": 4}}
    (folder / "run.json").write_text(json.dumps(older))
    line = {
        "scenario": "a",
        "attempt": 1,
        "transcript": {"turns": []},
        "verdict": {"type": "verdict", "claims": [{"pass": True, "reason": "said hi"}]},
        "stop": "max_turns",
    }
    empty = {
        **line,
        "scenario": "b",
        "verdict": {"type": "verdict", "claims": [{"pass": True, "reason": ""}]},
    }
    (folder / "attempts.jsonl").write_text(json.dumps(line) + "\n" + json.dumps(empty) + "\n")
    (run,) = Runs(tmp_path)
    assert [outcome.verdict for outcome in run.outcomes] == [
        Verdict((Claim(True, Reason("said hi")),)),
        Verdict((Claim(True, NoReason()),)),
    ]
    assert run.unreadable == 0


@pytest.mark.parametrize(
    ("answer", "steps"),
    [
        ({"text": "hi", "thinking": {"type": "thinking", "text": "plan"}}, (Thought("plan"),)),
        ({"text": "hi", "thinking": {"type": "no_thinking"}}, ()),
        ({"text": "hi"}, ()),
    ],
    ids=["thinking", "no thinking", "before thinking"],
)
def test_an_older_line_reads_its_thinking_as_a_step(
    tmp_path, answer: dict, steps: tuple[Thought, ...]
):
    folder = journal(tmp_path, "bot", "1", 1).folder()
    data = json.loads((folder / "run.json").read_text())
    (folder / "run.json").write_text(json.dumps({**data, "format": 4}))
    turn = {"message": {"text": "hi"}, "answer": answer, "seconds": 1.0}
    line = {
        "scenario": "a",
        "attempt": 1,
        "transcript": {"turns": [turn]},
        "verdict": {"type": "verdict", "claims": [{"pass": True}]},
        "stop": "max_turns",
    }
    (folder / "attempts.jsonl").write_text(json.dumps(line) + "\n")
    (run,) = Runs(tmp_path)
    assert run.outcomes[0].transcript.turns[0].answer == Answer("hi", steps=steps)
    assert run.unreadable == 0


@pytest.mark.parametrize("format", [3, 5])
@pytest.mark.parametrize(("thinking", "read"), [(0, NotReported()), (20, 20)])
def test_an_older_line_reads_a_thinking_count_of_0_as_not_reported_and_keeps_others(
    tmp_path, format: int, thinking: int, read: int | NotReported
):
    """Formats 3 to 5 wrote 0 for a thinking count the agent did not give."""
    usage = {"type": "usage", "input": 10, "output": 30, "thinking": thinking}
    call = {"type": "call", "name": "search", "started": "2026-10-06T00:00:00Z", "seconds": 1.0}
    answer = {"text": "hi", "usage": usage, "steps": [{**call, "usage": usage}]}
    run = older_run(tmp_path, format, answer, {"parallel": 4} if format < 4 else None)
    spent = Usage(10, 30, read)
    steps = (Call(name="search", started=DAY, seconds=1.0, usage=spent),)
    assert run.outcomes[0].transcript.turns[0].answer == Answer("hi", spent, steps)
    assert run.unreadable == 0


def test_an_older_line_with_thinking_text_reads_its_thinking_count_of_0_as_not_reported(tmp_path):
    """Before format 5 the thinking was a field of its own; its count still needs converting."""
    usage = {"type": "usage", "input": 10, "output": 30, "thinking": 0}
    thinking = {"type": "thinking", "text": "plan"}
    run = older_run(tmp_path, 4, {"text": "hi", "usage": usage, "thinking": thinking})
    answer = Answer("hi", Usage(10, 30), (Thought("plan"),))
    assert run.outcomes[0].transcript.turns[0].answer == answer


def test_a_format_2_line_reads_its_thinking_count_as_not_reported(tmp_path):
    usage = {"type": "usage", "input": 10, "output": 30}  # format 2 had no thinking count
    run = older_run(tmp_path, 2, {"text": "hi", "usage": usage}, {"parallel": 4})
    assert run.outcomes[0].transcript.turns[0].answer == Answer("hi", Usage(10, 30))


def older_run(directory: Path, format: int, answer: dict, spec: dict | None = None) -> Run:
    """A run of `format` whose one line holds one turn with `answer`, read back."""
    folder = journal(directory, "bot", "1", 1).folder()
    data = json.loads((folder / "run.json").read_text())
    older = {**data, "format": format, "spec": {**data["spec"], **(spec or {})}}
    (folder / "run.json").write_text(json.dumps(older))
    turn = {"message": {"text": "hi"}, "answer": answer, "seconds": 1.0}
    line = {
        "scenario": "a",
        "attempt": 1,
        "transcript": {"turns": [turn]},
        "verdict": {"type": "verdict", "claims": [{"pass": True}]},
        "stop": "max_turns",
    }
    (folder / "attempts.jsonl").write_text(json.dumps(line) + "\n")
    (run,) = Runs(directory)
    return run


@pytest.mark.parametrize("format", [2, 3])
def test_an_older_run_reads_its_one_limit_as_each_participant_limit(tmp_path, format: int):
    folder = journal(tmp_path, "bot", "1", 1).folder()
    data = json.loads((folder / "run.json").read_text())
    del data["spec"]["limits"]
    older = {**data, "format": format, "spec": {**data["spec"], "parallel": 2}}
    (folder / "run.json").write_text(json.dumps(older))
    (run,) = Runs(tmp_path)
    assert run.spec.limits == Limits(agent=2, user=2, judge=2)
    assert run.format == format


def test_runs_read_back_what_journals_wrote(tmp_path):
    steps = (Thought("plan"), Call(name="search", started=DAY, seconds=1.5, received=Reported("")))
    turn = Turn(Message("hi"), Answer("hello", Usage(10, 5, cache_read=4), steps), 2.0)
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
    assert metrics.stable == 1  # only a passed both
    assert (metrics.seconds, metrics.slowest) == (2.0, 2.0)
    assert (metrics.input, metrics.output, metrics.tokens) == (30, 30, 60)
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
    assert (a.rate, a.tokens) == (1, 30)  # 20 then 40 tokens: their mean
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
    assert (attempt.thinking_tokens, page.metrics.thinking_tokens) == (None, None)
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
    assert (attempt.output, attempt.thinking_tokens) == (50, 20)  # thinking is part of output
    assert page.metrics.thinking_tokens == 20


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
    assert (page.scenarios[0].cache_read, page.scenarios[0].cache_write) == (80, 20)
    assert (page.metrics.cache_read, page.metrics.cache_write) == (80, 20)
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


def call(name: str, at: float, seconds: float, usage: Usage | NoUsage = NO_USAGE) -> Call:
    """A call `at` seconds after the agent's first, by the agent's clock."""
    return Call(
        name=name, started=AGENT_CLOCK + timedelta(seconds=at), seconds=seconds, usage=usage
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
) -> CallView:
    return CallView(
        name=name,
        seconds=seconds,
        left=left,
        width=width,
        tokens=tokens,
        sent=sent,
        received=received,
    )


def test_calls_sit_on_their_own_time_line(tmp_path):
    turn = shown(tmp_path, call("search", 0, 1), call("gpt", 2, 2))
    assert turn.steps == (bar("search", 1, 0, 0.25), bar("gpt", 2, 0.5, 0.5))


def test_overlapping_calls_share_the_time_line(tmp_path):
    turn = shown(tmp_path, call("search", 0, 4), call("embed", 1, 1))
    assert turn.steps == (bar("search", 4, 0, 1), bar("embed", 1, 0.25, 0.25))


def test_an_instant_call_has_a_time_line(tmp_path):
    assert shown(tmp_path, call("cache", 0, 0)).steps == (bar("cache", 0, 0, 0),)


def test_a_huge_call_does_not_break_the_report(tmp_path):
    """A time in ms given as seconds: no `datetime` is made from it, so nothing overflows."""
    assert shown(tmp_path, call("search", 0, 1.7e12)).steps == (bar("search", 1.7e12, 0, 1),)


def test_a_call_shows_what_it_reported_and_what_it_did_not(tmp_path):
    searched = Call(
        name="search",
        started=AGENT_CLOCK,
        seconds=1,
        sent=Reported("refund rules"),
        received=Reported(""),
    )
    turn = shown(tmp_path, searched, call("gpt", 1, 1, Usage(3, 4, 2)))
    assert turn.steps == (
        bar("search", 1, 0, 0.5, sent="refund rules", received=""),
        bar("gpt", 1, 0.5, 0.5, tokens=7),
    )


def test_steps_keep_their_order_and_counts(tmp_path):
    turn = shown(tmp_path, Thought("look it up"), call("search", 0, 1), Thought("found it"))
    assert turn.steps == (
        ThoughtView("look it up"),
        bar("search", 1, 0, 1),
        ThoughtView("found it"),
    )
    assert (turn.thoughts, turn.calls) == (2, 1)


def test_an_answer_without_steps_counts_none(tmp_path):
    turn = shown(tmp_path)
    assert (turn.steps, turn.thoughts, turn.calls) == ((), 0, 0)


def test_calls_in_other_time_zones_share_the_time_line(tmp_path):
    moment = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
    utc = Call(name="a", started=moment, seconds=1)
    plus3 = Call(name="b", started=moment.astimezone(timezone(timedelta(hours=3))), seconds=1)
    assert shown(tmp_path, utc, plus3).steps == (bar("a", 1, 0, 1), bar("b", 1, 0, 1))


def test_a_claim_is_summed_up_over_the_attempts_the_judge_decided(tmp_path):
    decided = Verdict((Claim(True, Reason("said hi")), Claim(False, Reason("too long"))))
    held = Verdict((Claim(True), Claim(True)))
    played = (outcome("a", v, attempt=n) for n, v in enumerate((decided, held, Failed("down")), 1))
    journal(tmp_path, "bot", "1", 1, *played, k=3, claims=("greets", "is brief"))
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


STEPS = Graded("covers every step", ("none", "partial", "full"), "partial")


def graded(*grades: str) -> list[Outcome]:
    """An attempt per grade of `STEPS`, numbered from 1."""
    return [
        outcome("a", Verdict((Claim(STEPS.passes(g), grade=Grade(g)),)), attempt=n)
        for n, g in enumerate(grades, 1)
    ]


def test_a_graded_claim_counts_its_grades_and_its_typical_one_is_the_lower_median(tmp_path):
    journal(
        tmp_path, "bot", "1", 1, *graded("full", "none", "full", "partial"), k=4, claims=(STEPS,)
    )
    (scenario,) = Report(only(tmp_path)).page().scenarios
    (claim,) = scenario.claims
    assert (claim.text, claim.held, claim.judged) == ("covers every step", 3, 4)
    assert claim.grades == (("none", 1), ("partial", 1), ("full", 2))
    assert claim.typical == "partial"
    assert [a.claims[0].grade for a in scenario.attempts] == ["full", "none", "full", "partial"]


def test_a_plain_claim_has_no_grades(tmp_path):
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED))
    (scenario,) = Report(only(tmp_path)).page().scenarios
    assert (scenario.claims[0].grades, scenario.claims[0].typical) == ((), None)
    assert scenario.attempts[0].claims[0].grade is None


def test_a_comparison_sees_a_graded_claim_get_worse_with_the_same_pass_rate(tmp_path):
    for day, grades in ((5, ("full", "full")), (6, ("partial", "partial"))):
        journal(tmp_path, "bot", "1", 1, *graded(*grades), k=2, claims=(STEPS,), started=at(day))
    (row,) = Comparison(*both(tmp_path)).page().rows
    assert row.group == "same"
    assert [(c.change, c.was, c.now, c.moved) for c in row.claims] == [
        ("worse", "full", "partial", "worse")
    ]


def test_a_typical_grade_that_fell_is_worse_even_when_the_pass_rate_rose(tmp_path):
    for day, grades in ((5, ("none", "full", "full")), (6, ("partial", "partial", "partial"))):
        journal(tmp_path, "bot", "1", 1, *graded(*grades), k=3, claims=(STEPS,), started=at(day))
    (row,) = Comparison(*both(tmp_path)).page().rows
    assert [(c.change, c.was, c.now, c.moved) for c in row.claims] == [
        ("better", "full", "partial", "worse")
    ]


def test_a_comparison_groups_scenarios_by_what_changed(tmp_path):
    journal(
        tmp_path,
        "bot",
        "1",
        5,
        outcome("a", PASSED),
        outcome("b", FAILED),
        outcome("c", PASSED),
        outcome("d", NoVerdict("down")),
        outcome("e", PASSED),
        started=at(5),
    )
    journal(
        tmp_path,
        "bot",
        "2",
        4,
        outcome("a", FAILED),
        outcome("b", PASSED),
        outcome("c", PASSED),
        outcome("d", PASSED),
        started=at(6),
    )
    page = Comparison(*both(tmp_path)).page()
    assert [(r.id, r.group, r.why) for r in page.rows] == [
        ("a", "worse", ""),
        ("b", "better", ""),
        ("c", "same", ""),
        ("d", "apart", "no verdict in one of the runs"),
        ("e", "apart", "only in the before run"),
    ]
    worse = page.rows[0]
    assert worse.before is not None and worse.after is not None
    assert (worse.before.result, worse.after.result) == ("passing", "failing")
    assert [(c.before, c.after, c.change) for c in worse.claims] == [
        ("passing", "failing", "worse")
    ]


def test_an_edited_scenario_is_not_compared(tmp_path):
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), started=at(5), asks="Say hi.")
    journal(tmp_path, "bot", "1", 1, outcome("a", FAILED), started=at(6), asks="Say hello.")
    (row,) = Comparison(*both(tmp_path)).page().rows
    assert (row.group, row.why, row.claims) == ("apart", "edited between the runs", ())


def test_a_scenario_only_in_the_after_run_is_not_compared(tmp_path):
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), started=at(5))
    journal(tmp_path, "bot", "1", 2, outcome("a", PASSED), outcome("b", PASSED), started=at(6))
    rows = Comparison(*both(tmp_path)).page().rows
    assert [(r.id, r.group, r.why) for r in rows] == [
        ("a", "same", ""),
        ("b", "apart", "only in the after run"),
    ]


def test_runs_without_a_scenario_in_common_compare_none_and_see_only_noise(tmp_path):
    journal(tmp_path, "bot", "1", 4, *[outcome(s, FAILED) for s in "abcd"], started=at(5))
    journal(tmp_path, "bot", "1", 4, *[outcome(s, PASSED) for s in "abcd"], started=at(6),
            asks="Say hello.")  # fmt: skip
    page = Comparison(*both(tmp_path)).page()
    assert {row.group for row in page.rows} == {"apart"}
    assert (page.deltas.rate.value, page.deltas.rate.tone) == (100, "noise")


def test_a_pass_rate_missing_on_one_side_has_no_change(tmp_path):
    journal(tmp_path, "bot", "1", 1, outcome("a", NoVerdict("down")), started=at(5))
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), started=at(6))
    rate = Comparison(*both(tmp_path)).page().deltas.rate
    assert (rate.value, rate.tone) == (None, "none")


def test_a_change_of_pass_rate_is_noise_unless_the_evidence_shows_it(tmp_path):
    journal(tmp_path, "bot", "1", 3, *[outcome(s, FAILED) for s in "abc"], started=at(4))
    journal(tmp_path, "bot", "1", 3, outcome("a", PASSED), outcome("b", FAILED),
            outcome("c", FAILED), started=at(5))  # fmt: skip
    journal(tmp_path, "other", "1", 6, *[outcome(s, FAILED) for s in "abcdef"], started=at(4))
    journal(tmp_path, "other", "1", 6, *[outcome(s, PASSED) for s in "abcdef"], started=at(5))
    runs = sorted(Runs(tmp_path), key=lambda run: (run.spec.agent, run.spec.started))
    noise = Comparison(runs[0], runs[1]).page().deltas.rate
    assert noise.tone == "noise"
    assert noise.value == pytest.approx(100 / 3)
    real = Comparison(runs[2], runs[3]).page().deltas.rate
    assert (real.value, real.tone) == (100, "good")  # six scenarios, all from 0 to 1: 1 in 32


def test_a_real_change_colours_the_pass_rate_unless_they_disagree(tmp_path):
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
    runs = sorted(Runs(tmp_path), key=lambda run: (run.spec.agent, run.spec.started))
    down = Comparison(runs[0], runs[1]).page().deltas.rate
    assert (down.value, down.tone) == (-20, "noise")  # a to e got better, f worse: mixed
    mixed = Comparison(runs[2], runs[3]).page().deltas.rate
    assert (mixed.value, mixed.tone) == (10, "noise")  # the rate rises, the evidence says worse


def test_a_real_fall_turns_the_pass_rate_red_and_unjudged_attempts_stay_out(tmp_path):
    def attempts(scenario: str, verdict: Verdict | NoVerdict, count: int, start: int = 1):
        return [outcome(scenario, verdict, attempt=n) for n in range(start, start + count)]

    # three of six scenarios fall from 3/3 to 0/3: chance gives it about once in a thousand
    journal(tmp_path, "bot", "1", 6, *[o for s in "abcdef" for o in attempts(s, PASSED, 3)],
            k=3, started=at(4))  # fmt: skip
    journal(tmp_path, "bot", "1", 6, *[o for s in "abc" for o in attempts(s, FAILED, 3)],
            *[o for s in "def" for o in attempts(s, PASSED, 3)], k=3, started=at(5))  # fmt: skip
    # a falls from 40/40 to 18 of 20 judged: the 20 attempts with no verdict are not failures
    journal(tmp_path, "other", "1", 1, *attempts("a", PASSED, 40), k=40, started=at(4))
    journal(tmp_path, "other", "1", 1, *attempts("a", PASSED, 18), *attempts("a", FAILED, 2, 19),
            *attempts("a", NoVerdict("down"), 20, 21), k=40, started=at(5))  # fmt: skip
    runs = sorted(Runs(tmp_path), key=lambda run: (run.spec.agent, run.spec.started))
    real = Comparison(runs[0], runs[1]).page().deltas.rate
    assert (real.value, real.tone) == (-50, "bad")
    unjudged = Comparison(runs[2], runs[3]).page().deltas.rate
    assert (unjudged.value, unjudged.tone) == (-10, "noise")


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


def test_other_tiles_are_coloured_by_direction(tmp_path):
    journal(tmp_path, "bot", "1", 2, outcome("a", PASSED, tokens=10), outcome("b", PASSED),
            k=1, started=at(5))  # fmt: skip
    journal(tmp_path, "bot", "1", 2, outcome("a", PASSED, tokens=40), outcome("b", Failed("x")),
            k=1, started=at(6))  # fmt: skip
    deltas = Comparison(*both(tmp_path)).page().deltas
    assert (deltas.stable.value, deltas.stable.tone) == (-1, "bad")
    assert (deltas.tokens.value, deltas.tokens.tone) == (30, "bad")  # mean in + out per attempt
    assert (deltas.seconds.value, deltas.seconds.tone) == (0, "same")
    assert (deltas.errors.value, deltas.errors.tone) == (1, "bad")


def test_a_scenario_changes_by_a_percent_of_its_old_mean(tmp_path):
    before = (answers(s, 2.0, tokens=50) for s in "abc")
    journal(tmp_path, "bot", "1", 3, *before, started=at(5))
    after = (
        answers("a", 3.0, tokens=52),
        answers("b", 1.0, tokens=60),
        answers("c", 2.0, tokens=50),
    )
    journal(tmp_path, "bot", "1", 3, *after, started=at(6))
    rows = Comparison(*both(tmp_path)).page().rows
    assert [(r.id, r.seconds.value, r.seconds.tone) for r in rows] == [
        ("a", 50, "bad"),
        ("b", -50, "good"),
        ("c", 0, "same"),
    ]
    assert [(r.tokens.value, r.tokens.tone) for r in rows] == [
        (4, "same"),
        (20, "bad"),
        (0, "same"),
    ]


@pytest.mark.parametrize(
    ("tokens", "tone"),
    [(522, "same"), (523, "bad"), (525, "bad"), (478, "same"), (477, "good")],
    ids=["4.4%", "4.6% shows as 5%", "5%", "-4.4%", "-4.6% shows as -5%"],
)
def test_a_change_under_5_percent_as_the_page_rounds_it_is_the_same(tmp_path, tokens, tone):
    journal(tmp_path, "bot", "1", 1, answers("a", 2.0, tokens=500), started=at(5))
    journal(tmp_path, "bot", "1", 1, answers("a", 2.0, tokens=tokens), started=at(6))
    page = Comparison(*both(tmp_path)).page()
    (row,) = page.rows
    assert (row.tokens.tone, page.deltas.tokens.tone) == (tone, tone)
    assert page.deltas.tokens.value == 2 * tokens - 1000  # the tile keeps its unit


@pytest.mark.parametrize(("tokens", "row", "tile"), [(0, (0, "same"), (0, "same")),
                                                     (5, (None, "none"), (10, "bad"))])  # fmt: skip
def test_a_change_from_0_tokens_has_no_percent(tmp_path, tokens, row, tile):
    journal(tmp_path, "bot", "1", 1, answers("a", 2.0, tokens=0), started=at(5))
    journal(tmp_path, "bot", "1", 1, answers("a", 2.0, tokens=tokens), started=at(6))
    page = Comparison(*both(tmp_path)).page()
    assert (page.rows[0].tokens.value, page.rows[0].tokens.tone) == row
    assert (page.deltas.tokens.value, page.deltas.tokens.tone) == tile


def test_the_change_panels_hold_compared_scenarios_by_their_rise_then_id(tmp_path):
    before = (answers("a", 2.0, tokens=0), answers("b", 2.0), answers("c", 2.0))
    journal(tmp_path, "bot", "1", 3, *before, started=at(5))
    after = (answers("a", 3.0, tokens=5), answers("b", 3.0), answers("c", 1.0), answers("d", 9.0))
    journal(tmp_path, "bot", "1", 4, *after, started=at(6))
    page = Comparison(*both(tmp_path)).page()
    assert (page.by_seconds, page.by_tokens) == (("a", "b", "c"), ("b", "c"))


def test_a_row_counts_the_change_of_passed_attempts_in_its_groups_tone(tmp_path):
    before = [outcome("a", v, attempt=n) for n, v in enumerate((PASSED, PASSED, FAILED, FAILED), 1)]
    before += [outcome("b", PASSED, attempt=n) for n in (1, 2, 3)] + [outcome("c", PASSED)]
    journal(tmp_path, "bot", "1", 3, *before, k=4, started=at(5))
    after = [outcome("a", PASSED, attempt=n) for n in (1, 2)]
    after += [outcome("b", v, attempt=n) for n, v in enumerate((PASSED, FAILED, FAILED), 1)]
    journal(tmp_path, "bot", "1", 2, *after, k=3, started=at(6))
    rows = Comparison(*both(tmp_path)).page().rows
    assert [(r.id, r.group, r.held.value, r.held.tone) for r in rows] == [
        ("b", "worse", -2, "bad"),
        ("a", "better", 0, "good"),  # 2 of 4 to 2 of 2: as many passed, a higher rate
        ("c", "apart", None, "none"),
    ]


def cached(directory: Path, read: int | None, day: int) -> RunJournal:
    """A run on `day` whose one answer read `read` of its 100 input tokens from the cache."""
    usage = Usage(100, 10) if read is None else Usage(100, 10, cache_read=read)
    turn = Turn(Message("hi"), Answer("hello", usage), 1.0)
    outcome = Outcome("a", 1, Transcript((turn,)), PASSED, "max_turns")
    return journal(directory, "bot", "1", 1, outcome, started=at(day))


@pytest.mark.parametrize(
    ("before", "after", "change"),
    [
        (80, 20, (-60, "bad")),
        (20, 80, (60, "good")),
        (None, 80, (None, "none")),
        (80, None, (None, "none")),
    ],
    ids=["fell", "rose", "not reported before", "not reported after"],
)
def test_a_comparison_shows_how_the_share_of_cached_input_changed(
    tmp_path, before: int | None, after: int | None, change: tuple
):
    cached(tmp_path, before, 5)
    cached(tmp_path, after, 6)
    delta = Comparison(*both(tmp_path)).page().deltas.cached
    assert (delta.value, delta.tone) == change


@pytest.mark.parametrize(
    ("before", "after", "tone"),
    [(834, 831, "same"), (800, 200, "bad"), (800, 805, "good")],
    ids=["same whole percent", "fell", "rose a little"],
)
def test_the_colour_of_a_cache_change_agrees_with_the_percents_shown(
    tmp_path, before: int, after: int, tone: str
):
    for day, read in ((5, before), (6, after)):
        turn = Turn(Message("hi"), Answer("a", Usage(1000, 10, cache_read=read)), 1.0)
        outcome = Outcome("a", 1, Transcript((turn,)), PASSED, "max_turns")
        journal(tmp_path, "bot", "1", 1, outcome, started=at(day))
    assert Comparison(*both(tmp_path)).page().deltas.cached.tone == tone


def test_a_comparison_names_the_models_that_differ(tmp_path):
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), started=at(5), models=("u", "j"))
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), started=at(6), models=("u", "j2"))
    assert Comparison(*both(tmp_path)).page().differences == ("judge: j → j2",)


def test_a_comparison_names_another_agent_limit_but_not_other_limits(tmp_path):
    journal(
        tmp_path,
        "bot",
        "1",
        1,
        outcome("a", PASSED),
        started=at(5),
        limits=Limits(agent=4, user=1, judge=1, judge_per_minute=60),
    )
    journal(
        tmp_path,
        "bot",
        "1",
        1,
        outcome("a", PASSED),
        started=at(6),
        limits=Limits(agent=20, user=8, judge=2, agent_per_minute=600, user_per_minute=60),
    )
    assert Comparison(*both(tmp_path)).page().differences == (
        "agent limit: 4 → 20",
        "agent limit per minute: 0 → 600",
    )


@pytest.mark.parametrize(("then", "shown"), [("0.1.0", "0.1.0"), ("", "unknown")])
def test_a_comparison_names_another_convy(tmp_path, then: str, shown: str):
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), started=at(5), convy=then)
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), started=at(6))
    assert Comparison(*both(tmp_path)).page().differences == (f"convy: {shown} → {CONVY}",)


def test_the_index_lists_runs_newest_first_with_their_reports(tmp_path):
    first = journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), started=at(5))
    second = journal(tmp_path, "bot", "2", 2, outcome("a", FAILED), started=at(6))
    page = Index(Runs(tmp_path)).page()
    assert [(row.run.version, row.passed, row.judged, row.rate) for row in page.runs] == [
        ("2", 0, 1, 0),
        ("1", 1, 1, 1),
    ]
    assert page.runs[0].report == f"bot/{second.spec.id}/report.html"
    assert page.runs[1].report == f"bot/{first.spec.id}/report.html"


def test_no_runs_make_an_empty_index(tmp_path):
    assert '"runs":[]' in Index(Runs(tmp_path / "results")).html()


def data(html: str) -> object:
    start = html.index("const DATA = ") + len("const DATA = ")
    return json.loads(html[start : html.index(";\n", start)])


def test_pages_show_dialogues_as_data_only(tmp_path):
    hostile = "</script><img src=x onerror=alert(1)>"
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED, text=hostile), started=at(5))
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED, text=hostile), started=at(6))
    before, after = both(tmp_path)
    pages = (Report(after).html(), Comparison(before, after).html(), Index(Runs(tmp_path)).html())
    for html in pages:
        assert "</script><img" not in html
        assert "innerHTML" not in html
    run = data(pages[0])
    assert isinstance(run, dict)
    assert run["scenarios"][0]["attempts"][0]["turns"][0]["agent"] == hostile


def test_every_use_of_storage_is_guarded(tmp_path):
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), started=at(5))
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), started=at(6))
    before, after = both(tmp_path)
    for html in (Report(after).html(), Comparison(before, after).html(), Index([before]).html()):
        lines = [line for line in html.splitlines() if "localStorage" in line]
        assert lines
        assert all("try {" in line for line in lines)


def test_a_written_page_stands_alone(tmp_path):
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), started=at(5))
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), started=at(6))
    before, after = both(tmp_path)
    pages = (Report(after).html(), Comparison(before, after).html(), Index([before]).html())
    for html in pages:
        assert "/*include" not in html
        assert "function el(" in html
    assert "function dialogue(" in pages[0] and "function dialogue(" in pages[1]
    assert "function dialogue(" not in pages[2]  # the index has no scenario window


def test_every_page_has_the_icon(tmp_path):
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), started=at(5))
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), started=at(6))
    before, after = both(tmp_path)
    for html in (Report(after).html(), Comparison(before, after).html(), Index([before]).html()):
        assert '<link rel="icon" href="data:image/svg+xml,' in html


def test_attempts_below_trust_are_cut_out_and_counted(tmp_path):
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
    assert (page.metrics.passed, page.metrics.judged, page.metrics.cut) == (1, 1, 3)
    assert page.run.trust == 0.8
    a, b = sorted(page.scenarios, key=lambda s: s.id)
    assert (a.result, b.result) == ("passing", "none")
    assert [(x.passed, x.cut) for x in a.attempts] == [(True, False), (None, True)]
    assert [(c.held, c.judged, c.cut) for c in a.claims] == [(1, 1, 1)]
    assert [(c.confidence, c.trusted) for c in a.attempts[1].claims] == [(0.5, False)]
    assert page.metrics.stable == 0  # a cut attempt is not a pass


def test_trust_0_cuts_nothing(tmp_path):
    journal(tmp_path, "bot", "1", 1, outcome("a", unsure(False, 0.1)))
    page = Report(only(tmp_path)).page()
    assert (page.metrics.passed, page.metrics.judged, page.metrics.cut) == (0, 1, 0)
    assert page.scenarios[0].result == "failing"


def test_a_decision_without_confidence_is_trusted_and_shown_as_such(tmp_path):
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), trust=0.9)
    (scenario,) = Report(only(tmp_path)).page().scenarios
    (claim,) = scenario.attempts[0].claims
    assert (claim.passed, claim.confidence, claim.trusted) == (True, None, True)
    assert scenario.result == "passing"


def test_the_index_and_the_comparison_show_each_run_with_its_trust(tmp_path):
    journal(tmp_path, "bot", "1", 1, outcome("a", unsure(True, 0.5)), started=at(5))
    journal(tmp_path, "bot", "1", 1, outcome("a", unsure(True, 0.5)), started=at(6), trust=0.8)
    page = Comparison(*both(tmp_path)).page()
    assert (page.before.trust, page.after.trust) == (0, 0.8)
    assert (page.was.judged, page.now.judged, page.now.cut) == (1, 0, 1)
    assert page.differences == ()  # trust is not a warning
    assert [(row.run.trust, row.cut) for row in Index(Runs(tmp_path)).page().runs] == [
        (0.8, 1),
        (0, 0),
    ]


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
    assert page.metrics.seconds == 3.0
    assert page.scenarios[0].seconds == 3.0
    assert page.scenarios[0].attempts[0].seconds == 12.0


def answers(scenario: str, *seconds: float, attempt: int = 1, tokens: int = 10) -> Outcome:
    """A passed attempt of `scenario` whose answers took `seconds`, each `tokens` in and out."""
    turns = tuple(Turn(Message("hi"), Answer("hello", Usage(tokens, tokens)), s) for s in seconds)
    return Outcome(scenario, attempt, Transcript(turns), PASSED, "max_turns")


def test_a_scenario_spreads_from_its_fastest_answer_and_its_cheapest_attempt(tmp_path):
    played = (answers("a", 3.0, 1.0, tokens=5), answers("a", 2.0, attempt=2, tokens=50))
    journal(tmp_path, "bot", "1", 1, *played, k=2)
    (view,) = Report(only(tmp_path)).page().scenarios
    assert (view.fastest, view.slowest, view.fewest, view.most) == (1.0, 3.0, 20, 100)


def test_the_spread_puts_the_slowest_and_costliest_first_ties_by_id_and_the_unplayed_last(tmp_path):
    played = (
        answers("a", 1.0, tokens=30),
        answers("b", 4.0, tokens=10),
        answers("c", 4.0, tokens=30),
    )
    journal(tmp_path, "bot", "1", 4, *played)
    page = Report(only(tmp_path)).page()
    assert (page.by_seconds, page.by_tokens) == (("b", "c", "a", "d"), ("a", "c", "b", "d"))


def test_a_scenario_without_reported_tokens_has_a_time_spread_only(tmp_path):
    silent = Turn(Message("hi"), Answer("hello"), 2.0)
    unreported = Outcome("a", 1, Transcript((silent,)), PASSED, "max_turns")
    journal(tmp_path, "bot", "1", 2, unreported, answers("b", 1.0))
    page = Report(only(tmp_path)).page()
    assert [(v.id, v.fastest, v.fewest, v.most) for v in page.scenarios] == [
        ("a", 2.0, None, None),
        ("b", 1.0, 20, 20),
    ]
    assert page.by_tokens == ("b", "a")


def test_counts_not_reported_stay_none_at_every_level(tmp_path):
    turn = Turn(Message("hi"), Answer("a", Usage(10, 5)), 1.0)
    journal(tmp_path, "bot", "1", 1, Outcome("a", 1, Transcript((turn,)), PASSED, "max_turns"))
    page = Report(only(tmp_path)).page()
    scenario, (attempt,) = page.scenarios[0], page.scenarios[0].attempts
    assert (attempt.cache_read, attempt.cache_write, attempt.thinking_tokens) == (None, None, None)
    assert (scenario.cache_read, scenario.cache_write, scenario.thinking_tokens) == (
        None,
        None,
        None,
    )
    assert (page.metrics.cache_read, page.metrics.cache_write) == (None, None)


def test_cache_means_cover_only_the_attempts_that_report_them(tmp_path):
    def played(attempt: int, usage: Usage) -> Outcome:
        turn = Turn(Message("hi"), Answer("a", usage), 1.0)
        return Outcome("a", attempt, Transcript((turn,)), PASSED, "max_turns")

    reported, silent = played(1, Usage(100, 10, cache_read=80)), played(2, Usage(100, 10))
    journal(tmp_path, "bot", "1", 1, reported, silent, k=2)
    page = Report(only(tmp_path)).page()
    assert (page.scenarios[0].cache_read, page.metrics.cache_read) == (80, 80)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_scripts_of_every_page_parse(tmp_path):
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), started=at(5))
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), started=at(6))
    before, after = both(tmp_path)
    pages = (Report(after).html(), Comparison(before, after).html(), Index([before]).html())
    scripts = [body for html in pages for body in re.findall(r"<script>(.*?)</script>", html, re.S)]
    assert len(scripts) == 6
    for number, body in enumerate(scripts):
        file = tmp_path / f"script{number}.js"
        file.write_text(body, encoding="utf-8")
        done = subprocess.run(["node", "--check", str(file)], check=False, capture_output=True)
        assert done.returncode == 0, done.stderr.decode()
