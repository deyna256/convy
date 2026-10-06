"""The `convy` command: `init`, `run` and `report`. It prints, and it picks the exit code."""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

from msgspec import Struct
from pydantic import BaseModel, Field, ValidationError
from pydantic_settings import (
    BaseSettings,
    CliApp,
    CliPositionalArg,
    CliSubCommand,
    SettingsConfigDict,
)

from convy.agent import NoUsage, TimeLimited, Usage
from convy.bench import Bench, Journal, JsonlJournal, RunHeader
from convy.dialog import NoVerdict, Verdict
from convy.fakes import FakeModel, MemoryJournal
from convy.model import Models
from convy.project import Project, ProjectAgent
from convy.scenario import Matching, Outcome, Scenario

SMOKE = Scenario(
    id="smoke",
    max_turns=2,
    instructions="Greet the assistant and ask what it can help with, then thank it.",
    claims=("The agent answered the greeting",),
)


class Printed(Struct, frozen=True):
    """A journal that also prints each outcome as it is recorded."""

    journal: Journal

    def record(self, outcome: Outcome) -> None:
        self.journal.record(outcome)
        match outcome.verdict:
            case Verdict(passed=True):
                mark = "✓"
            case Verdict():
                mark = "✗"
            case NoVerdict():
                mark = "?"
        seconds = sum(turn.seconds for turn in outcome.transcript.turns)
        print(f"  {mark} {outcome.scenario} #{outcome.attempt}  {seconds:.1f} s  {outcome.stop}")


class Invalid(Struct, frozen=True):
    """Settings that failed validation, as the command shows them: where and what, never the
    values read, since they may be keys."""

    error: ValidationError

    def show(self) -> None:
        for found in self.error.errors(include_input=False, include_url=False):
            field = ".".join(str(part) for part in found["loc"])
            print(f"error: {self.error.title}: {field}: {found['msg']}", file=sys.stderr)


class Rebuilt(Struct, frozen=True):
    """A project's report, written again from its journals, as the command shows it."""

    project: Project

    def show(self) -> None:
        for path in self.project.report():
            print(
                f"skipped unreadable lines or a whole journal: {self.project.runs() / path}",
                file=sys.stderr,
            )
        print(f"report: {self.project.page()}")


class InitCommand(BaseModel):
    path: CliPositionalArg[Path] = Path(".")

    def cli_cmd(self) -> None:
        created = Project(self.path).init()
        for path in created:
            print(f"created {path}")
        print(
            "nothing to create: every file exists"
            if not created
            else "next: convy run echo --smoke"
        )


class RunCommand(BaseModel):
    agents: CliPositionalArg[list[str]]
    k: int = Field(1, ge=1, description="attempts per scenario")
    scenarios: str = Field("*", description="only scenarios whose id matches this mask")
    parallel: int = Field(4, ge=1, description="conversations at once")
    turn_timeout: float = Field(
        600,
        gt=0,
        description="seconds for each step of the agent: opening a conversation, a turn, closing",
    )
    smoke: bool = Field(False, description="check the connection to the agent; no models called")

    def cli_cmd(self) -> None:
        project = Project(Path.cwd())
        try:
            agents = [project.agent(name) for name in self.agents]
            benches = [self.bench(project) for _ in agents]
        except ValidationError as error:  # settings in the project's files
            Invalid(error).show()
            raise SystemExit(2) from None
        except Exception as error:  # anything else wrong in the project's files
            print(f"error: {error}", file=sys.stderr)
            raise SystemExit(2) from None
        failed = False
        for loaded, bench in zip(agents, benches, strict=True):
            outcomes = asyncio.run(self.played(project, bench, loaded))
            failed |= any(o.stop in ("agent_failure", "model_failure") for o in outcomes)
        if not self.smoke:
            Rebuilt(project).show()
        raise SystemExit(int(failed))

    def bench(self, project: Project) -> Bench:
        """A bench for one agent, with models of its own: a fake model's replies run on across its
        calls, and a project's models are built fresh by running `models.py`."""
        if self.smoke:
            user = FakeModel("Hello! What can you help me with?", "Thank you!")
            return Bench((SMOKE,), Models(user, FakeModel('{"pass": true, "reason": "smoke"}')))
        scenarios = tuple(Matching(project.scenarios(), self.scenarios))
        return Bench(scenarios, project.models(), self.k, self.parallel)

    async def played(
        self, project: Project, bench: Bench, loaded: ProjectAgent
    ) -> tuple[Outcome, ...]:
        agent = TimeLimited(loaded.agent, self.turn_timeout)
        if self.smoke:
            print(f"{loaded.name}: checking the connection")
            (outcome,) = await bench.run(agent, MemoryJournal())
            self.smoked(outcome)
            return (outcome,)
        header = RunHeader(
            agent=loaded.name,
            version=loaded.version,
            user=bench.models.user.name,
            judge=bench.models.judge.name,
            attempts=bench.attempts,
            planned=bench.planned(),
            started=datetime.now().astimezone(),
        )
        print(f"{loaded.name}: {len(bench.scenarios)} scenarios, {bench.attempts} attempts each")
        return await bench.run(agent, Printed(JsonlJournal(project.runs(), header)))

    def smoked(self, outcome: Outcome) -> None:
        for turn in outcome.transcript.turns:
            match turn.answer.usage:
                case Usage(input=spent, output=produced):
                    tokens = f", {spent} / {produced} tokens"
                case NoUsage():
                    tokens = ""
            print(f"  agent ({turn.seconds:.1f} s{tokens}): {turn.answer.text[:200]}")
        match outcome:
            case Outcome(stop="agent_failure", verdict=Verdict(reason=reason)):
                print(f"connection failed: {reason}")
            case _:
                print("connection works")


class ReportCommand(BaseModel):
    def cli_cmd(self) -> None:
        Rebuilt(Project(Path.cwd())).show()


class Convy(BaseSettings):
    """Check conversational agents with a simulated user and a judge."""

    model_config = SettingsConfigDict(
        cli_prog_name="convy",
        cli_kebab_case=True,
        cli_implicit_flags=True,
        cli_enforce_required=True,
    )
    init: CliSubCommand[InitCommand] = Field(description="create a project with examples")
    run: CliSubCommand[RunCommand] = Field(description="play scenarios against agents")
    report: CliSubCommand[ReportCommand] = Field(description="rebuild results/index.html")

    def cli_cmd(self) -> None:
        CliApp.run_subcommand(self)


def main(argv: list[str] | None = None) -> None:
    """The command's entry point."""
    try:
        CliApp.run(Convy, cli_args=argv)  # None: sys.argv[1:]
    except ValidationError as error:
        Invalid(error).show()
        raise SystemExit(2) from None
