"""A user's project: the files convy loads from it, and the template `convy init` copies."""

import hashlib
import importlib.util
import sys
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from types import ModuleType
from typing import Annotated

import msgspec
from msgspec import UNSET, Meta, Struct, UnsetType
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from convy.agent import Agent
from convy.bench import Files, Limits, RunSpec
from convy.model import Models
from convy.report import Comparison, Index, Report, Run, Runs
from convy.scenario import Scenarios

# Files in the template whose names would otherwise be hidden from the package.
RENAMED = {"env.example": ".env.example", "gitignore": ".gitignore"}
COMPILED = "__pycache__"  # pip compiles the installed template; a project does not need it


type Places = Annotated[int, Meta(ge=1)]  # how much a participant does at once
type PerMinute = Annotated[float, Meta(ge=0)]  # how many requests it sends per minute; 0: any


class AgentSettings(Struct, frozen=True, forbid_unknown_fields=True):
    """An agent's own table, `[tool.convy.agents.<agent>]`: each limit given there instead of the
    project's."""

    parallel: Places | UnsetType = UNSET
    per_minute: PerMinute | UnsetType = UNSET


class Settings(Struct, frozen=True, forbid_unknown_fields=True):
    """The project's settings, as `[tool.convy]` holds them: how much each participant does at
    once and per minute, and an agent's own limits."""

    agent_parallel: Places = 4
    user_parallel: Places = 4
    judge_parallel: Places = 4
    agent_per_minute: PerMinute = 0
    user_per_minute: PerMinute = 0
    judge_per_minute: PerMinute = 0
    agents: dict[str, AgentSettings] = {}

    def limits(self, agent: str) -> Limits:
        """The limits a run of the agent plays with: its own, else the project's. Agents are
        matched in lower case, since the environment gives their names so; of two names alike, the
        later wins, and the environment's come after the file's."""
        own = {name.lower(): found for name, found in self.agents.items()}.get(
            agent.lower(), AgentSettings()
        )
        return Limits(
            agent=self.agent_parallel if own.parallel is UNSET else own.parallel,
            user=self.user_parallel,
            judge=self.judge_parallel,
            agent_per_minute=self.agent_per_minute if own.per_minute is UNSET else own.per_minute,
            user_per_minute=self.user_per_minute,
            judge_per_minute=self.judge_per_minute,
        )


class Tools(Struct, frozen=True):
    """`[tool]` of `pyproject.toml`, as far as convy reads it."""

    convy: Settings = Settings()


class Pyproject(Struct, frozen=True):
    """`pyproject.toml`, as far as convy reads it."""

    tool: Tools = Tools()


class Variables(BaseSettings):
    """The `CONVY_*` variables of `.env` and the environment, over `[tool.convy]`, which is given
    to the constructor: a variable is `CONVY_` and the key in capitals, an agent's limit
    `CONVY_AGENTS__<AGENT>__PARALLEL`. It only reads them; the result is checked as `Settings`."""

    model_config = SettingsConfigDict(
        title="CONVY_* variables",
        env_prefix="CONVY_",
        env_nested_delimiter="__",
        extra="ignore",  # .env holds the project's other settings too, such as its keys
        frozen=True,
        hide_input_in_errors=True,
    )
    agent_parallel: int
    user_parallel: int
    judge_parallel: int
    agent_per_minute: float
    user_per_minute: float
    judge_per_minute: float
    agents: dict[str, dict[str, int | float]]

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return env_settings, dotenv_settings, init_settings


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
        return self.settings().limits(agent)

    def settings(self) -> Settings:
        """`[tool.convy]` of the project's `pyproject.toml`, then `.env`, then the environment,
        each over the one before. A key convy does not know in the file is an error, so a typo does
        not leave a limit at its default unnoticed."""
        path = self.directory / "pyproject.toml"
        try:
            table = msgspec.toml.decode(path.read_bytes(), type=Pyproject).tool.convy
        except FileNotFoundError:
            table = Settings()
        except msgspec.MsgspecError as error:  # not TOML, or not the table convy reads
            raise ValueError(f"{path}: {error}") from None
        found = Variables(_env_file=self.directory / ".env", **msgspec.to_builtins(table))
        try:
            return msgspec.convert(found.model_dump(), Settings)
        except msgspec.ValidationError as error:
            raise ValueError(f"CONVY_* variables: {error}") from None

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
