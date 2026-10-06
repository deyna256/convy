"""The promises every `Agent` keeps, checked on each implementation convy ships."""

import httpx2
import pytest

from convy.agent import Agent, AgentFailure, Answer, Message, TimeLimited
from convy.fakes import Echo, FakeAgent
from convy.http import JsonAgent, JsonEndpoint


def json_agent(status: int = 200) -> JsonAgent:
    service = httpx2.MockTransport(lambda request: httpx2.Response(status, json={"reply": "hi"}))
    endpoint = JsonEndpoint("https://agent.test/chat", pauses=(), transport=service)
    return JsonAgent(endpoint, body={"message": "{text}"}, reply="reply")


AGENTS = {
    "JsonAgent": json_agent,
    "FakeAgent": lambda: FakeAgent("hi"),
    "Echo": lambda: Echo(),
    "TimeLimited": lambda: TimeLimited(Echo(), 5),
}


@pytest.fixture(params=AGENTS)
def agent(request: pytest.FixtureRequest) -> Agent:
    return AGENTS[request.param]()


async def test_answer_is_an_answer(agent: Agent):
    async with agent.conversation() as conversation:
        assert isinstance(await conversation.answer(Message("hello")), Answer)


async def test_conversations_are_independent(agent: Agent):
    async with agent.conversation() as first, agent.conversation() as second:
        one = await first.answer(Message("hello"))
        two = await second.answer(Message("hello"))
    assert one == two


async def test_failed_turn_is_agent_failure():
    down = FakeAgent(AgentFailure("down"))
    for agent in (down, TimeLimited(down, 5), json_agent(status=400)):
        async with agent.conversation() as conversation:
            with pytest.raises(AgentFailure):
                await conversation.answer(Message("hello"))
