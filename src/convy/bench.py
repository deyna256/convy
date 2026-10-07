"""A run: every scenario played against an agent, each outcome written to the run's folder."""

import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

import msgspec
from msgspec import Struct

from convy.agent import Agent
from convy.model import Models
from convy.scenario import Outcome, Scenario

type Pair = tuple[str, int]  # a scenario's id and an attempt's number


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
    convy: str = ""
    files: Files = Files()

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

    format: Literal[2]
    spec: RunSpec
    status: Status


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

    def planned(self) -> int:
        return len(self.scenarios) * self.attempts

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

    def write(self, status: Status) -> None:
        temporary = self.folder() / "run.json.tmp"
        temporary.write_bytes(msgspec.json.encode(RunFile(2, self.spec, status)))
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
        stops it."""
        self.write(Running())
        try:
            outcomes = await bench.run(agent, journal, done)
        except BaseException:  # Ctrl+C cancels the bench; a bug in convy stops it too
            self.write(Interrupted(datetime.now().astimezone()))
            raise
        self.write(Finished(datetime.now().astimezone()))
        return outcomes
