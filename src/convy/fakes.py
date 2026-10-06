"""Simple working stand-ins for convy's interfaces, for tests: yours and convy's own."""

import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from msgspec import Struct

from convy.agent import Answer, Conversation, Message, Usage
from convy.model import ModelFailure
from convy.scenario import Outcome

type Step = str | Answer | BaseException


class FakeAgent:
    """An agent that answers from a list of steps.

    A step is a string, an `Answer`, or an exception to raise on that turn. After the last step the
    agent repeats it. Every conversation starts the list over. Each answer takes `delay` seconds.
    `opened` counts the conversations opened, `peak` the most that were open at once.
    """

    def __init__(self, *steps: Step, delay: float = 0):
        if not steps:
            raise ValueError("FakeAgent needs at least one step")
        self.steps = steps
        self.delay = delay
        self.opened = 0
        self.peak = 0
        self.open = 0

    @asynccontextmanager
    async def conversation(self) -> AsyncIterator[Conversation]:
        self.opened += 1
        self.open += 1
        self.peak = max(self.peak, self.open)
        try:
            yield FakeConversation(self.steps, self.delay)
        finally:
            self.open -= 1


class FakeConversation:
    """A conversation of `FakeAgent`."""

    def __init__(self, steps: Sequence[Step], delay: float):
        self.steps = steps
        self.delay = delay
        self.turns = 0

    async def answer(self, message: Message) -> Answer:
        step = self.steps[min(self.turns, len(self.steps) - 1)]
        self.turns += 1
        await asyncio.sleep(self.delay)  # even at 0, other conversations get to run
        if isinstance(step, BaseException):
            raise step
        return Answer(step) if isinstance(step, str) else step


class Echo(Struct, frozen=True):
    """An agent that answers with the user's message; its tokens are the message's length."""

    @asynccontextmanager
    async def conversation(self) -> AsyncIterator[Conversation]:
        yield EchoConversation()


class EchoConversation(Struct, frozen=True):
    """A conversation of `Echo`."""

    async def answer(self, message: Message) -> Answer:
        length = len(message.text)
        return Answer(message.text, Usage(input=length, output=length))


class FakeModel:
    """A model that replies from a list: a step is a string, or an exception to raise.

    The list runs across all calls, and the last step repeats. Its `name` is `"fake"`.
    """

    name = "fake"

    def __init__(self, *steps: str | ModelFailure):
        if not steps:
            raise ValueError("FakeModel needs at least one step")
        self.steps = steps
        self.calls: list[list[dict[str, str]]] = []

    async def reply(self, messages: list[dict[str, str]]) -> str:
        step = self.steps[min(len(self.calls), len(self.steps) - 1)]
        self.calls.append(list(messages))
        if isinstance(step, ModelFailure):
            raise step
        return step


class MemoryJournal:
    """A journal that keeps outcomes in memory, in `outcomes`."""

    def __init__(self) -> None:
        self.outcomes: list[Outcome] = []

    def record(self, outcome: Outcome) -> None:
        self.outcomes.append(outcome)
