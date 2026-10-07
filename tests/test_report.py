import json
import secrets
from datetime import UTC, datetime
from pathlib import Path

import pytest

from convy.agent import Answer, Message, NoUsage, Usage
from convy.bench import Finished, Interrupted, RunJournal, RunSpec
from convy.dialog import Claim, Failed, NoVerdict, Transcript, Turn, Verdict
from convy.report import Report, Runs
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
    assert "bot/index.html" in Report(Runs(tmp_path)).pages()


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


def page(directory: Path):
    return Report(Runs(directory)).page(list(Runs(directory)))


def at(day: int) -> datetime:
    return DAY.replace(day=day)


def test_pass_rate_weighs_scenarios_equally_with_a_margin_from_three(tmp_path):
    journal(
        tmp_path,
        "bot",
        "1",
        3,
        outcome("a", PASSED),
        outcome("a", PASSED, attempt=2),
        outcome("b", PASSED),
        outcome("b", FAILED, attempt=2),
        outcome("c", FAILED),
        outcome("c", Failed("down"), attempt=2),
        k=2,
    )
    (run,) = page(tmp_path).runs
    assert run.passed == 0.5
    assert run.margin == pytest.approx(1.96 * 0.5 / 3**0.5)
    assert (run.steady, run.counted, run.played) == (1, 3, 3)
    assert run.agent_failures == 1


def test_no_verdict_is_left_out_and_two_scenarios_get_no_margin(tmp_path):
    journal(
        tmp_path,
        "bot",
        "1",
        2,
        outcome("a", PASSED),
        outcome("a", NoVerdict("down"), attempt=2),
        outcome("b", FAILED),
        k=2,
    )
    (run,) = page(tmp_path).runs
    assert (run.passed, run.margin) == (0.5, None)
    assert (run.steady, run.counted) == (0, 0)  # a has no verdict on one, b lacks an attempt
    assert run.model_failures == 1


def test_one_attempt_each_has_no_pass_k(tmp_path):
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED))
    (run,) = page(tmp_path).runs
    assert (run.k, run.steady, run.counted) == (1, 0, 0)


def test_a_run_without_verdicts_has_no_pass_rate(tmp_path):
    journal(tmp_path, "bot", "1", 2, outcome("a", NoVerdict("down")), outcome("b", NoVerdict("x")))
    (run,) = page(tmp_path).runs
    assert (run.passed, run.margin, run.change) == (None, None, None)
    assert run.model_failures == 2


def test_the_change_pairs_scenarios_played_unchanged_in_both_runs(tmp_path):
    before = [outcome(s, FAILED) for s in "abcd"]
    after = [outcome(s, PASSED) for s in "abc"] + [outcome("d", FAILED)]
    journal(tmp_path, "bot", "1", 4, *before, started=at(5))
    journal(tmp_path, "bot", "1", 4, *after, started=at(6))
    first, second = page(tmp_path).runs
    assert first.change is None
    assert second.change is not None
    assert (second.change.delta, second.change.scenarios) == (0.75, 4)
    assert second.change.verdict == "better"  # 0.75 > 1.96 · 0.5 / √4 = 0.49


def test_a_change_within_its_margin_is_noise_and_under_three_scenarios_too_few(tmp_path):
    journal(tmp_path, "bot", "1", 3, *[outcome(s, FAILED) for s in "abc"], started=at(4))
    journal(
        tmp_path,
        "bot",
        "1",
        3,
        outcome("a", PASSED),
        outcome("b", FAILED),
        outcome("c", FAILED),
        started=at(5),
    )
    journal(tmp_path, "bot", "1", 2, outcome("a", FAILED), outcome("b", FAILED), started=at(6))
    _, noise, few = page(tmp_path).runs
    assert noise.change is not None and noise.change.verdict == "noise"
    assert few.change is not None and few.change.verdict == "few"


def test_a_changed_scenario_is_not_compared_and_is_marked(tmp_path):
    journal(tmp_path, "bot", "1", 1, outcome("a", FAILED), started=at(5), asks="Say hi.")
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), started=at(6), asks="Say hello.")
    report = page(tmp_path)
    first, second = report.runs
    assert second.change is None
    old, new = (report.cells[f"a@{run.id}"] for run in report.runs)
    assert (old.changed, new.changed) == (True, False)
    assert (new.earlier, new.revised, new.tint) == (first.id, True, "")
    assert (new.user, old.user) == ("Say hello.", "Say hi.")


def test_cells_are_tinted_against_the_nearest_run_that_played_the_scenario(tmp_path):
    journal(tmp_path, "bot", "1", 2, outcome("a", FAILED), outcome("b", PASSED), started=at(4))
    journal(tmp_path, "bot", "1", 1, outcome("a", FAILED), started=at(5))  # does not play b
    journal(tmp_path, "bot", "1", 2, outcome("a", PASSED), outcome("b", FAILED), started=at(6))
    report = page(tmp_path)
    first, second, third = report.runs
    assert f"b@{second.id}" not in report.cells
    assert report.cells[f"a@{second.id}"].tint == ""
    assert report.cells[f"a@{third.id}"].tint == "better"
    b = report.cells[f"b@{third.id}"]
    assert (b.earlier, b.revised, b.tint) == (first.id, False, "worse")
    assert report.changed == ("a", "b")
    assert report.scenarios == ("a", "b")


def test_a_cell_is_tinted_against_the_nearest_run_with_the_same_scenario(tmp_path):
    journal(tmp_path, "bot", "1", 1, outcome("a", FAILED), started=at(4), asks="Say hi.")
    journal(tmp_path, "bot", "1", 1, outcome("a", FAILED), started=at(5), asks="Say hello.")
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), started=at(6), asks="Say hi.")
    report = page(tmp_path)
    _, second, third = report.runs
    cell = report.cells[f"a@{third.id}"]
    assert (cell.earlier, cell.revised, cell.tint) == (second.id, True, "better")
    assert report.changed == ("a",)


def test_scenarios_changed_in_the_latest_run_come_first(tmp_path):
    journal(tmp_path, "bot", "1", 3, *[outcome(s, PASSED) for s in "abc"], started=at(5))
    journal(
        tmp_path,
        "bot",
        "1",
        3,
        outcome("a", PASSED),
        outcome("b", PASSED),
        outcome("c", FAILED),
        started=at(6),
    )
    report = page(tmp_path)
    assert (report.changed, report.scenarios) == (("c",), ("c", "a", "b"))


def test_a_run_says_its_status_and_whether_the_models_changed(tmp_path):
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), started=at(5), models=("u", "j"))
    later = journal(tmp_path, "bot", "1", 1, started=at(6), models=("u", "j2"))
    later.write(Interrupted(at(6)))
    first, second = page(tmp_path).runs
    assert (first.status, first.models_changed) == ("running", False)
    assert (second.status, second.models_changed) == ("interrupted", True)
    assert (second.played, second.passed) == (1, None)


def test_an_attempt_shows_each_claim_with_its_decision(tmp_path):
    decided = Verdict((Claim(False, "it did not greet"),))
    journal(tmp_path, "bot", "1", 2, outcome("a", decided), outcome("b", Failed("down")))
    report = page(tmp_path)
    (run,) = report.runs
    (judged,) = report.cells[f"a@{run.id}"].attempts
    (failed,) = report.cells[f"b@{run.id}"].attempts
    assert (judged.passed, judged.error) == (False, "")
    assert [(c.text, c.passed, c.reason) for c in judged.claims] == [
        ("greets", False, "it did not greet")
    ]
    assert (failed.passed, failed.error, failed.stop) == (False, "down", "agent_failure")
    assert [(c.text, c.passed) for c in failed.claims] == [("greets", None)]


def test_page_shows_unreported_tokens_as_null(tmp_path):
    turn = Turn(Message("hi"), Answer("hello", NoUsage()), 1.0)
    written = Outcome("a", 1, Transcript((turn,)), PASSED, "max_turns")
    journal(tmp_path, "bot", "1", 1, written)
    report = page(tmp_path)
    (run,) = report.runs
    (attempt,) = report.cells[f"a@{run.id}"].attempts
    assert (attempt.input, attempt.output) == (None, None)
    assert (attempt.turns[0].input, attempt.turns[0].output) == (None, None)
    assert (run.input, run.output) == (None, None)


def test_pages_are_one_per_agent_and_an_index(tmp_path):
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), started=at(5))
    journal(tmp_path, "bot", "2", 1, outcome("a", FAILED), started=at(6))
    journal(tmp_path, "other", "1", 1, outcome("a", PASSED))
    report = Report(Runs(tmp_path))
    assert set(report.pages()) == {"index.html", "bot/index.html", "other/index.html"}
    index = report.index(list(Runs(tmp_path)))
    assert [(a.agent, a.runs, a.latest.version) for a in index.agents] == [
        ("bot", 2, "2"),
        ("other", 1, "1"),
    ]


def test_pages_show_dialogues_as_data_only(tmp_path):
    hostile = "</script><img src=x onerror=alert(1)>"
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED, text=hostile))
    for html in Report(Runs(tmp_path)).pages().values():
        assert "</script><img" not in html
        assert "innerHTML" not in html
    html = Report(Runs(tmp_path)).pages()["bot/index.html"]
    start = html.index("const DATA = ") + len("const DATA = ")
    data = json.loads(html[start : html.index(";\n", start)])
    (cell,) = data["cells"].values()
    assert cell["attempts"][0]["turns"][0]["agent"] == hostile


def test_no_runs_make_an_empty_index(tmp_path):
    pages = Report(Runs(tmp_path / "results")).pages()
    assert list(pages) == ["index.html"]
    assert '"agents":[]' in pages["index.html"]
