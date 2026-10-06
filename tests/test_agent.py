import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

from convy.agent import AgentFailure, Answer, Conversation, Message, NoUsage, TimeLimited, Usage
from convy.fakes import Echo, EchoConversation, FakeAgent, FakeModel
from convy.model import Models
from convy.scenario import Scenario


class Slow:
    """An agent whose conversation takes `opening` seconds to open and `closing` to close."""

    def __init__(self, opening: float, closing: float):
        self.opening = opening
        self.closing = closing

    @asynccontextmanager
    async def conversation(self) -> AsyncIterator[Conversation]:
        await asyncio.sleep(self.opening)
        try:
            yield EchoConversation()
        finally:
            await asyncio.sleep(self.closing)


SLOW = [Slow(opening=1, closing=0), Slow(opening=0, closing=1)]


@pytest.mark.parametrize("agent", SLOW)
async def test_time_limited_fails_a_slow_opening_or_closing(agent: Slow):
    with pytest.raises(AgentFailure, match=r"did not open or close in 0\.05 s"):
        async with TimeLimited(agent, 0.05).conversation() as conversation:
            await conversation.answer(Message("hello"))


@pytest.mark.parametrize("agent", SLOW)
async def test_a_slow_opening_or_closing_fails_the_attempt(agent: Slow):
    scenario = Scenario("greet", 1, "Say hi.", ("greets",))
    models = Models(user=FakeModel("hi"), judge=FakeModel('{"pass": true}'))
    outcome = await scenario.outcome(TimeLimited(agent, 0.05), models, attempt=1)
    assert outcome.stop == "agent_failure"


async def test_time_limited_gives_turns_their_own_limit():
    agent = Slow(opening=0.03, closing=0.03)
    async with TimeLimited(agent, 0.05).conversation() as conversation:
        await asyncio.sleep(0.1)  # time between turns is not limited
        assert await conversation.answer(Message("hi")) == Answer("hi", Usage(2, 2))
    async with TimeLimited(FakeAgent("late", delay=1), 0.05).conversation() as conversation:
        with pytest.raises(AgentFailure, match=r"no answer in 0\.05 s"):
            await conversation.answer(Message("hello"))


async def test_time_limited_passes_an_error_of_the_body():
    with pytest.raises(KeyError, match="mine"):
        async with TimeLimited(Echo(), 5).conversation():
            raise KeyError("mine")


async def test_time_limited_fails_a_slow_turn():
    async with TimeLimited(FakeAgent("late", delay=1), 0.05).conversation() as conversation:
        with pytest.raises(AgentFailure, match=r"no answer in 0\.05 s"):
            await conversation.answer(Message("hello"))


async def test_time_limited_passes_a_timeout_of_the_agent_itself():
    async with TimeLimited(FakeAgent(TimeoutError("inner")), 5).conversation() as conversation:
        with pytest.raises(TimeoutError, match="inner"):
            await conversation.answer(Message("hello"))


async def test_answer_without_usage_has_no_usage():
    assert Answer("hi").usage == NoUsage()


async def test_echo_answers_with_the_message_and_its_length():
    async with Echo().conversation() as conversation:
        assert await conversation.answer(Message("hello")) == Answer("hello", Usage(5, 5))


async def test_fake_agent_repeats_its_last_step_and_starts_over_per_conversation():
    agent = FakeAgent("one", "two")
    async with agent.conversation() as conversation:
        texts = [(await conversation.answer(Message("?"))).text for _ in range(3)]
    async with agent.conversation() as conversation:
        texts.append((await conversation.answer(Message("?"))).text)
    assert texts == ["one", "two", "two", "one"]
    assert agent.opened == 2


def test_fake_agent_needs_a_step():
    with pytest.raises(ValueError, match="at least one step"):
        FakeAgent()
