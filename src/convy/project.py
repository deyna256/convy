"""A user's project: the files convy loads from it, and the template `convy init` copies."""

import hashlib
import importlib.util
import sys
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from types import ModuleType

from msgspec import Struct

from convy.agent import Agent
from convy.bench import Files, RunSpec
from convy.model import Models
from convy.report import Comparison, Index, Report, Run, Runs
from convy.scenario import Scenarios

# Files in the template whose names would otherwise be hidden from the package.
RENAMED = {"env.example": ".env.example", "gitignore": ".gitignore"}
COMPILED = "__pycache__"  # pip compiles the installed template; a project does not need it


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
        return found

    def agent(self, name: str) -> ProjectAgent:
        path = self.directory / "agents" / f"{name}.py"
        if not path.is_file():
            raise FileNotFoundError(f"no agent {name!r}: there is no {path}")
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

    def scenarios(self) -> Scenarios:
        return Scenarios(self.directory / "scenarios")

    def results(self) -> Path:
        return self.directory / "results"

    def page(self) -> Path:
        """The index: every run, with a link to its report."""
        return self.results() / "index.html"

    def run_page(self, spec: RunSpec) -> Path:
        return self.results() / spec.agent / spec.id / "report.html"

    def report(self) -> tuple[Path, ...]:
        """Write every run's report and the index; return the runs that could not be read
        whole, relative to `results()`."""
        runs = Runs(self.results())
        read = list(runs)
        for run in read:
            self.write(self.run_page(run.spec), Report(run).html())
        self.write(self.page(), Index(read).html())
        return runs.broken()

    def compare(self, before: Run, after: Run) -> Path:
        """Write the comparison of two runs, `compare/<before>-vs-<after>.html`."""
        short = (before.spec.id.rpartition("_")[2], after.spec.id.rpartition("_")[2])
        path = self.results() / "compare" / f"{short[0]}-vs-{short[1]}.html"
        self.write(path, Comparison(before, after).html())
        return path

    def write(self, path: Path, html: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")

    def old_journals(self) -> bool:
        """Whether `results/runs/` holds journals of convy 0.1, which this version does not read.
        An agent named `runs` has a folder of that name too, so the check looks for the files."""
        return any(self.results().glob("runs/*/*.jsonl"))

    def files(self, agent: str) -> Files:
        """The sha256 of the agent's file and `models.py`, to tell whether they changed."""
        return Files(
            agent=self.fingerprint(self.directory / "agents" / f"{agent}.py"),
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
