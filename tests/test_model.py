import httpx2
import pytest

from convy.env import Env
from convy.fakes import FakeModel
from convy.http import JsonEndpoint
from convy.model import ModelFailure, OpenAiModel


async def test_open_ai_model_sends_its_name_and_the_messages():
    requests: list[httpx2.Request] = []

    def service(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

    endpoint = JsonEndpoint(
        "https://llm.test/chat/completions", transport=httpx2.MockTransport(service)
    )
    await OpenAiModel(endpoint, "gpt").reply([{"role": "user", "content": "hello"}])
    assert httpx2.Response(200, content=requests[0].read()).json() == {
        "model": "gpt",
        "messages": [{"role": "user", "content": "hello"}],
    }


async def test_open_ai_model_fails_on_an_answer_without_text():
    service = httpx2.MockTransport(lambda request: httpx2.Response(200, json={"choices": []}))
    model = OpenAiModel(JsonEndpoint("https://llm.test", transport=service), "gpt")
    with pytest.raises(ModelFailure, match=r"gpt: choices\.0\.message\.content"):
        await model.reply([])


LONE_SURROGATE = b'{"choices": [{"message": {"content": "\\ud83d"}}]}'  # half an emoji


async def test_open_ai_model_fails_on_text_that_cannot_be_encoded():
    service = httpx2.MockTransport(lambda request: httpx2.Response(200, content=LONE_SURROGATE))
    model = OpenAiModel(JsonEndpoint("https://llm.test", transport=service), "gpt")
    with pytest.raises(ModelFailure, match="gpt: the reply is not valid Unicode") as failure:
        await model.reply([])
    assert "\ud83d" not in str(failure.value)


async def test_fake_model_replies_in_order_and_repeats_the_last():
    model = FakeModel("one", "two")
    assert [await model.reply([]) for _ in range(3)] == ["one", "two", "two"]
    assert len(model.calls) == 3


async def test_fake_model_keeps_a_copy_of_the_messages():
    model = FakeModel("hi")
    messages = [{"role": "user", "content": "hello"}]
    await model.reply(messages)
    messages.append({"role": "user", "content": "later"})
    assert model.calls == [[{"role": "user", "content": "hello"}]]


def test_env_reads_dotenv_then_the_environment(tmp_path, monkeypatch):
    class GatewayEnv(Env):
        base_url: str
        api_key: str

    (tmp_path / ".env").write_text("BASE_URL=https://from-file\nAPI_KEY=file\nOTHER=1\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("API_KEY", "from-environment")
    env = GatewayEnv()
    assert (env.base_url, env.api_key) == ("https://from-file", "from-environment")
