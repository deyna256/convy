import json
import secrets
from datetime import UTC, datetime
from pathlib import Path

import pytest

from convy.agent import Answer, Message, NoUsage, Usage
from convy.bench import Finished, RunJournal, RunSpec
from convy.dialog import Claim, NoVerdict, Transcript, Turn, Verdict
from convy.report import Report, Runs
from convy.scenario import Outcome, Scenario

PASSED = Verdict((Claim(True, ""),))
FAILED = Verdict((Claim(False, ""),))


def outcome(
    scenario: str, verdict: Verdict | NoVerdict, text: str = "hello", tokens: int = 10
) -> Outcome:
    turn = Turn(Message("hi"), Answer(text, Usage(tokens, tokens)), 2.0)
    stop = "model_failure" if isinstance(verdict, NoVerdict) else "max_turns"
    return Outcome(scenario, 1, Transcript((turn,)), verdict, stop)


def journal(
    directory: Path,
    agent: str,
    version: str,
    planned: int,
    *outcomes: Outcome,
    started: datetime | None = None,
    models: tuple[str, str] = ("fake", "fake"),
    id: str = "",
) -> RunJournal:
    """A run of `planned` scenarios, `a`, `b`, …, one attempt each, holding `outcomes`."""
    started = started or datetime.now(UTC)
    scenarios = tuple(Scenario(chr(97 + i), 1, "Say hi.", ("greets",)) for i in range(planned))
    spec = RunSpec(
        id or f"{started:%Y-%m-%dT%H-%M-%S}_{secrets.token_hex(2)}",
        agent,
        version,
        *models,
        1,
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


def test_page_sums_up_groups_and_cells(tmp_path):
    journal(tmp_path, "bot", "1", 2, outcome("a", PASSED), outcome("b", FAILED))
    journal(tmp_path, "bot", "1", 2, outcome("a", PASSED))  # stopped half way
    journal(
        tmp_path,
        "bot",
        "2",
        3,
        outcome("a", PASSED),
        outcome("b", PASSED),
        outcome("c", NoVerdict("down")),
    )
    page = Report(Runs(tmp_path)).page()
    first, second = page.groups
    assert (first.id, first.runs, first.stopped) == ("bot 1", 2, 1)
    assert first.passed is not None and first.passed.mean == 0.5
    assert (first.input, first.seconds, first.turn_max) == (10, 2.0, 2.0)
    assert second.passed is not None and second.passed.mean == 1.0  # no verdict is not a failure
    assert second.model_failures == 1
    assert page.scenarios == ("b", "a", "c")  # the groups differ on b, so it comes first
    assert page.cells["a|bot 1"].passed == 2
    assert page.cells["a|bot 1"].judged == 2


def test_html_shows_dialogues_as_data_only(tmp_path):
    journal(
        tmp_path,
        "bot",
        "1",
        1,
        outcome("a", PASSED, text="</script><img src=x onerror=alert(1)>"),
    )
    html = Report(Runs(tmp_path)).html()
    assert "</script><img" not in html
    data = html[html.index("const DATA = ") + 13 : html.index(";\n", html.index("const DATA = "))]
    assert json.loads(data)["cells"]["a|bot 1"]["attempts"][0]["turns"][0]["agent"].startswith(
        "</script>"
    )
    assert "innerHTML" not in html


def test_page_shows_runs_relative_to_the_results_directory(tmp_path):
    written = journal(tmp_path, "bot", "1", 1, outcome("a", PASSED))
    (attempt,) = Report(Runs(tmp_path)).page().cells["a|bot 1"].attempts
    assert attempt.run == f"bot/{written.spec.id}"


def test_page_shows_unreported_tokens_as_null(tmp_path):
    turn = Turn(Message("hi"), Answer("hello", NoUsage()), 1.0)
    written = Outcome("a", 1, Transcript((turn,)), PASSED, "max_turns")
    journal(tmp_path, "bot", "1", 1, written)
    page = Report(Runs(tmp_path)).page()
    (attempt,) = page.cells["a|bot 1"].attempts
    assert (attempt.input, attempt.output) == (None, None)
    assert (attempt.turns[0].input, attempt.turns[0].output) == (None, None)
    assert (page.groups[0].input, page.groups[0].output) == (None, None)


def test_a_run_without_verdicts_has_no_pass_rate(tmp_path):
    journal(tmp_path, "bot", "1", 2, outcome("a", NoVerdict("down")), outcome("b", NoVerdict("x")))
    (group,) = Report(Runs(tmp_path)).page().groups
    assert group.passed is None
    assert group.model_failures == 2


def test_an_empty_runs_directory_renders_an_empty_page(tmp_path):
    report = Report(Runs(tmp_path / "runs"))
    assert report.page().groups == ()
    assert '"groups":[]' in report.html()


def test_a_group_names_its_agent_version_models_and_latest_run(tmp_path):
    for day, models in ((5, ("user-a", "judge-a")), (6, ("user-b", "judge-b"))):
        started = datetime(2026, 10, day, tzinfo=UTC)
        journal(tmp_path, "bot", "1", 1, outcome("a", PASSED), started=started, models=models)
    (group,) = Report(Runs(tmp_path)).page().groups
    assert (group.agent, group.version) == ("bot", "1")
    assert (group.user, group.judge) == ("user-b", "judge-b")  # the latest run's models
    assert group.started == "2026-10-06T00:00:00+00:00"
