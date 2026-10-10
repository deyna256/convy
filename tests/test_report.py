import json
import secrets
from datetime import UTC, datetime
from pathlib import Path

import pytest

from convy.agent import Answer, Message, NoUsage, Usage
from convy.bench import Finished, Interrupted, RunJournal, RunSpec
from convy.dialog import Claim, Confidence, Failed, NoVerdict, Transcript, Turn, Verdict
from convy.report import Comparison, Index, Report, Run, Runs
from convy.scenario import Outcome, Scenario

DAY = datetime(2026, 10, 6, tzinfo=UTC)
PASSED = Verdict((Claim(True, ""),))
FAILED = Verdict((Claim(False, ""),))


def unsure(passed: bool, value: float) -> Verdict:
    return Verdict((Claim(passed, "", Confidence(value)),))


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
    claims: tuple[str, ...] = ("greets",),
    trust: float = 0.0,
) -> RunJournal:
    """A run of `scenarios` scenarios, `a`, `b`, …, `k` attempts each, holding `outcomes`."""
    started = started or datetime.now(UTC)
    played = tuple(Scenario(chr(97 + i), 1, asks, claims) for i in range(scenarios))
    spec = RunSpec(
        id or f"{started:%Y-%m-%dT%H-%M-%S}_{secrets.token_hex(2)}",
        agent,
        version,
        *models,
        k,
        4,
        600,
        played,
        started,
        trust=trust,
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
    two = Verdict((Claim(True, ""), Claim(True, "")))  # scenario a has one claim
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
    assert (metrics.agent_errors, metrics.model_errors, metrics.errors) == (1, 1, 2)
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
    assert (attempt.passed, attempt.error) == (None, "judge down")


def test_a_claim_is_summed_up_over_the_attempts_the_judge_decided(tmp_path):
    decided = Verdict((Claim(True, "said hi"), Claim(False, "too long")))
    held = Verdict((Claim(True, ""), Claim(True, "")))
    played = (outcome("a", v, attempt=n) for n, v in enumerate((decided, held, Failed("down")), 1))
    journal(tmp_path, "bot", "1", 1, *played, k=3, claims=("greets", "is brief"))
    (scenario,) = Report(only(tmp_path)).page().scenarios
    assert [(c.text, c.held, c.judged, c.result) for c in scenario.claims] == [
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


def test_a_significant_change_that_disagrees_with_the_pass_rate_is_noise(tmp_path):
    def attempts(scenario: str, verdict: Verdict, count: int) -> list[Outcome]:
        return [outcome(scenario, verdict, attempt=n) for n in range(1, count + 1)]

    # a to e go from failing to passing; f, played k times, loses half its passes
    k = 20
    journal(tmp_path, "bot", "1", 6, *[outcome(s, FAILED) for s in "abcde"],
            *attempts("f", PASSED, k), k=k, started=at(4))  # fmt: skip
    journal(tmp_path, "bot", "1", 6, *[outcome(s, PASSED) for s in "abcde"],
            *attempts("f", PASSED, 10), *attempts("f", FAILED, k)[10:], k=k,
            started=at(5))  # fmt: skip
    # the same, but f loses all its passes over five attempts: equal pass rates
    journal(tmp_path, "other", "1", 6, *[outcome(s, FAILED) for s in "abcde"],
            *attempts("f", PASSED, 5), k=5, started=at(4))  # fmt: skip
    journal(tmp_path, "other", "1", 6, *[outcome(s, PASSED) for s in "abcde"],
            *attempts("f", FAILED, 5), k=5, started=at(5))  # fmt: skip
    runs = sorted(Runs(tmp_path), key=lambda run: (run.spec.agent, run.spec.started))
    down = Comparison(runs[0], runs[1]).page().deltas.rate
    assert (down.value, down.tone) == (-20, "noise")
    level = Comparison(runs[2], runs[3]).page().deltas.rate
    assert (level.value, level.tone) == (0, "same")


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
    assert page.models == ()  # trust is not a warning
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
