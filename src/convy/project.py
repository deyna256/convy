"""A user's project: the files convy loads from it, and the template `convy init` copies."""

import hashlib
import importlib.util
import sys
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from types import ModuleType

from msgspec import Struct
from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    PyprojectTomlConfigSettingsSource,
    SettingsConfigDict,
)

from convy.agent import Agent
from convy.bench import Files, Limits, RunSpec
from convy.model import Models
from convy.report import Comparison, Index, Report, Run, Runs
from convy.scenario import Scenarios

# Files in the template whose names would otherwise be hidden from the package.
RENAMED = {"env.example": ".env.example", "gitignore": ".gitignore"}
COMPILED = "__pycache__"  # pip compiles the installed template; a project does not need it


class AgentSettings(BaseModel, extra="forbid", frozen=True):
    """An agent's own table, `[tool.convy.agents.<name>]`."""

    parallel: int = Field(ge=1)


class ToolTable(PyprojectTomlConfigSettingsSource):
    """`[tool.convy]` in `pyproject.toml`, where a key convy does not know is an error: a typo
    would otherwise leave a limit at its default without a word."""

    def __call__(self) -> dict[str, object]:
        found = super().__call__()
        if unknown := sorted(set(found) - set(self.settings_cls.model_fields)):
            raise ValueError(f"pyproject.toml: [tool.convy] has no {', '.join(unknown)}")
        return found


class Settings(BaseSettings):
    """The project's settings: `[tool.convy]` in `pyproject.toml`, then `.env`, then the
    environment, each over the one before. Variables are the keys in capitals after `CONVY_`, an
    agent's as `CONVY_AGENTS__<NAME>__PARALLEL`."""

    model_config = SettingsConfigDict(
        title="settings",
        env_prefix="CONVY_",
        env_file=".env",
        env_nested_delimiter="__",
        extra="ignore",  # .env holds the project's other settings too, such as its keys
        frozen=True,
        hide_input_in_errors=True,
        pyproject_toml_table_header=("tool", "convy"),
    )
    agent_parallel: int = Field(4, ge=1)
    user_parallel: int = Field(4, ge=1)
    judge_parallel: int = Field(4, ge=1)
    agents: dict[str, AgentSettings] = {}

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return env_settings, dotenv_settings, ToolTable(settings_cls)


class ProjectAgent(Struct, frozen=True):
    """An agent loaded from `agents/<name>.py`, with the build label from its `version`."""

    name: str
    agent: Agent
    version: str


class Project(Struct, frozen=True):
    """A directory with `models.py`, `agents/`, `scenarios/` and `results/`."""

    directory: Path

    def models(self) -> Models:
        found = getattr(self.module(self.directory / "models.py"), "models", None)
        if not isinstance(found, Models):
            raise ValueError("models.py: expected `models = Models(user=…, judge=…)`")
        judge = found.judge
        if (
            not isinstance(getattr(judge, "name", None), str)
            or not isinstance(getattr(judge, "reviews_agent_thinking", None), bool)
            or not callable(getattr(judge, "decide", None))
        ):
            raise ValueError(
                "models.py: expected a judge, such as judge=ChatJudge(model), "
                "with a `name`, `reviews_agent_thinking` and a `decide` method"
            )
        return found

    def limits(self, agent: str) -> Limits:
        """The limits a run of the agent plays with: its own table's, else `agent_parallel`. Read
        from the current directory, as `.env` is."""
        settings = Settings()
        own = settings.agents.get(agent)
        return Limits(
            agent=own.parallel if own else settings.agent_parallel,
            user=settings.user_parallel,
            judge=settings.judge_parallel,
        )

    def agent(self, name: str) -> ProjectAgent:
        path = self.agent_file(name)
        module = self.module(path)
        expected = f"{path}: expected an object `agent` with a `conversation` method"
        try:
            agent = module.agent
        except AttributeError:
            raise ValueError(expected) from None
        if not callable(getattr(agent, "conversation", None)):
            raise ValueError(expected)
        version = getattr(module, "version", "")
        if not isinstance(version, str):
            raise ValueError(f"{path}: `version` must be a string")
        return ProjectAgent(name, agent, version)

    def agent_file(self, name: str) -> Path:
        path = self.directory / "agents" / f"{name}.py"
        if not path.is_file():
            raise FileNotFoundError(f"no agent {name!r}: there is no {path}")
        return path

    def scenarios(self) -> Scenarios:
        return Scenarios(self.directory / "scenarios")

    def results(self) -> Path:
        return self.directory / "results"

    def index(self) -> Path:
        """The index: every run, with a link to its report."""
        return self.results() / "index.html"

    def report_page(self, spec: RunSpec) -> Path:
        return self.results() / spec.agent / spec.id / "report.html"

    def report(self) -> tuple[Path, ...]:
        """Write every run's report and the index; return the runs that could not be read
        whole, relative to `results()`."""
        runs = Runs(self.results())
        read = list(runs)
        for run in read:
            self.write(self.report_page(run.spec), Report(run).html())
        self.write(self.index(), Index(read).html())
        return runs.broken(read)

    def compare(self, before: Run, after: Run) -> Path:
        """Write the comparison of two runs, `compare/<before>-vs-<after>.html`."""
        path = self.results() / "compare" / f"{before.spec.short()}-vs-{after.spec.short()}.html"
        self.write(path, Comparison(before, after).html())
        return path

    def write(self, path: Path, html: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")

    def old_journals(self) -> bool:
        """Whether `results/runs/` holds journals of convy 0.1, which this version does not read.
        An agent named `runs` has a folder of that name too, so the check looks for the files."""
        return any(path.name != "attempts.jsonl" for path in self.results().glob("runs/*/*.jsonl"))

    def files(self, agent: str) -> Files:
        """The sha256 of the agent's file and `models.py`, to tell whether they changed."""
        return Files(
            agent=self.fingerprint(self.agent_file(agent)),
            models=self.fingerprint(self.directory / "models.py"),
        )

    def fingerprint(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def init(self) -> tuple[Path, ...]:
        """Copy the template here, never over an existing file; return the files created."""
        return tuple(self.copied(files("convy").joinpath("template"), self.directory))

    def copied(self, source: Traversable, target: Path) -> list[Path]:
        created = []
        for item in source.iterdir():
            if item.name == COMPILED:
                continue
            path = target / RENAMED.get(item.name, item.name)
            if item.is_dir():
                created += self.copied(item, path)
            elif not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(item.read_bytes())
                created.append(path)
        return created

    def module(self, path: Path) -> ModuleType:
        """Run a project file as a module, under a name unique to its path."""
        name = "convy_project_" + hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:16]
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module  # pydantic resolves the module's classes through sys.modules
        folder = str(self.directory.resolve())
        if folder not in sys.path:  # project files import each other, as in a script
            sys.path.insert(0, folder)
        spec.loader.exec_module(module)
        return module
