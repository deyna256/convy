"""A run: every scenario played against an agent, each outcome written to a journal."""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Protocol

import msgspec
from msgspec import Struct

from convy.agent import Agent
from convy.model import Models
from convy.scenario import Outcome, Scenario


class RunHeader(Struct, frozen=True):
    """What a run was: the agent and its version, the models, how many attempts were planned."""

    agent: str
    version: str
    user: str
    judge: str
    attempts: int
    planned: int
    started: datetime


class Journal(Protocol):
    """Where outcomes go as soon as they are ready."""

    def record(self, outcome: Outcome) -> None: ...


class JsonlJournal(Struct, frozen=True):
    """A run's file, `<directory>/<agent>/<start>.jsonl`: the header, then a line per attempt.

    The file is created on the first `record`, so a run that never got an outcome leaves no file.
    """

    directory: Path
    header: RunHeader

    def path(self) -> Path:
        name = self.header.started.strftime("%Y-%m-%dT%H-%M-%S.%f")  # unique per run
        return self.directory / self.header.agent / f"{name}.jsonl"

    def record(self, outcome: Outcome) -> None:
        path = self.path()
        lines = [msgspec.json.encode(outcome)]
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            lines.insert(0, msgspec.json.encode(self.header))
        with path.open("ab") as file:
            file.write(b"".join(line + b"\n" for line in lines))


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

    async def run(self, agent: Agent, journal: Journal) -> tuple[Outcome, ...]:
        """Play every scenario `attempts` times, at most `parallel` conversations at once."""
        limit = asyncio.Semaphore(self.parallel)
        async with asyncio.TaskGroup() as group:
            tasks = [
                group.create_task(self.played(scenario, attempt, agent, journal, limit))
                for scenario in self.scenarios
                for attempt in range(1, self.attempts + 1)
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
