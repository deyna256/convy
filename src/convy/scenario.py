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
from convy.dialog import (
    Failed,
    Finished,
    Judge,
    NoVerdict,
    SimulatedUser,
    Transcript,
    Turn,
    Verdict,
)
from convy.model import Contained, ModelFailure, Models

type Stop = Literal["user_stop", "max_turns", "agent_failure", "model_failure"]


class Outcome(Struct, frozen=True):
    """The result of one attempt: the dialogue, the verdict, and why the dialogue stopped."""

    scenario: str
    attempt: int
    claims: tuple[str, ...]
    transcript: Transcript
    verdict: Verdict | Failed | NoVerdict
    stop: Stop


class Scenario(Struct, frozen=True, forbid_unknown_fields=True):
    """A scenario, as written in `scenarios/<id>.yaml`: `user` holds the simulated user's
    instructions and `judge` the claims that must all hold."""

    id: str
    max_turns: int
    instructions: str = field(name="user")
    claims: tuple[str, ...] = field(name="judge")

    def __post_init__(self) -> None:
        if self.max_turns < 1:
            raise ValueError(f"max_turns must be at least 1, got {self.max_turns}")
        if not self.claims:
            raise ValueError("judge must list at least one claim")

    async def outcome(self, agent: Agent, models: Models, attempt: int) -> Outcome:
        """Play the scenario once against the agent."""
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
                                await self.turn(conversation, message)
                            )
        except ModelFailure as failure:
            return self.ended(attempt, transcript, NoVerdict(str(failure)), "model_failure")
        except TurnFailed as failed:
            return self.failed(attempt, transcript.with_turn(failed.turn), str(failed))
        except Exception as error:  # opening or closing the conversation is the agent's code too
            return self.failed(attempt, transcript, self.agent_error(error))
        try:
            verdict = await Judge(Contained(models.judge)).verdict(transcript, self.claims)
        except ModelFailure as failure:
            return self.ended(attempt, transcript, NoVerdict(str(failure)), "model_failure")
        return self.ended(attempt, transcript, verdict, stop)

    async def turn(self, conversation: Conversation, message: Message) -> Turn:
        start = time.monotonic()
        try:
            answer = self.checked(await conversation.answer(message))
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
        return Outcome(self.id, attempt, self.claims, transcript, verdict, stop)


class TurnFailed(Exception):
    """A turn of the agent failed; `turn` records the message and the error."""

    def __init__(self, turn: Turn):
        super().__init__(turn.answer.text)
        self.turn = turn


class Scenarios(Struct, frozen=True):
    """Every `*.yaml` scenario in a directory, checked as it is read."""

    directory: Path

    def __iter__(self) -> Iterator[Scenario]:
        seen: set[str] = set()
        for path in sorted(self.directory.glob("*.yaml")):
            try:
                scenario = msgspec.convert(
                    yamlrocks.loads(path.read_text(encoding="utf-8")), Scenario
                )
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
