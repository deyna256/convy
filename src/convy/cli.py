"""The `convy` command: `init`, `run`, `resume`, `report` and `compare`. It prints and picks the
exit code."""

import asyncio
import secrets
import sys
from datetime import datetime
from importlib.metadata import version
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

from convy.agent import Agent, NoUsage, TimeLimited, Usage
from convy.bench import Bench, Files, Finished, Journal, Pair, RunJournal, RunSpec
from convy.dialog import ChatJudge, Failed, NoVerdict, Verdict
from convy.fakes import FakeModel, MemoryJournal
from convy.model import Models
from convy.project import Project, ProjectAgent
from convy.report import Runs
from convy.scenario import Matching, Outcome, Scenario

SMOKE = Scenario(
    id="smoke",
    max_turns=2,
    instructions="Greet the assistant and ask what it can help with, then thank it.",
    claims=("The agent answered the greeting",),
)


class Printed(Struct, frozen=True):
    """A journal that also prints each outcome as it is recorded; one the judge was not sure
    enough of, at the run's `trust`, is marked "not trusted"."""

    journal: Journal
    trust: float

    def record(self, outcome: Outcome) -> None:
        self.journal.record(outcome)
        note = ""
        match outcome.verdict:
            case Verdict() as verdict if not verdict.decided(self.trust):
                mark, note = "?", "  not trusted"
            case Verdict(passed=True):
                mark = "✓"
            case Verdict() | Failed():
                mark = "✗"
            case NoVerdict():
                mark = "?"
        seconds = sum(turn.seconds for turn in outcome.transcript.turns)
        line = f"  {mark} {outcome.scenario} #{outcome.attempt}  {seconds:.1f} s  {outcome.stop}"
        print(line + note)


class Invalid(Struct, frozen=True):
    """Settings that failed validation, as the command shows them: where and what, never the
    values read, since they may be keys."""

    error: ValidationError

    def show(self) -> None:
        for found in self.error.errors(include_input=False, include_url=False):
            field = ".".join(str(part) for part in found["loc"])
            print(f"error: {self.error.title}: {field}: {found['msg']}", file=sys.stderr)


class Rebuilt(Struct, frozen=True):
    """A project's report, written again from its runs, as the command shows it."""

    project: Project

    def show(self) -> None:
        if self.project.old_journals():
            print(
                f"{self.project.results() / 'runs'} holds journals of convy 0.1, which this "
                "version does not read; run the agents again",
                file=sys.stderr,
            )
        for path in self.project.report():
            print(
                f"skipped unreadable lines or a whole run: {self.project.results() / path}",
                file=sys.stderr,
            )
        print(f"index: {self.project.index()}")


class Recorded(Struct, frozen=True):
    """A run played into its folder, as the command shows it: on Ctrl+C it says what was
    recorded and how to continue, rebuilds the report and exits with 130."""

    project: Project
    journal: RunJournal

    def outcomes(
        self, bench: Bench, agent: Agent, done: frozenset[Pair] = frozenset()
    ) -> tuple[Outcome, ...]:
        try:
            printed = Printed(self.journal, self.journal.spec.trust)
            return asyncio.run(self.journal.play(bench, agent, printed, done))
        except KeyboardInterrupt:
            spec = self.journal.spec
            run = Runs(self.project.results()).read(self.journal.folder())
            print(f"interrupted: {len(run.done())} of {len(spec.pairs())} attempts recorded")
            print(f"resume with: convy resume {spec.short()}")
            Rebuilt(self.project).show()
            print(f"report: {self.project.report_page(spec)}")
            raise SystemExit(130) from None


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
    trust: float = Field(
        0.0,
        ge=0,
        le=1,
        description="cut out the judge's decisions it is less sure of than this, from 0 to 1",
    )
    smoke: bool = Field(False, description="check the connection to the agent; no models called")

    def cli_cmd(self) -> None:
        project = Project(Path())
        try:
            agents = [project.agent(name) for name in self.agents]
            benches = [self.bench(project) for _ in agents]
            fingerprints = [project.files(loaded.name) for loaded in agents]
        except ValidationError as error:  # settings in the project's files
            Invalid(error).show()
            raise SystemExit(2) from None
        except Exception as error:  # anything else wrong in the project's files
            print(f"error: {error}", file=sys.stderr)
            raise SystemExit(2) from None
        failed = False
        played = []
        for loaded, bench, files in zip(agents, benches, fingerprints, strict=True):
            agent = TimeLimited(loaded.agent, self.turn_timeout)
            if self.smoke:
                outcomes = asyncio.run(self.smoked(bench, agent, loaded.name))
            else:
                journal = self.journal(project, bench, loaded, files)
                outcomes = Recorded(project, journal).outcomes(bench, agent)
                played.append(journal.spec)
            failed |= any(outcome.failed() for outcome in outcomes)
        if not self.smoke:
            Rebuilt(project).show()
            for spec in played:
                print(f"report: {project.report_page(spec)}")
        raise SystemExit(int(failed))

    def bench(self, project: Project) -> Bench:
        """A bench for one agent, with models of its own: a fake model's replies run on across its
        calls, and a project's models are built fresh by running `models.py`."""
        if self.smoke:
            user = FakeModel("Hello! What can you help me with?", "Thank you!")
            judge = ChatJudge(FakeModel('{"claims": [{"pass": true, "reason": "smoke"}]}'))
            return Bench((SMOKE,), Models(user, judge))
        scenarios = tuple(Matching(project.scenarios(), self.scenarios))
        return Bench(scenarios, project.models(), self.k, self.parallel)

    def journal(
        self, project: Project, bench: Bench, loaded: ProjectAgent, files: Files
    ) -> RunJournal:
        """The folder of a new run of the agent, created with its specification."""
        started = datetime.now().astimezone()
        spec = RunSpec(
            id=f"{started:%Y-%m-%dT%H-%M-%S}_{secrets.token_hex(2)}",
            agent=loaded.name,
            version=loaded.version,
            user=bench.models.user.name,
            judge=bench.models.judge.name,
            k=bench.attempts,
            parallel=bench.parallel,
            turn_timeout=self.turn_timeout,
            trust=self.trust,
            scenarios=bench.scenarios,
            started=started,
            convy=version("convy"),
            files=files,
        )
        journal = RunJournal(project.results(), spec)
        journal.create()  # ponytail: an id clash is an error; draw a new id if it ever happens
        print(
            f"{loaded.name}: run {spec.id}, {len(bench.scenarios)} scenarios, "
            f"{bench.attempts} attempts each"
        )
        return journal

    async def smoked(self, bench: Bench, agent: Agent, name: str) -> tuple[Outcome, ...]:
        print(f"{name}: checking the connection")
        (outcome,) = await bench.run(agent, MemoryJournal())
        for turn in outcome.transcript.turns:
            match turn.answer.usage:
                case Usage(input=spent, output=produced):
                    tokens = f", {spent} / {produced} tokens"
                case NoUsage():
                    tokens = ""
            print(f"  agent ({turn.seconds:.1f} s{tokens}): {turn.answer.text[:200]}")
        match outcome:
            case Outcome(verdict=Failed(reason=reason)):
                print(f"connection failed: {reason}")
            case _:
                print("connection works")
        return (outcome,)


class ResumeCommand(BaseModel):
    run: CliPositionalArg[str] = Field(description="the run's id, or its random part")

    def cli_cmd(self) -> None:
        project = Project(Path())
        try:
            run = Runs(project.results()).run(self.run)
            spec = run.spec
            match run.status:
                case Finished():
                    raise ValueError(f"run {spec.id} is finished; there is nothing to resume")
            loaded = project.agent(spec.agent)
            models = project.models()
            files = project.files(spec.agent)
            changes = spec.changes(loaded.version, models.user.name, models.judge.name, files)
            if changes:
                raise ValueError(f"run {self.run} cannot resume: {'; '.join(changes)}")
        except ValidationError as error:  # settings in the project's files
            Invalid(error).show()
            raise SystemExit(2) from None
        except Exception as error:  # anything else wrong in the run or the project's files
            print(f"error: {error}", file=sys.stderr)
            raise SystemExit(2) from None
        print(
            f"{spec.agent}: resuming run {spec.id}, "
            f"{len(run.done())} of {len(spec.pairs())} attempts recorded"
        )
        bench = Bench(spec.scenarios, models, spec.k, spec.parallel)
        agent = TimeLimited(loaded.agent, spec.turn_timeout)
        journal = RunJournal(project.results(), spec)
        outcomes = Recorded(project, journal).outcomes(bench, agent, run.done())
        Rebuilt(project).show()
        print(f"report: {project.report_page(spec)}")
        raise SystemExit(int(any(outcome.failed() for outcome in outcomes)))


class ReportCommand(BaseModel):
    def cli_cmd(self) -> None:
        Rebuilt(Project(Path())).show()


class CompareCommand(BaseModel):
    before: CliPositionalArg[str] = Field(description="the run to compare with: id or random part")
    after: CliPositionalArg[str] = Field(description="the run that may have changed")

    def cli_cmd(self) -> None:
        project = Project(Path())
        runs = Runs(project.results())
        try:
            before, after = runs.run(self.before), runs.run(self.after)
        except ValueError as error:  # no such run, or several
            print(f"error: {error}", file=sys.stderr)
            raise SystemExit(2) from None
        print(f"comparison: {project.compare(before, after)}")


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
    resume: CliSubCommand[ResumeCommand] = Field(
        description="play the rest of a run that was stopped, exactly as it started"
    )
    report: CliSubCommand[ReportCommand] = Field(description="rebuild the pages in results/")
    compare: CliSubCommand[CompareCommand] = Field(
        description="write a page that compares two runs: before, then after"
    )

    def cli_cmd(self) -> None:
        CliApp.run_subcommand(self)


def main(argv: list[str] | None = None) -> None:
    """The command's entry point."""
    try:
        CliApp.run(Convy, cli_args=argv)  # None: sys.argv[1:]
    except ValidationError as error:
        Invalid(error).show()
        raise SystemExit(2) from None
