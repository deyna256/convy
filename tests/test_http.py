import os
import ssl
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx2
import pytest
import time_machine
import trustme

from convy.agent import AgentFailure, Answer, Message, NoUsage, Usage
from convy.http import HttpFailure, JsonAgent, JsonEndpoint, Tls

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


class Service(httpx2.MockTransport):
    """A fake HTTP service: answers from a list, records the requests it got and counts the
    clients opened over it."""

    def __init__(self, *responses: httpx2.Response | Exception):
        super().__init__(self.answer)
        self.responses = list(responses)
        self.requests: list[httpx2.Request] = []
        self.clients = 0

    async def __aenter__(self) -> "Service":
        self.clients += 1
        return self

    def answer(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def endpoint(self) -> JsonEndpoint:
        return JsonEndpoint("https://agent.test/chat", pauses=(0, 0), transport=self)


async def test_post_returns_the_parsed_answer():
    service = Service(httpx2.Response(200, json={"ok": True}))
    assert await service.endpoint().post({"q": 1}) == {"ok": True}
    assert service.requests[0].read() == b'{"q":1}'


@pytest.mark.parametrize("status", [429, 503])
async def test_post_repeats_a_request_the_service_did_not_process(status: int):
    service = Service(httpx2.Response(status), httpx2.Response(200, json={}))
    assert await service.endpoint().post({}) == {}
    assert len(service.requests) == 2


@pytest.mark.parametrize("error", [httpx2.ConnectError("refused"), httpx2.ConnectTimeout("slow")])
async def test_post_repeats_when_it_cannot_connect(error: Exception):
    service = Service(error, httpx2.Response(200, json={}))
    assert await service.endpoint().post({}) == {}


@pytest.mark.parametrize(
    "failure",
    [httpx2.Response(status) for status in (500, 502, 504)] + [httpx2.ReadTimeout("slow")],
)
async def test_post_does_not_repeat_a_request_the_service_may_have_processed(failure):
    service = Service(failure, httpx2.Response(200, json={}))
    with pytest.raises(HttpFailure):
        await service.endpoint().post({})
    assert len(service.requests) == 1


async def test_post_fails_when_the_retries_run_out():
    service = Service(*[httpx2.Response(503)] * 3)
    with pytest.raises(HttpFailure, match="503"):
        await service.endpoint().post({})
    assert len(service.requests) == 3


async def test_post_fails_on_an_answer_that_is_not_json():
    with pytest.raises(HttpFailure, match="not JSON: oops"):
        await Service(httpx2.Response(200, text="oops")).endpoint().post({})


@pytest.mark.parametrize(
    ("header", "seconds"),
    [
        ("7", 7.0),
        ("600", 60.0),
        (format_datetime(NOW + timedelta(seconds=30), usegmt=True), 30.0),
        ("soon", 0.0),
        ("Wed, 21 Oct 2026 07:28:00 -0000", 0.0),  # a date without a timezone
        ("\u00b2", 0.0),  # a digit to str.isdigit, not to float
    ],
)
async def test_retry_after_is_seconds_or_a_date_capped_at_a_minute(header: str, seconds: float):
    response = httpx2.Response(429, headers={b"Retry-After": header.encode("latin-1")})
    async with Service().endpoint().connection() as connection:
        with time_machine.travel(NOW, tick=False):
            assert connection.retry_after(response) == seconds


@pytest.mark.parametrize("tls", [Tls(ca="/missing.pem"), Tls(ca=__file__)])
async def test_a_wrong_tls_is_an_http_failure(tls: Tls):
    with pytest.raises(HttpFailure, match=r"https://agent\.test/chat: "):
        await JsonEndpoint("https://agent.test/chat", tls=tls, transport=Service()).post({})


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file")
async def test_an_unreadable_certificate_is_an_http_failure(tmp_path):
    ca = tmp_path / "ca.pem"
    ca.write_text("")
    ca.chmod(0)
    with pytest.raises(HttpFailure, match=r"https://agent\.test/chat: .*Permission denied"):
        await JsonEndpoint(
            "https://agent.test/chat", tls=Tls(ca=str(ca)), transport=Service()
        ).post({})


async def test_a_malformed_url_is_an_http_failure():
    with pytest.raises(HttpFailure, match="InvalidURL"):
        await JsonEndpoint("https://agent.test/\x00", pauses=()).post({})


async def test_a_header_that_is_not_ascii_is_an_http_failure_without_its_value():
    headers = {"Authorization": "Bearer sk\u2011SECRET"}  # a key pasted with a non-breaking hyphen
    endpoint = JsonEndpoint("https://agent.test/chat", headers=headers, transport=Service())
    with pytest.raises(HttpFailure, match="Authorization") as failure:
        await endpoint.post({})
    assert "SECRET" not in str(failure.value)
    assert "\u2011" not in str(failure.value)


async def test_failures_do_not_show_the_query_of_the_url():
    service = Service(httpx2.Response(401))
    endpoint = JsonEndpoint("https://agent.test/chat?key=SECRET", transport=service)
    with pytest.raises(HttpFailure) as failure:
        await endpoint.post({})
    assert "SECRET" not in str(failure.value)
    assert "https://agent.test/chat: 401" in str(failure.value)


def test_tls_names_a_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError, match=f"tls ca: no file {tmp_path}/none.pem"):
        Tls(ca=str(tmp_path / "none.pem")).context()


def test_tls_loads_a_root_and_a_client_certificate(tmp_path):
    ca = trustme.CA()
    client = ca.issue_cert("client@convy.test")
    ca.cert_pem.write_to_path(str(tmp_path / "ca.pem"))
    client.cert_chain_pems[0].write_to_path(str(tmp_path / "cert.pem"))
    client.private_key_pem.write_to_path(str(tmp_path / "key.pem"))
    files = {name: str(tmp_path / f"{name}.pem") for name in ("ca", "cert", "key")}
    context = Tls(**files).context()
    assert isinstance(context, ssl.SSLContext)
    assert "trustme" in str(context.get_ca_certs())  # the extra root, next to the system's
    with pytest.raises(ssl.SSLError):  # the certificate alone has no key: the key is what loaded it
        Tls(cert=files["cert"]).context()


def test_tls_rejects_a_key_without_a_certificate():
    with pytest.raises(ValueError, match="key is set without cert"):
        Tls(key="client.key")


def json_agent(
    service: Service,
    body: Mapping[str, object] | None = None,
    reply: str = "a",
    tokens: tuple[str, str] | None = None,
) -> JsonAgent:
    return JsonAgent(service.endpoint(), body or {"q": "{text}"}, reply, tokens)


async def test_json_agent_fills_text_session_and_history():
    service = Service(*[httpx2.Response(200, json={"a": "ok"})] * 2)
    body = {"m": "{text} ({session})", "h": "{history}", "n": [1, "{text}"]}
    async with json_agent(service, body=body).conversation() as conversation:
        await conversation.answer(Message("hi {session}"))
        await conversation.answer(Message("again"))
    first, second = (httpx2.Response(200, content=r.read()).json() for r in service.requests)
    session = first["m"].removeprefix("hi {session} (").removesuffix(")")
    assert len(session) == 36
    assert second["m"] == f"again ({session})"
    assert second["n"] == [1, "again"]
    assert second["h"] == [
        {"role": "user", "content": "hi {session}"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "again"},
    ]


async def test_json_agent_uses_one_client_for_the_whole_conversation():
    service = Service(*[httpx2.Response(200, json={"a": "ok"})] * 2)
    async with json_agent(service).conversation() as conversation:
        await conversation.answer(Message("one"))
        await conversation.answer(Message("two"))
    assert (service.clients, len(service.requests)) == (1, 2)


async def test_post_opens_a_client_of_its_own():
    service = Service(*[httpx2.Response(200, json={})] * 2)
    await service.endpoint().post({})
    await service.endpoint().post({})
    assert service.clients == 2


async def test_json_agent_reads_reply_and_tokens_by_paths():
    data = {"choices": [{"message": {"content": "hi"}}], "usage": {"in": 3, "out": 4}}
    service = Service(httpx2.Response(200, json=data))
    agent = json_agent(service, reply="choices.0.message.content", tokens=("usage.in", "usage.out"))
    async with agent.conversation() as conversation:
        assert await conversation.answer(Message("?")) == Answer("hi", Usage(3, 4))


async def test_json_agent_rejects_tokens_that_are_not_counts():
    service = Service(httpx2.Response(200, json={"a": "hi", "in": True, "out": 1}))
    async with json_agent(service, tokens=("in", "out")).conversation() as conversation:
        with pytest.raises(AgentFailure, match="expected token counts"):
            await conversation.answer(Message("?"))


async def test_json_agent_without_tokens_has_no_usage():
    service = Service(httpx2.Response(200, json={"a": "hi"}))
    async with json_agent(service).conversation() as conversation:
        assert (await conversation.answer(Message("?"))).usage == NoUsage()


@pytest.mark.parametrize(
    ("data", "error"), [({"a": 1}, "expected text"), ({"b": "hi"}, "no 'a'"), ([], "no 'a'")]
)
async def test_json_agent_fails_when_the_reply_is_not_text(data, error: str):
    async with json_agent(Service(httpx2.Response(200, json=data))).conversation() as conversation:
        with pytest.raises(AgentFailure, match=error):
            await conversation.answer(Message("?"))


async def test_json_agent_turns_http_failure_into_agent_failure():
    async with json_agent(Service(httpx2.Response(401))).conversation() as conversation:
        with pytest.raises(AgentFailure, match="401"):
            await conversation.answer(Message("?"))


async def test_json_agent_history_does_not_keep_a_failed_turn():
    service = Service(httpx2.Response(500), httpx2.Response(200, json={"a": "ok"}))
    agent = json_agent(service, body={"h": "{history}"})
    async with agent.conversation() as conversation:
        with pytest.raises(AgentFailure):
            await conversation.answer(Message("lost"))
        await conversation.answer(Message("kept"))
    assert httpx2.Response(200, content=service.requests[1].read()).json()["h"] == [
        {"role": "user", "content": "kept"}
    ]


def test_json_agent_needs_text_or_history_in_the_body():
    with pytest.raises(ValueError, match="neither"):
        json_agent(Service(), body={"q": "fixed"})
