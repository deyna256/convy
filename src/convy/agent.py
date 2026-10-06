"""What convy needs from an agent, and the wrapper that limits the time of each of its steps."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol

from msgspec import Struct


class Message(Struct, frozen=True):
    """A message from the simulated user to the agent."""

    text: str


class Usage(Struct, frozen=True, tag="usage"):
    """Tokens the agent spent on one answer."""

    input: int
    output: int


class NoUsage(Struct, frozen=True, tag="no_usage"):
    """The agent did not report the tokens it spent."""


class Answer(Struct, frozen=True):
    """The agent's answer to a message."""

    text: str
    usage: Usage | NoUsage = NoUsage()


class AgentFailure(Exception):
    """A turn of the agent failed."""


class Conversation(Protocol):
    """One dialogue with an agent."""

    async def answer(self, message: Message) -> Answer:
        """Answer the message, or raise `AgentFailure` with the reason."""
        ...


class Agent(Protocol):
    """Anything convy can talk to."""

    def conversation(self) -> AbstractAsyncContextManager[Conversation]:
        """Open a new dialogue, independent of any other."""
        ...


class TimeLimited(Struct, frozen=True):
    """The same agent, with a limit on the time of each step: opening a conversation, a turn,
    closing it."""

    agent: Agent
    seconds: float

    @asynccontextmanager
    async def conversation(self) -> AsyncIterator[Conversation]:
        limit = asyncio.timeout(self.seconds)
        try:
            async with limit, self.agent.conversation() as conversation:
                limit.reschedule(None)  # turns have limits of their own
                try:
                    yield LimitedConversation(conversation, self.seconds)
                finally:
                    limit.reschedule(asyncio.get_running_loop().time() + self.seconds)
        except TimeoutError:
            if limit.expired():
                raise AgentFailure(
                    f"the conversation did not open or close in {self.seconds:g} s"
                ) from None
            raise


class LimitedConversation(Struct, frozen=True):
    """A conversation whose turns fail when they take longer than `seconds`."""

    conversation: Conversation
    seconds: float

    async def answer(self, message: Message) -> Answer:
        limit = asyncio.timeout(self.seconds)
        try:
            async with limit:
                return await self.conversation.answer(message)
        except TimeoutError:
            if limit.expired():
                raise AgentFailure(f"no answer in {self.seconds:g} s") from None
            raise
