import json
from datetime import UTC, datetime
from pathlib import Path

from convy.agent import Answer, Message, NoUsage, Usage
from convy.bench import JsonlJournal, RunHeader
from convy.dialog import Claim, NoVerdict, Transcript, Turn, Verdict
from convy.report import Report, Runs
from convy.scenario import Outcome

PASSED = Verdict((Claim(True, ""),))
FAILED = Verdict((Claim(False, ""),))


def outcome(
    scenario: str, verdict: Verdict | NoVerdict, text: str = "hello", tokens: int = 10
) -> Outcome:
    turn = Turn(Message("hi"), Answer(text, Usage(tokens, tokens)), 2.0)
    stop = "model_failure" if isinstance(verdict, NoVerdict) else "max_turns"
    return Outcome(scenario, 1, ("greets",), Transcript((turn,)), verdict, stop)


def journal(directory, agent: str, version: str, planned: int, *outcomes: Outcome):
    started = datetime.now(UTC)  # each run its own file
    header = RunHeader(agent, version, "fake", "fake", 1, planned, started)
    for item in outcomes:
        JsonlJournal(directory, header).record(item)


def test_runs_read_back_what_journals_wrote(tmp_path):
    written = outcome("a", NoVerdict("judge down"))
    journal(tmp_path, "bot", "1", 1, written)
    (run,) = Runs(tmp_path)
    assert run.outcomes == (written,)
    assert run.complete()
    assert Runs(tmp_path).broken() == ()


def test_runs_skip_and_list_a_broken_journal(tmp_path):
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED))
    (tmp_path / "bot" / "broken.jsonl").write_text("not json\n")
    assert len(list(Runs(tmp_path))) == 1
    assert Runs(tmp_path).broken() == (Path("bot/broken.jsonl"),)


def test_runs_keep_the_lines_they_can_read(tmp_path):
    good = outcome("a", PASSED)
    journal(tmp_path, "bot", "1", 2, good, outcome("b", PASSED))
    (path,) = (tmp_path / "bot").iterdir()
    path.write_bytes(path.read_bytes()[:-20])  # the last line cut short, as by a crash
    (run,) = Runs(tmp_path)
    assert run.outcomes == (good,)
    assert Runs(tmp_path).broken() == (run.path,) == (path.relative_to(tmp_path),)


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


def test_page_shows_journals_relative_to_the_runs_directory(tmp_path):
    journal(tmp_path, "bot", "1", 1, outcome("a", PASSED))
    (path,) = (tmp_path / "bot").iterdir()
    (attempt,) = Report(Runs(tmp_path)).page().cells["a|bot 1"].attempts
    assert attempt.run == f"bot/{path.name}"


def test_page_shows_unreported_tokens_as_null(tmp_path):
    turn = Turn(Message("hi"), Answer("hello", NoUsage()), 1.0)
    written = Outcome("a", 1, ("greets",), Transcript((turn,)), PASSED, "max_turns")
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
    early = RunHeader("bot", "1", "user-a", "judge-a", 1, 1, datetime(2026, 10, 5, tzinfo=UTC))
    late = RunHeader("bot", "1", "user-b", "judge-b", 1, 1, datetime(2026, 10, 6, tzinfo=UTC))
    for header in (early, late):
        JsonlJournal(tmp_path, header).record(outcome("a", PASSED))
    (group,) = Report(Runs(tmp_path)).page().groups
    assert (group.agent, group.version) == ("bot", "1")
    assert (group.user, group.judge) == ("user-b", "judge-b")  # the latest run's models
    assert group.started == "2026-10-06T00:00:00+00:00"
