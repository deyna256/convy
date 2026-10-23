"""What convy needs from an agent, and the wrappers that limit the time it has to open a
conversation, to answer each turn and to close it, and the conversations it holds at once."""

import asyncio
import math
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from datetime import datetime
from typing import Protocol

from msgspec import Struct

from convy.busy import Busy, Places


class Message(Struct, frozen=True):
    """A message from the simulated user to the agent."""

    text: str


class Reported(Struct, frozen=True, tag="reported"):
    """Text the agent reported; it may be empty, as a search that found nothing."""

    text: str


class NotReported(Struct, frozen=True, tag="not_reported"):
    """The agent did not report this: a text, or a count of tokens."""


class Usage(Struct, frozen=True, tag="usage"):
    """Tokens the agent spent on one answer. `input` holds every input token, those read from or
    written to the model's cache included, and `output` every output token, thinking included; a
    part the agent did not report is `NotReported()`."""

    input: int
    output: int
    thinking: int | NotReported = NotReported()  # part of output
    cache_read: int | NotReported = NotReported()  # part of input
    cache_write: int | NotReported = NotReported()  # part of input

    def __post_init__(self) -> None:
        thinking = self.counted(self.thinking)
        read, written = self.counted(self.cache_read), self.counted(self.cache_write)
        counts = (("input", self.input), ("output", self.output))
        for name, count in (*counts, ("cache_read", read), ("cache_write", written)):
            if count < 0:
                raise ValueError(f"{name} tokens cannot be below 0, got {count}")
        if not 0 <= thinking <= self.output:
            raise ValueError(
                f"thinking tokens must be from 0 to the output's {self.output}, got {thinking}"
            )
        if read + written > self.input:
            raise ValueError(
                f"cached tokens are part of the input: {read} read from the cache and {written} "
                f"written to it are more than the input's {self.input}; add them to the input, "
                "as Anthropic's input_tokens leaves them out"
            )

    def counted(self, count: int | NotReported) -> int:
        """A part as a count for the checks: 0 when it was not reported."""
        match count:
            case int():
                return count
            case NotReported():
                return 0


class NoUsage(Struct, frozen=True, tag="no_usage"):
    """The agent did not report the tokens it spent."""


class Thought(Struct, frozen=True, tag="thought"):
    """Something the agent thought, in its place among the steps of an answer."""

    text: str

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("a thought needs text")


class Call(Struct, frozen=True, tag="call", kw_only=True):
    """Something the agent called to give an answer: a model, a tool, a search. `started` is by
    the agent's own clock, with a time zone; `sent` and `received` are the text it sent and got
    back."""

    name: str
    started: datetime
    seconds: float
    usage: Usage | NoUsage = NoUsage()
    sent: Reported | NotReported = NotReported()
    received: Reported | NotReported = NotReported()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("a call needs a name")
        if self.started.utcoffset() is None:
            raise ValueError(
                f"call {self.name!r}: started needs a time zone, such as datetime.now(UTC)"
            )
        if not 0 <= self.seconds < math.inf:  # NaN fails too
            raise ValueError(
                f"call {self.name!r}: seconds must be a finite number, 0 or more, "
                f"got {self.seconds}"
            )


class Answer(Struct, frozen=True):
    """The agent's answer to a message: `text` is what it said, `usage` what it spent in all, and
    `steps` how it got there, in order: what it thought and what it called."""

    text: str
    usage: Usage | NoUsage = NoUsage()
    steps: tuple[Thought | Call, ...] = ()


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
    """The same agent, with a limit on the time it has to open a conversation, to answer each
    turn, and to close it."""

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


class QueuedAgent(Struct, frozen=True):
    """The same agent, holding a place of `places` while a conversation is open, from opening to
    closing. A conversation waits for its place before it opens, so the wait counts neither in an
    answer's time nor against a time limit inside; a service busy at opening leaves fewer places."""

    agent: Agent
    places: Places

    @asynccontextmanager
    async def conversation(self) -> AsyncIterator[Conversation]:
        async with self.places, AsyncExitStack() as opened:
            try:
                conversation = await opened.enter_async_context(self.agent.conversation())
            except Busy:
                self.places.busy()
                raise
            yield conversation


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
