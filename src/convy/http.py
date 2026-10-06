"""JSON over HTTP: the endpoint every HTTP call goes through, and an agent built on it."""

import asyncio
import json
import re
import ssl
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from uuid import uuid4

import httpx2
from msgspec import Struct

from convy.agent import AgentFailure, Answer, Conversation, Message, NoUsage, Usage

RETRIED = frozenset({429, 503})  # the service says it did not process the request
MAX_RETRY_AFTER = 60.0
PLACEHOLDER = re.compile(r"\{(text|session)\}")


class HttpFailure(Exception):
    """A request failed and will not be repeated."""


class Busy(Exception):
    """The service did not process the request; it may be repeated after `retry_after` seconds."""

    def __init__(self, message: str, retry_after: float = 0.0):
        super().__init__(message)
        self.retry_after = retry_after


class Tls(Struct, frozen=True):
    """An extra root certificate `ca`, and a client certificate `cert` with its `key`."""

    ca: str | None = None
    cert: str | None = None
    key: str | None = None

    def __post_init__(self) -> None:
        if self.key is not None and self.cert is None:
            raise ValueError("tls: key is set without cert")

    def context(self) -> ssl.SSLContext | bool:
        """What httpx2 takes as `verify`: `True` keeps its default, the system's certificates."""
        if self.ca is None and self.cert is None:
            return True
        context = ssl.create_default_context()
        if self.ca is not None:
            context.load_verify_locations(self.file("ca", self.ca))
        if self.cert is not None:
            key = self.file("key", self.key) if self.key is not None else None
            context.load_cert_chain(self.file("cert", self.cert), key)
        return context

    def file(self, field: str, value: str) -> Path:
        path = Path(value).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"tls {field}: no file {path}")
        return path


class JsonEndpoint(Struct, frozen=True):
    """An address that takes and returns JSON, with retries for requests it did not process."""

    url: str
    headers: dict[str, str] = {}
    tls: Tls = Tls()
    timeout: float = 120
    pauses: tuple[float, ...] = (2, 4, 8)
    transport: httpx2.AsyncBaseTransport | None = None

    @asynccontextmanager
    async def connection(self) -> AsyncIterator["JsonConnection"]:
        """One connection to the address, kept open for several requests."""
        try:
            verify = self.tls.context()
        except OSError as error:  # no file, no access, a damaged one (ssl.SSLError is an OSError)
            raise HttpFailure(f"{self.address()}: {error}") from error
        client = httpx2.AsyncClient(verify=verify, timeout=self.timeout, transport=self.transport)
        async with client as http:
            yield JsonConnection(self, http)

    def address(self) -> str:
        """The URL without its query, which may hold a key: what error messages show."""
        return self.url.partition("?")[0]

    async def post(self, body: object) -> object:
        """Send `body` once, over a connection of its own, and return the parsed answer."""
        async with self.connection() as connection:
            return await connection.post(body)


class JsonConnection(Struct, frozen=True):
    """An open connection to a `JsonEndpoint`."""

    endpoint: JsonEndpoint
    http: httpx2.AsyncClient

    async def post(self, body: object) -> object:
        """Send `body` and return the parsed answer, or raise `HttpFailure`."""
        for pause in self.endpoint.pauses:
            try:
                return await self.attempt(body)
            except Busy as busy:
                await asyncio.sleep(busy.retry_after or pause)
        try:
            return await self.attempt(body)
        except Busy as busy:
            raise HttpFailure(str(busy)) from busy

    async def attempt(self, body: object) -> object:
        url = self.endpoint.address()
        try:
            response = await self.http.post(
                self.endpoint.url, json=body, headers=self.endpoint.headers
            )
        except (httpx2.ConnectError, httpx2.ConnectTimeout) as error:
            raise Busy(f"POST {url}: cannot connect: {error}") from error
        except UnicodeEncodeError:  # the message would show part of the value, maybe of a key
            names = [name for name, value in self.endpoint.headers.items() if not value.isascii()]
            raise HttpFailure(f"POST {url}: a header value is not ASCII: {names}") from None
        except (httpx2.HTTPError, httpx2.InvalidURL) as error:
            raise HttpFailure(f"POST {url}: {type(error).__name__}: {error}") from error
        if response.status_code in RETRIED:
            raise Busy(f"POST {url}: {response.status_code}", self.retry_after(response))
        if not response.is_success:
            raise HttpFailure(f"POST {url}: {response.status_code} {response.text[:200]}")
        try:
            return response.json()
        except ValueError as error:
            raise HttpFailure(
                f"POST {url}: the answer is not JSON: {response.text[:200]}"
            ) from error

    def retry_after(self, response: httpx2.Response) -> float:
        """Seconds from `Retry-After`, given as seconds or as a date; 0 when absent."""
        value = response.headers.get("Retry-After", "").strip()
        if value.isascii() and value.isdigit():
            seconds = float(value)
        else:
            try:
                seconds = (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
            except (ValueError, TypeError):  # TypeError: a date without a timezone
                return 0.0
        return min(max(seconds, 0.0), MAX_RETRY_AFTER)


class JsonAgent(Struct, frozen=True):
    """An agent with a JSON API, described by a body template and paths in the answer.

    In `body`, `{text}` becomes the user's message and `{session}` the conversation's id; a value of
    exactly `"{history}"` becomes the dialogue so far. `reply` is the path to the answer's text and
    `tokens` the paths to its input and output tokens: dot-separated, numbers are list indexes.
    """

    endpoint: JsonEndpoint
    body: Mapping[str, object]
    reply: str
    tokens: tuple[str, str] | None = None

    def __post_init__(self) -> None:
        template = json.dumps(self.body)
        if "{text}" not in template and '"{history}"' not in template:
            raise ValueError('the body has neither "{text}" nor "{history}"')

    @asynccontextmanager
    async def conversation(self) -> AsyncIterator[Conversation]:
        async with self.endpoint.connection() as connection:
            yield JsonConversation(self, str(uuid4()), connection)


class JsonConversation:
    """A conversation of `JsonAgent`: it keeps the session id, the connection and the dialogue
    so far."""

    def __init__(self, agent: JsonAgent, session: str, connection: JsonConnection):
        self.agent = agent
        self.session = session
        self.connection = connection
        self.history: list[dict[str, str]] = []

    async def answer(self, message: Message) -> Answer:
        history = [*self.history, {"role": "user", "content": message.text}]
        values = {"text": message.text, "session": self.session}
        body = Placeholders(values, history).fill(self.agent.body)
        try:
            data = await self.connection.post(body)
            text = JsonPath(self.agent.reply).find(data)
            usage = self.usage(data)
        except (HttpFailure, LookupError) as failure:
            raise AgentFailure(str(failure)) from failure
        if not isinstance(text, str):
            raise AgentFailure(f"{self.agent.reply}: expected text, got {text!r:.100}")
        self.history = [*history, {"role": "assistant", "content": text}]
        return Answer(text, usage)

    def usage(self, data: object) -> Usage | NoUsage:
        if self.agent.tokens is None:
            return NoUsage()
        spent, produced = (JsonPath(path).find(data) for path in self.agent.tokens)
        if type(spent) is not int or type(produced) is not int:  # bool is an int too
            found = f"got {spent!r} and {produced!r}"
            raise AgentFailure(f"{self.agent.tokens}: expected token counts, {found}")
        return Usage(spent, produced)


class Placeholders(Struct, frozen=True):
    """The values of `{text}`, `{session}` and `"{history}"` for one turn."""

    values: dict[str, str]
    history: list[dict[str, str]]

    def fill(self, template: object) -> object:
        if template == "{history}":
            return self.history
        if isinstance(template, str):  # one pass, so a message containing "{session}" stays as is
            return PLACEHOLDER.sub(lambda match: self.values[match[1]], template)
        if isinstance(template, dict):
            return {key: self.fill(item) for key, item in template.items()}
        if isinstance(template, list):
            return [self.fill(item) for item in template]
        return template


class JsonPath(Struct, frozen=True):
    """A dot-separated path into JSON; numbers are list indexes."""

    path: str

    def find(self, data: object) -> object:
        for key in self.path.split("."):
            if isinstance(data, dict) and key in data:
                data = data[key]
            elif isinstance(data, list) and key.isdigit() and int(key) < len(data):
                data = data[int(key)]
            else:
                raise LookupError(f"{self.path}: no {key!r} in the answer")
        return data
