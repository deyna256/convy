"""Scenarios, and the attempt in which one is played against an agent."""

import time
from collections.abc import Iterable, Iterator
from fnmatch import fnmatch
from pathlib import Path
from typing import Literal

import msgspec
import yamlrocks
from msgspec import Struct, field

from convy.agent import Agent, AgentFailure, Answer, Conversation, Message
from convy.busy import Busy, Places
from convy.dialog import (
    Checked,
    Failed,
    Finished,
    NoVerdict,
    SimulatedUser,
    Transcript,
    Turn,
    Verdict,
)
from convy.model import Contained, ModelFailure, Models

type Stop = Literal["user_stop", "max_turns", "agent_failure", "agent_busy", "model_failure"]


class Outcome(Struct, frozen=True):
    """The result of one attempt: the dialogue, the verdict, and why the dialogue stopped. The
    claims' texts are the scenario's; a verdict holds the judge's decisions in their order."""

    scenario: str
    attempt: int
    transcript: Transcript
    verdict: Verdict | Failed | NoVerdict
    stop: Stop

    def failed(self) -> bool:
        """Whether the agent or convy's model failed, or the agent's service stayed busy."""
        return self.stop in ("agent_failure", "agent_busy", "model_failure")


class Requirement(Struct, frozen=True, forbid_unknown_fields=True):
    """A claim to judge, optionally required for the attempt to pass."""

    text: str = field(name="claim")
    required: bool = False


class Score(Struct, frozen=True, kw_only=True):
    """The effective claims held, and the run's rule for passing this attempt."""

    held: int
    total: int
    required_failed: tuple[int, ...]
    threshold: float

    @property
    def fraction(self) -> float:
        return self.held / self.total

    @property
    def passed(self) -> bool:
        return not self.required_failed and self.fraction >= self.threshold


class Scenario(Struct, frozen=True, forbid_unknown_fields=True):
    """A scenario's user instructions and requirements, in judge order."""

    id: str
    max_turns: int
    instructions: str = field(name="user")
    claims: tuple[Requirement, ...] = field(name="judge")

    def __post_init__(self) -> None:
        if self.max_turns < 1:
            raise ValueError(f"max_turns must be at least 1, got {self.max_turns}")
        if not self.claims:
            raise ValueError("judge must list at least one claim")

    def score(self, verdict: Verdict, trust: float = 0, threshold: float = 1) -> Score:
        """All claims have equal weight; required claims must also hold individually."""
        if not 0 <= trust <= 1:
            raise ValueError(f"trust must be from 0 to 1, got {trust}")
        if not 0 <= threshold <= 1:
            raise ValueError(f"threshold must be from 0 to 1, got {threshold}")
        held = tuple(claim.holds(trust) for claim in verdict.claims)
        required_failed = tuple(
            number
            for number, (requirement, holds) in enumerate(zip(self.claims, held, strict=True), 1)
            if requirement.required and not holds
        )
        return Score(
            held=sum(held),
            total=len(self.claims),
            required_failed=required_failed,
            threshold=threshold,
        )

    async def outcome(self, agent: Agent, models: Models, attempt: int, places: Places) -> Outcome:
        """Play the scenario once against the agent, whose `places` wait for its busy service."""
        user = SimulatedUser(Contained(models.user), self.instructions)
        transcript = Transcript()
        stop: Stop = "max_turns"
        try:
            async with agent.conversation() as conversation:
                for _ in range(self.max_turns):
                    match await user.next(transcript):
                        case Finished():
                            stop = "user_stop"
                            break
                        case Message() as message:
                            transcript = transcript.with_turn(
                                await places.retry(lambda: self.turn(conversation, message))
                            )
        except ModelFailure as failure:
            return self.ended(attempt, transcript, NoVerdict(str(failure)), "model_failure")
        except Busy as busy:
            reason = f"the agent's service stayed busy: {busy}"
            return self.ended(attempt, transcript, NoVerdict(reason), "agent_busy")
        except TurnFailed as failed:
            return self.failed(attempt, transcript.with_turn(failed.turn), str(failed))
        except Exception as error:  # opening or closing the conversation is the agent's code too
            return self.failed(attempt, transcript, self.agent_error(error))
        try:
            decided = await Checked(models.judge).decide(
                transcript, tuple(claim.text for claim in self.claims)
            )
        except ModelFailure as failure:
            return self.ended(attempt, transcript, NoVerdict(str(failure)), "model_failure")
        return self.ended(attempt, transcript, Verdict(decided), stop)

    async def turn(self, conversation: Conversation, message: Message) -> Turn:
        """One try of a turn, timed alone, so that waiting for a busy service is not answering."""
        start = time.monotonic()
        try:
            answer = self.checked(await conversation.answer(message))
        except Busy:
            raise
        except Exception as error:  # the agent's code: any bug is a failed turn
            failed = Turn(message, Answer(self.agent_error(error)), time.monotonic() - start)
            raise TurnFailed(failed) from error
        return Turn(message, answer, time.monotonic() - start)

    def checked(self, answer: Answer) -> Answer:
        """The agent's answer, written and read back as the journal does."""
        try:
            return msgspec.json.decode(msgspec.json.encode(answer), type=Answer)
        except (
            msgspec.ValidationError,
            msgspec.EncodeError,
            TypeError,
            UnicodeEncodeError,
        ) as error:
            raise AgentFailure(f"the answer is not a valid Answer: {error}") from error

    def agent_error(self, error: Exception) -> str:
        return f"[agent error: {type(error).__name__}: {error}]"

    def failed(self, attempt: int, transcript: Transcript, error: str) -> Outcome:
        """An agent that failed does not pass, whatever was said before: the judge is not asked."""
        return self.ended(attempt, transcript, Failed(error), "agent_failure")

    def ended(
        self,
        attempt: int,
        transcript: Transcript,
        verdict: Verdict | Failed | NoVerdict,
        stop: Stop,
    ) -> Outcome:
        return Outcome(self.id, attempt, transcript, verdict, stop)


class TurnFailed(Exception):
    """A turn of the agent failed; `turn` records the message and the error."""

    def __init__(self, turn: Turn):
        super().__init__(turn.answer.text)
        self.turn = turn


class ScenarioInput(Struct, frozen=True, forbid_unknown_fields=True):
    """The YAML boundary, where a plain text claim is shorthand for a requirement."""

    id: str
    max_turns: int
    instructions: str = field(name="user")
    claims: tuple[str | Requirement, ...] = field(name="judge")

    def scenario(self) -> Scenario:
        claims = []
        for claim in self.claims:
            match claim:
                case str():
                    claims.append(Requirement(claim))
                case Requirement():
                    claims.append(claim)
        return Scenario(self.id, self.max_turns, self.instructions, tuple(claims))


class Scenarios(Struct, frozen=True):
    """Every `*.yaml` scenario in a directory and the folders under it, checked as it is read."""

    directory: Path

    def __iter__(self) -> Iterator[Scenario]:
        seen: set[str] = set()
        for path in sorted(self.directory.rglob("*.yaml")):
            try:
                scenario = msgspec.convert(
                    yamlrocks.loads(path.read_text(encoding="utf-8")), ScenarioInput
                ).scenario()
            except ValueError as error:  # YAML and validation errors are both ValueError
                raise ValueError(f"{path}: {error}") from error
            if scenario.id in seen:
                raise ValueError(f"{path}: another scenario already has the id {scenario.id!r}")
            seen.add(scenario.id)
            yield scenario


class Matching(Struct, frozen=True):
    """The scenarios whose id matches a mask such as `refund-*`."""

    scenarios: Iterable[Scenario]
    mask: str

    def __iter__(self) -> Iterator[Scenario]:
        matching = [s for s in self.scenarios if fnmatch(s.id, self.mask)]
        if not matching:
            raise ValueError(f"no scenario matches {self.mask!r}")
        return iter(matching)
