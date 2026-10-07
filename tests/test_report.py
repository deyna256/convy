import json
import secrets
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

import pytest

from convy.agent import Answer, Message, NoUsage, Usage
from convy.bench import Finished, RunJournal, RunSpec
from convy.dialog import Claim, Failed, NoVerdict, Transcript, Turn, Verdict
from convy.report import Comparison, Index, Report, Run, Runs
from convy.scenario import Outcome, Scenario

DAY = datetime(2026, 10, 6, tzinfo=UTC)
PASSED = Verdict((Claim(True, ""),))
FAILED = Verdict((Claim(False, ""),))


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
    planned: int,
    *outcomes: Outcome,
    started: datetime | None = None,
    models: tuple[str, str] = ("fake", "fake"),
    id: str = "",
    k: int = 1,
    asks: str = "Say hi.",
) -> RunJournal:
    """A run of `planned` scenarios, `a`, `b`, …, `k` attempts each, holding `outcomes`."""
    started = started or datetime.now(UTC)
    scenarios = tuple(Scenario(chr(97 + i), 1, asks, ("greets",)) for i in range(planned))
    spec = RunSpec(
        id or f"{started:%Y-%m-%dT%H-%M-%S}_{secrets.token_hex(2)}",
        agent,
        version,
        *models,
        k,
        4,
        600,
        scenarios,
        started,
    )
    written = RunJournal(directory, spec)
    written.create()
    for item in outcomes:
        written.record(item)
    return written


def test_runs_read_back_what_journals_wrote(tmp_path):
    written = outcome("a", NoVerdict("judge down"))
    run_journal = journal(tmp_path, "bot", "1", 1, written)
    run_journal.write(Finished(datetime.now(UTC)))
    (run,) = Runs(tmp_path)
    assert run.outcomes == (written,)
    assert run.spec == run_journal.spec
    assert isinstance(run.status, Finished)
    assert run.complete()
    assert run.done() == {("a", 1)}
    assert Runs(tmp_path).broken() == ()


def test_runs_skip_and_list_a_broken_run(tmp_path):
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED))
    (tmp_path / "bot" / "broken").mkdir()
    (tmp_path / "bot" / "broken" / "run.json").write_text("not json\n")
    assert len(list(Runs(tmp_path))) == 1
    assert Runs(tmp_path).broken() == (Path("bot/broken"),)


def test_runs_keep_the_lines_they_can_read(tmp_path):
    good = outcome("a", PASSED)
    written = journal(tmp_path, "bot", "1", 2, good, outcome("b", PASSED))
    attempts = written.folder() / "attempts.jsonl"
    attempts.write_bytes(attempts.read_bytes()[:-20])  # the last line cut short, as by a crash
    (run,) = Runs(tmp_path)
    assert run.outcomes == (good,)
    assert (run.unreadable, run.complete()) == (1, False)
    assert Runs(tmp_path).broken() == (run.path,) == (written.folder().relative_to(tmp_path),)


def test_runs_count_a_line_the_scenarios_cannot_explain_as_unreadable(tmp_path):
    good = outcome("a", PASSED)
    two = Verdict((Claim(True, ""), Claim(True, "")))  # scenario a has one claim
    written = journal(
        tmp_path, "bot", "1", 1, good, outcome("zzz", PASSED), outcome("a", two, attempt=2), k=2
    )
    (run,) = Runs(tmp_path)
    assert run.outcomes == (good,)
    assert run.unreadable == 2
    assert Runs(tmp_path).broken() == (written.folder().relative_to(tmp_path),)
    assert "sms" not in Report(run).html()  # the page is still written


def test_runs_read_an_attempt_written_twice_once(tmp_path):
    first = outcome("a", PASSED)
    journal(tmp_path, "bot", "1", 1, first, outcome("a", FAILED))
    (run,) = Runs(tmp_path)
    assert run.outcomes == (first,)


def test_a_run_without_attempts_is_read(tmp_path):
    journal(tmp_path, "bot", "1", 2)
    (run,) = Runs(tmp_path)
    assert (run.outcomes, run.complete()) == ((), False)


def test_old_journals_are_not_runs(tmp_path):
    (tmp_path / "runs" / "bot").mkdir(parents=True)
    (tmp_path / "runs" / "bot" / "2026-10-06T14-05-00.000000.jsonl").write_text("{}\n")
    assert list(Runs(tmp_path)) == []
    assert Runs(tmp_path).broken() == ()


def test_a_run_is_found_by_its_id_or_its_random_part(tmp_path):
    written = journal(tmp_path, "bot", "1", 1)
    other = journal(tmp_path, "other", "1", 1)
    spec = written.spec
    assert Runs(tmp_path).run(spec.id).spec == spec
    assert Runs(tmp_path).run(spec.id.rpartition("_")[2]).spec == spec
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
    assert (metrics.passed, metrics.judged, metrics.rate()) == (3, 4, 0.75)
    assert (metrics.stable, metrics.scenarios, metrics.k) == (1, 3, 2)  # only a passed both
    assert (metrics.seconds, metrics.slowest) == (2.0, 2.0)
    assert (metrics.input, metrics.output, metrics.tokens()) == (30, 30, 60)
    assert (metrics.agent_errors, metrics.model_errors, metrics.errors()) == (1, 1, 2)
    assert (page.run.short, page.run.agent, page.run.status, page.run.k) == (
        page.run.id.rpartition("_")[2],
        "bot",
        "running",
        2,
    )


def test_with_one_attempt_each_a_passing_scenario_is_stable(tmp_path):
    journal(tmp_path, "bot", "1", 2, outcome("a", PASSED), outcome("b", FAILED))
    assert Report(only(tmp_path)).page().metrics.stable == 1


def test_a_run_without_verdicts_or_usage_reports_none(tmp_path):
    turn = Turn(Message("hi"), Answer("hello", NoUsage()), 1.0)
    written = Outcome("a", 1, Transcript((turn,)), NoVerdict("judge down"), "model_failure")
    journal(tmp_path, "bot", "1", 1, written)
    page = Report(only(tmp_path)).page()
    assert (page.metrics.rate(), page.metrics.tokens()) == (None, None)
    (scenario,) = page.scenarios
    (attempt,) = scenario.attempts
    assert (attempt.input, attempt.output, attempt.turns[0].input) == (None, None, None)
    assert (attempt.passed, attempt.error) == (None, "judge down")


def test_a_claim_is_summed_up_over_the_attempts_the_judge_decided(tmp_path):
    two = Scenario("a", 1, "Say hi.", ("greets", "is brief"))
    decided = Verdict((Claim(True, "said hi"), Claim(False, "too long")))
    held = Verdict((Claim(True, ""), Claim(True, "")))
    spec = RunSpec("run_a3f9", "bot", "1", "fake", "fake", 3, 4, 600, (two,), DAY)
    written = RunJournal(tmp_path, spec)
    written.create()
    for number, verdict in enumerate((decided, held, Failed("down")), 1):
        written.record(outcome("a", verdict, attempt=number))
    (scenario,) = Report(only(tmp_path)).page().scenarios
    assert [(c.text, c.held, c.judged, c.result()) for c in scenario.claims] == [
        ("greets", 2, 2, "passing"),
        ("is brief", 1, 2, "flaky"),
    ]
    first, _, failed = scenario.attempts
    assert [(c.passed, c.reason) for c in first.claims] == [(True, "said hi"), (False, "too long")]
    assert (failed.passed, failed.error, [c.passed for c in failed.claims]) == (
        False,
        "down",
        [None, None],
    )


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


def test_a_change_of_pass_rate_is_noise_unless_the_paired_test_says_otherwise(tmp_path):
    journal(tmp_path, "bot", "1", 3, *[outcome(s, FAILED) for s in "abc"], started=at(4))
    journal(tmp_path, "bot", "1", 3, outcome("a", PASSED), outcome("b", FAILED),
            outcome("c", FAILED), started=at(5))  # fmt: skip
    journal(tmp_path, "other", "1", 4, *[outcome(s, FAILED) for s in "abcd"], started=at(4))
    journal(tmp_path, "other", "1", 4, *[outcome(s, PASSED) for s in "abcd"], started=at(5))
    runs = sorted(Runs(tmp_path), key=lambda run: (run.spec.agent, run.spec.started))
    noise = Comparison(runs[0], runs[1]).page().deltas.rate
    assert noise.tone == "noise"
    assert noise.value == pytest.approx(100 / 3)
    real = Comparison(runs[2], runs[3]).page().deltas.rate
    assert (real.value, real.tone) == (100, "good")  # four scenarios, all from 0 to 1


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


def test_a_comparison_names_the_models_that_differ(tmp_path):
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), started=at(5), models=("u", "j"))
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), started=at(6), models=("u", "j2"))
    assert Comparison(*both(tmp_path)).page().models == ("judge: j → j2",)


def test_the_index_lists_runs_newest_first_with_their_reports(tmp_path):
    first = journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), started=at(5))
    second = journal(tmp_path, "bot", "2", 2, outcome("a", FAILED), started=at(6))
    page = Index(Runs(tmp_path)).page()
    assert [(row.run.version, row.passed, row.judged) for row in page.runs] == [
        ("2", 0, 1),
        ("1", 1, 1),
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


def test_every_use_of_storage_is_guarded():
    for page in ("run.html", "compare.html", "index.html"):
        text = files("convy").joinpath("pages", page).read_text(encoding="utf-8")
        lines = [line for line in text.splitlines() if "localStorage" in line]
        assert lines, page
        assert all("try {" in line for line in lines), page
