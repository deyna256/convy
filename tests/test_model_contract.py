"""The promises every `Model` keeps, checked on each implementation convy ships."""

import httpx2
import pytest

from convy.fakes import FakeModel
from convy.http import JsonEndpoint
from convy.model import Model, ModelFailure, OpenAiModel

CHAT = {"choices": [{"message": {"content": "hi"}}]}


def open_ai(status: int = 200) -> OpenAiModel:
    service = httpx2.MockTransport(lambda request: httpx2.Response(status, json=CHAT))
    return OpenAiModel(
        JsonEndpoint("https://llm.test/chat/completions", pauses=(), transport=service), "gpt"
    )


MODELS = {"OpenAiModel": open_ai, "FakeModel": lambda: FakeModel("hi")}
FAILING = {
    "OpenAiModel": lambda: open_ai(status=401),
    "FakeModel": lambda: FakeModel(ModelFailure("down")),
}


@pytest.mark.parametrize("make", MODELS.values(), ids=MODELS)
async def test_reply_is_text_and_name_is_set(make):
    model: Model = make()
    assert await model.reply([{"role": "user", "content": "hello"}]) == "hi"
    assert model.name


@pytest.mark.parametrize("make", FAILING.values(), ids=FAILING)
async def test_failure_is_model_failure(make):
    with pytest.raises(ModelFailure):
        await make().reply([{"role": "user", "content": "hello"}])
