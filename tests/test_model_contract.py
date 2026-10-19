"""The promises every `Model` keeps, checked on each implementation convy ships."""

import httpx2
import pytest

from convy.busy import Busy, Patience, Places
from convy.fakes import FakeModel
from convy.http import JsonEndpoint
from convy.model import Model, ModelFailure, OpenAiModel, PatientModel

CHAT = {"choices": [{"message": {"content": "hi"}}]}


def open_ai(status: int = 200) -> OpenAiModel:
    service = httpx2.MockTransport(lambda request: httpx2.Response(status, json=CHAT))
    return OpenAiModel(JsonEndpoint("https://llm.test/chat/completions", transport=service), "gpt")


MODELS = {
    "OpenAiModel": open_ai,
    "FakeModel": lambda: FakeModel("hi"),
    "PatientModel": lambda: PatientModel(FakeModel("hi"), Places(1, Patience())),
}
FAILING = {
    "OpenAiModel": lambda: open_ai(status=401),
    "FakeModel": lambda: FakeModel(ModelFailure("down")),
    "PatientModel": lambda: PatientModel(FakeModel(ModelFailure("down")), Places(1, Patience())),
}
BUSY = {
    "OpenAiModel": lambda: open_ai(status=429),
    "FakeModel": lambda: FakeModel(Busy("slow down", 1)),
    "PatientModel": lambda: PatientModel(
        FakeModel(Busy("slow down", 1)), Places(1, Patience(seconds=0))
    ),
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


@pytest.mark.parametrize("make", BUSY.values(), ids=BUSY)
async def test_a_busy_service_is_busy(make):
    """A reply the service refused because it is busy raises `Busy`, which convy waits on; one
    that waited as long as it may gives up with `Busy` too."""
    with pytest.raises(Busy):
        await make().reply([{"role": "user", "content": "hello"}])
