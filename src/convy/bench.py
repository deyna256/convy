"""A run: every scenario played against an agent, each outcome written to the run's folder."""

import asyncio
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from importlib import metadata
from pathlib import Path
from typing import Literal, Protocol

import msgspec
from msgspec import Struct

from convy.agent import Agent
from convy.model import Models
from convy.scenario import Outcome, Scenario

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

type Pair = tuple[str, int]  # a scenario's id and an attempt's number

CONVY = metadata.version("convy")  # the installed convy, which a new run records


class Files(Struct, frozen=True):
    """The sha256 of the project files a run was started with: its agent's file and `models.py`."""

    agent: str = ""
    models: str = ""


class RunSpec(Struct, frozen=True):
    """What a run plays and with what: everything needed to continue it unchanged."""

    id: str
    agent: str
    version: str
    user: str
    judge: str
    k: int
    parallel: int
    turn_timeout: float
    scenarios: tuple[Scenario, ...]
    started: datetime
    convy: str = CONVY
    files: Files = Files()
    trust: float = 0.0  # decisions the judge is less sure of are cut out; 0 cuts nothing

    def __post_init__(self) -> None:
        if not 0 <= self.trust <= 1:
            raise ValueError(f"trust must be from 0 to 1, got {self.trust}")

    def code_changes(self, files: Files, convy: str) -> tuple[str, ...]:
        """How the code that plays the run differs from the code it started with: the agent's
        file, `models.py` and convy itself, each a reason the run cannot continue unchanged. Known
        without loading the project, so it is checked first. A change in a module these files
        import, such as `gateway.py`, or in the service behind the agent, does not show here."""
        found = []
        if files.agent != self.files.agent:
            found.append(f"agents/{self.agent}.py changed since the run started")
        if files.models != self.files.models:
            found.append("models.py changed since the run started")
        if convy != self.convy:
            found.append(
                f"convy is {convy}, the run started on {self.convy}"
                if self.convy
                else f"convy is {convy}, the run does not say which convy started it"
            )
        return tuple(found)

    def label_changes(self, version: str, user: str, judge: str) -> tuple[str, ...]:
        """How the labels the project's code gives itself differ from the run's: the agent's
        `version` and the models' names, each a reason the run cannot continue unchanged. Known
        only once the agent and `models.py` are loaded, so `code_changes` comes first."""
        found = []
        if version != self.version:
            found.append(f"the agent's version is {version!r}, the run has {self.version!r}")
        if user != self.user:
            found.append(f"the user model is {user!r}, the run has {self.user!r}")
        if judge != self.judge:
            found.append(f"the judge model is {judge!r}, the run has {self.judge!r}")
        return tuple(found)

    def short(self) -> str:
        """The id's random part."""
        return self.id.rpartition("_")[2]

    def pairs(self) -> tuple[Pair, ...]:
        """Every attempt the run plays: each scenario, `k` times."""
        return tuple((s.id, attempt) for s in self.scenarios for attempt in range(1, self.k + 1))


class Running(Struct, frozen=True, tag="running"):
    """The run is being played, or its process died before it could say otherwise."""


class Finished(Struct, frozen=True, tag="finished"):
    """Every attempt of the run was played."""

    ended: datetime


class Interrupted(Struct, frozen=True, tag="interrupted"):
    """The run was stopped before its end; `convy resume` plays the rest."""

    ended: datetime


type Status = Running | Finished | Interrupted


class RunFile(Struct, frozen=True):
    """What `run.json` holds."""

    format: Literal[2, 3]
    spec: RunSpec
    status: Status


class RunInUse(Exception):
    """Another process is playing the run."""


class Journal(Protocol):
    """Where outcomes go as soon as they are ready."""

    def record(self, outcome: Outcome) -> None: ...


class Bench(Struct, frozen=True):
    """Scenarios to play, the models that play the user and judge, and how to play them."""

    scenarios: tuple[Scenario, ...]
    models: Models
    attempts: int = 1
    parallel: int = 4

    def __post_init__(self) -> None:
        if self.attempts < 1:
            raise ValueError(f"attempts must be at least 1, got {self.attempts}")
        if self.parallel < 1:
            raise ValueError(f"parallel must be at least 1, got {self.parallel}")

    async def run(
        self, agent: Agent, journal: Journal, done: frozenset[Pair] = frozenset()
    ) -> tuple[Outcome, ...]:
        """Play every scenario `attempts` times, at most `parallel` conversations at once; skip
        the attempts in `done`."""
        limit = asyncio.Semaphore(self.parallel)
        async with asyncio.TaskGroup() as group:
            tasks = [
                group.create_task(self.played(scenario, attempt, agent, journal, limit))
                for scenario in self.scenarios
                for attempt in range(1, self.attempts + 1)
                if (scenario.id, attempt) not in done
            ]
        return tuple(task.result() for task in tasks)

    async def played(
        self,
        scenario: Scenario,
        attempt: int,
        agent: Agent,
        journal: Journal,
        limit: asyncio.Semaphore,
    ) -> Outcome:
        async with limit:
            outcome = await scenario.outcome(agent, self.models, attempt)
        journal.record(outcome)
        return outcome


class RunJournal(Struct, frozen=True):
    """A run's folder, `<directory>/<agent>/<id>/`: `run.json` with the specification and the
    status, rewritten whole, and `attempts.jsonl`, a line per attempt, only appended to."""

    directory: Path
    spec: RunSpec

    def folder(self) -> Path:
        return self.directory / self.spec.agent / self.spec.id

    def create(self) -> None:
        """Make the folder of a new run; an existing one is an error, never written over."""
        self.folder().mkdir(parents=True, exist_ok=False)
        self.write(Running())

    @contextmanager
    def held(self) -> Iterator[None]:
        """Hold the run's folder for this process through `run.lock`, or raise `RunInUse`; a
        file system without locks holds nothing. The system lets the lock go when the process
        ends, however it ends, so the folder of a run whose process died can be held again."""
        with (self.folder() / "run.lock").open("a+b") as file:  # made when missing, never cut
            file.seek(0)  # a Windows lock starts at the file's position
            locked = True
            try:
                if sys.platform == "win32":
                    msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (BlockingIOError, PermissionError):  # taken: EWOULDBLOCK, or EACCES on Windows
                raise RunInUse(f"run {self.spec.id} is being played by another process") from None
            except OSError:  # ponytail: a file system without locks plays unguarded, as before
                locked = False
            try:
                yield
            finally:
                if sys.platform == "win32" and locked:  # Windows frees a closed file's locks late
                    msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)

    def write(self, status: Status) -> None:
        temporary = self.folder() / "run.json.tmp"
        temporary.write_bytes(msgspec.json.encode(RunFile(3, self.spec, status)))
        temporary.replace(self.folder() / "run.json")  # never half-written

    def record(self, outcome: Outcome) -> None:
        line = msgspec.json.encode(outcome) + b"\n"
        with (self.folder() / "attempts.jsonl").open("a+b") as file:
            if file.seek(0, os.SEEK_END) > 0:
                file.seek(-1, os.SEEK_END)
                if file.read(1) != b"\n":  # the last line was cut short, by a crash say
                    line = b"\n" + line
            file.write(line)

    async def play(
        self, bench: Bench, agent: Agent, journal: Journal, done: frozenset[Pair] = frozenset()
    ) -> tuple[Outcome, ...]:
        """Play the run's attempts not in `done` into `journal` — this one, or one that wraps it —
        and keep the status: running while it plays, then finished, or interrupted when anything
        stops it. A run another process plays is `RunInUse`, and nothing is played or written."""
        with self.held():
            self.write(Running())
            try:
                outcomes = await bench.run(agent, journal, done)
            except BaseException:  # Ctrl+C cancels the bench; a bug in convy stops it too
                self.write(Interrupted(datetime.now().astimezone()))
                raise
            self.write(Finished(datetime.now().astimezone()))
            return outcomes
