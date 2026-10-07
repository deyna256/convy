import sys
from pathlib import Path

import pytest

from convy.fakes import Echo
from convy.model import Models
from convy.project import Project


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_init_copies_the_template_once(tmp_path: Path):
    write(tmp_path / "models.py", "# mine\n")
    created = Project(tmp_path).init()
    assert tmp_path / ".env.example" in created
    assert tmp_path / ".gitignore" in created
    assert tmp_path / "agents" / "echo.py" in created
    assert tmp_path / "models.py" not in created
    assert (tmp_path / "models.py").read_text() == "# mine\n"
    assert Project(tmp_path).init() == ()


def test_init_skips_compiled_files(tmp_path: Path):
    template = tmp_path / "template"
    write(template / "agents" / "echo.py", "agent = 1\n")
    write(template / "agents" / "__pycache__" / "echo.cpython-312.pyc", "compiled")
    created = Project(tmp_path / "new").copied(template, tmp_path / "new")
    assert created == [tmp_path / "new" / "agents" / "echo.py"]


def test_report_writes_the_page_and_returns_broken_runs(tmp_path: Path):
    write(tmp_path / "results" / "bot" / "broken" / "run.json", "oops\n")
    project = Project(tmp_path)
    assert project.report() == (Path("bot/broken"),)
    assert project.index().is_file()


def test_old_journals_are_found_but_an_agent_named_runs_is_not_one(tmp_path: Path):
    project = Project(tmp_path)
    write(tmp_path / "results" / "runs" / "2026-10-06T14-05-00_a3f9" / "run.json", "{}")
    write(tmp_path / "results" / "runs" / "2026-10-06T14-05-00_a3f9" / "attempts.jsonl", "{}\n")
    assert not project.old_journals()
    write(tmp_path / "results" / "runs" / "bot" / "2026-10-06T14-05-00.000000.jsonl", "{}")
    assert project.old_journals()


def test_files_are_fingerprinted_to_tell_a_change(tmp_path: Path):
    write(tmp_path / "agents" / "bot.py", "agent = 1\n")
    write(tmp_path / "models.py", "models = 1\n")
    before = Project(tmp_path).files("bot")
    assert len(before.agent) == len(before.models) == 64
    write(tmp_path / "agents" / "bot.py", "agent = 2\n")
    after = Project(tmp_path).files("bot")
    assert (after.agent != before.agent, after.models == before.models) == (True, True)


def test_agent_is_loaded_with_its_version(tmp_path: Path):
    write(
        tmp_path / "agents" / "bot.py",
        'from convy.fakes import Echo\nagent = Echo()\nversion = "7"\n',
    )
    loaded = Project(tmp_path).agent("bot")
    assert (loaded.name, loaded.agent, loaded.version) == ("bot", Echo(), "7")


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("agent = 1\n", "expected an object `agent` with a `conversation` method"),
        ("x = 1\n", "expected an object `agent`"),
        (
            "from convy.fakes import Echo\nagent = Echo()\nversion = 2\n",
            "`version` must be a string",
        ),
    ],
)
def test_a_wrong_agent_file_is_named(tmp_path: Path, text: str, error: str):
    write(tmp_path / "agents" / "bot.py", text)
    with pytest.raises(ValueError, match=error):
        Project(tmp_path).agent("bot")


def test_a_missing_agent_is_named(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="no agent 'nobody'"):
        Project(tmp_path).agent("nobody")


def test_models_come_from_models_py(tmp_path: Path):
    write(
        tmp_path / "models.py",
        "from convy import Models\nfrom convy.fakes import FakeModel\n"
        "models = Models(user=FakeModel('hi'), judge=FakeModel('{}'))\n",
    )
    assert isinstance(Project(tmp_path).models(), Models)
    write(tmp_path / "models.py", "models = 1\n")
    with pytest.raises(ValueError, match="expected `models = Models"):
        Project(tmp_path).models()


def test_project_files_import_a_module_of_the_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(sys, "path", sys.path.copy())
    shared = f"shared_{tmp_path.name}"  # unique: modules stay imported between tests
    write(tmp_path / f"{shared}.py", 'version = "from the project"\n')
    write(
        tmp_path / "agents" / "bot.py",
        f"from convy.fakes import Echo\nfrom {shared} import version\nagent = Echo()\n",
    )
    assert Project(tmp_path).agent("bot").version == "from the project"
