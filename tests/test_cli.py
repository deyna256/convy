"""The `convy` command, run in a fresh project from the template. No network: agents are fakes."""

from pathlib import Path

import msgspec
import pytest
import time_machine

from convy.bench import Finished, RunFile
from convy.cli import main
from convy.project import Project
from convy.scenario import Outcome

# Every scenario of the template has two claims, so the fake judge decides two.
FAKE_MODELS = """
from convy import Models
from convy.fakes import FakeModel

models = Models(
    user=FakeModel("Hello!", "###STOP###"),
    judge=FakeModel('{"claims": [{"pass": true, "reason": "ok"}, {"pass": true, "reason": "ok"}]}'),
)
"""

UNAUTHORIZED = """
import httpx2
from convy import JsonAgent, JsonEndpoint

locked = httpx2.MockTransport(lambda request: httpx2.Response(401, text="bad token"))
agent = JsonAgent(JsonEndpoint("https://bot.test", transport=locked), {"q": "{text}"}, "a")
"""


def convy(*argv: str) -> int:
    with pytest.raises(SystemExit) as exit:
        main(list(argv))
    return int(exit.value.code or 0)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    main(["init", str(tmp_path)])
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_init_creates_the_template_and_keeps_existing_files(tmp_path: Path, capsys):
    (tmp_path / "models.py").write_text("# mine\n")
    main(["init", str(tmp_path)])
    assert (tmp_path / "models.py").read_text() == "# mine\n"
    for name in (".env.example", ".gitignore", "agents/echo.py", "scenarios/clarify-backup.yaml"):
        assert (tmp_path / name).is_file()
    main(["init", str(tmp_path)])
    assert "nothing to create" in capsys.readouterr().out


def test_smoke_on_echo_works(project: Path, capsys):
    assert convy("run", "echo", "--smoke") == 0
    out = capsys.readouterr().out
    assert "agent (" in out and "Hello! What can you help me with?" in out
    assert "connection works" in out
    assert not (project / "results").exists()


def test_smoke_on_an_agent_that_rejects_us_fails(project: Path, capsys):
    (project / "agents" / "locked.py").write_text(UNAUTHORIZED)
    assert convy("run", "locked", "--smoke") == 1
    assert "connection failed: [agent error: AgentFailure: POST" in capsys.readouterr().out


def test_a_run_writes_a_journal_and_the_report(project: Path, capsys):
    (project / "models.py").write_text(FAKE_MODELS)
    with time_machine.travel("2026-10-06 14:05:00+00:00", tick=False):
        assert convy("run", "echo", "--scenarios", "c*", "-k", "2") == 0
    (folder,) = (project / "results" / "echo").iterdir()
    assert folder.name.startswith("2026-10-06T")
    file = msgspec.json.decode((folder / "run.json").read_bytes(), type=RunFile)
    assert file.spec.id == folder.name
    assert (file.spec.agent, file.spec.k, len(file.spec.pairs())) == ("echo", 2, 6)
    assert file.spec.files == Project(project).files("echo")
    assert file.spec.convy
    assert isinstance(file.status, Finished)
    assert len((folder / "attempts.jsonl").read_bytes().splitlines()) == 6
    assert "echo" in (project / "results" / "index.html").read_text()
    out = capsys.readouterr().out
    assert f"echo: run {folder.name}, 3 scenarios, 2 attempts each" in out
    assert out.count("✓") == 6


@pytest.mark.parametrize(
    "argv",
    [
        ("run", "nobody", "--smoke"),
        ("run", "echo", "--scenarios", "nothing*"),
        ("run", "echo", "-k", "0"),
    ],
)
def test_a_project_that_cannot_run_exits_with_2(project: Path, argv: tuple[str, ...], capsys):
    (project / "models.py").write_text(FAKE_MODELS)
    assert convy(*argv) == 2
    assert capsys.readouterr().err.startswith("error: ")


def test_an_agent_with_a_body_without_the_message_exits_with_2(project: Path, capsys):
    (project / "agents" / "fixed.py").write_text(UNAUTHORIZED.replace("{text}", "hello"))
    assert convy("run", "fixed", "--smoke") == 2
    assert capsys.readouterr().err == 'error: the body has neither "{text}" nor "{history}"\n'


def test_smoke_on_several_agents_greets_each(project: Path, capsys):
    assert convy("run", "echo", "echo", "--smoke") == 0
    assert capsys.readouterr().out.count("Hello! What can you help me with?") == 2


def test_each_agent_gets_models_of_its_own(project: Path):
    (project / "models.py").write_text(FAKE_MODELS)
    assert convy("run", "echo", "echo", "--scenarios", "clarify-*") == 0
    folders = sorted((project / "results" / "echo").iterdir())
    assert len(folders) == 2
    for folder in folders:
        line = (folder / "attempts.jsonl").read_bytes().splitlines()[0]
        assert len(msgspec.json.decode(line, type=Outcome).transcript.turns) == 1


def test_a_missing_setting_does_not_show_the_keys(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys
):
    monkeypatch.delenv("GW_BASE_URL", raising=False)
    monkeypatch.delenv("GW_API_KEY", raising=False)
    (project / ".env").write_text("GW_API_KEY=sk-SECRET123\n")
    assert convy("run", "echo") == 2
    out, err = capsys.readouterr()
    assert "sk-SECRET123" not in out + err
    assert "error: GatewayEnv: base_url: Field required" in err


def test_a_run_names_broken_runs(project: Path, capsys):
    (project / "models.py").write_text(FAKE_MODELS)
    (project / "results" / "x" / "broken").mkdir(parents=True)
    (project / "results" / "x" / "broken" / "run.json").write_text("oops\n")
    assert convy("run", "echo", "--scenarios", "clarify-*") == 0
    err = capsys.readouterr().err
    assert f"skipped unreadable lines or a whole run: {project / 'results' / 'x' / 'broken'}" in err


def test_report_rebuilds_the_page_and_names_old_journals(project: Path, capsys):
    (project / "results" / "runs" / "x").mkdir(parents=True)
    (project / "results" / "runs" / "x" / "2026-10-06T14-05-00.000000.jsonl").write_text("{}\n")
    main(["report"])
    assert (project / "results" / "index.html").is_file()
    out, err = capsys.readouterr()
    assert out == f"report: {project / 'results' / 'index.html'}\n"
    assert err == (
        f"{project / 'results' / 'runs'} holds journals of convy 0.1, which this version does "
        "not read; run the agents again\n"
    )
