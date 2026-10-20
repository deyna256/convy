import re
import sys
import tomllib
from importlib.metadata import version
from pathlib import Path

import pytest

from convy.bench import Limits
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
    assert (tmp_path / "models.py").read_text(encoding="utf-8") == "# mine\n"
    assert Project(tmp_path).init() == ()


def test_init_uses_the_version_of_convy_that_created_it(tmp_path: Path):
    Project(tmp_path).init()
    with (tmp_path / "pyproject.toml").open("rb") as file:
        project = tomllib.load(file)
    assert project["project"]["dependencies"] == [f"convy=={version('convy')}"]


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
        "from convy import Models\nfrom convy.fakes import FakeJudge, FakeModel\n"
        "models = Models(user=FakeModel('hi'), judge=FakeJudge(()))\n",
    )
    assert isinstance(Project(tmp_path).models(), Models)
    write(tmp_path / "models.py", "models = 1\n")
    with pytest.raises(ValueError, match="expected `models = Models"):
        Project(tmp_path).models()


def test_a_model_given_as_the_judge_is_named(tmp_path: Path):
    write(
        tmp_path / "models.py",
        "from convy import Models\nfrom convy.fakes import FakeModel\n"
        "models = Models(user=FakeModel('hi'), judge=FakeModel('{}'))\n",
    )
    with pytest.raises(ValueError, match=r"expected a judge, such as judge=ChatJudge\(model\)"):
        Project(tmp_path).models()


def test_a_judge_must_say_whether_it_reviews_the_agent_thinking(tmp_path: Path):
    write(
        tmp_path / "models.py",
        "from convy import Models\nfrom convy.fakes import FakeModel\n"
        "class Judge:\n    name = 'j'\n    async def decide(self, transcript, claims): ...\n"
        "models = Models(user=FakeModel('hi'), judge=Judge())\n",
    )
    with pytest.raises(ValueError, match="reviews_agent_thinking"):
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


LIMITS = """
[tool.convy]
agent_parallel = 3
judge_parallel = 2
judge_per_minute = 120

[tool.convy.agents.fast]
parallel = 20
per_minute = 600

[tool.convy.agents.Bot]
parallel = 9
"""


@pytest.fixture
def limited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Project:
    """A project whose pyproject.toml sets limits, run from another folder: the project's own
    files count, not those where convy runs."""
    write(tmp_path / "project" / "pyproject.toml", LIMITS)
    monkeypatch.chdir(tmp_path)
    write(tmp_path / "pyproject.toml", "[tool.convy]\nagent_parallel = 1\n")
    return Project(tmp_path / "project")


def test_limits_come_from_the_project_table(limited: Project):
    assert limited.limits("fast") == Limits(
        agent=20, user=4, judge=2, agent_per_minute=600, judge_per_minute=120
    )
    assert limited.limits("other") == Limits(agent=3, user=4, judge=2, judge_per_minute=120)


def test_a_limit_per_minute_comes_from_the_environment_too(
    limited: Project, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("CONVY_USER_PER_MINUTE", "30")
    monkeypatch.setenv("CONVY_AGENT_PER_MINUTE", "60")
    monkeypatch.setenv("CONVY_AGENTS__FAST__PER_MINUTE", "90")
    assert limited.limits("fast").agent_per_minute == 90
    assert limited.limits("other").agent_per_minute == 60
    assert limited.limits("other").user_per_minute == 30


def test_the_environment_wins_over_env_file_and_table(
    limited: Project, monkeypatch: pytest.MonkeyPatch
):
    env = "GW_API_KEY=secret\nCONVY_JUDGE_PARALLEL=5\nCONVY_USER_PARALLEL=6\n"
    write(limited.directory / ".env", env)
    monkeypatch.setenv("CONVY_USER_PARALLEL", "7")
    monkeypatch.setenv("CONVY_AGENTS__FAST__PARALLEL", "1")
    assert limited.limits("fast") == Limits(
        agent=1, user=7, judge=5, agent_per_minute=600, judge_per_minute=120
    )


def test_agents_are_matched_in_any_case(limited: Project, monkeypatch: pytest.MonkeyPatch):
    assert limited.limits("bot").agent == 9
    monkeypatch.setenv("CONVY_AGENTS__BOT__PARALLEL", "11")  # the environment gives `bot`
    assert limited.limits("Bot").agent == 11


def test_limits_default_to_4_without_a_table(tmp_path: Path):
    assert Project(tmp_path).limits("bot") == Limits()


@pytest.mark.parametrize(
    ("table", "error"),
    [
        (
            "[tool.convy]\njudge-parallel = 2\n",
            "unknown field `judge-parallel` - at `$.tool.convy`",
        ),
        ("[tool.convy.agents.bot]\nparalel = 2\n", "unknown field `paralel`"),
        ("[tool.convy]\nagent_parallel = 0\n", "`int` >= 1 - at `$.tool.convy.agent_parallel`"),
        ("[tool.convy]\njudge_per_minute = -1\n", ">= 0.0 - at `$.tool.convy.judge_per_minute`"),
        ("[tool.convy]\nagents = 5\n", "Expected `object`, got `int` - at `$.tool.convy.agents`"),
        ("[tool.convy\n", "Expected ']'"),
    ],
)
def test_a_wrong_table_is_an_error_that_names_the_file(tmp_path: Path, table: str, error: str):
    write(tmp_path / "pyproject.toml", table)
    with pytest.raises(ValueError, match=re.escape(f"{tmp_path / 'pyproject.toml'}: ")) as raised:
        Project(tmp_path).limits("bot")
    assert error in str(raised.value)


def test_a_wrong_variable_is_an_error_that_names_the_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("CONVY_JUDGE_PARALLEL", "0")
    with pytest.raises(ValueError, match=re.escape("CONVY_* variables: Expected `int` >= 1")):
        Project(tmp_path).limits("bot")
