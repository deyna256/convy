"""JSON over HTTP: the endpoint every HTTP call goes through, and an agent built on it."""

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
import msgspec
from msgspec import Struct

from convy.agent import AgentFailure, Answer, Conversation, Message, NotReported, NoUsage, Usage
from convy.busy import Busy

BUSY = frozenset({429, 503})  # the service says it did not process the request
PLACEHOLDER = re.compile(r"\{(text|session)\}")


class HttpFailure(Exception):
    """A request failed, and convy does not send it again."""


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
    """An address that takes and returns JSON. A request the service refused because it is busy
    raises `Busy`, which convy waits on; nothing is repeated here."""

    url: str
    headers: dict[str, str] = {}
    tls: Tls = Tls()
    timeout: float = 120
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
        """Send `body` and return the parsed answer; raise `Busy` when the service refused it
        unprocessed, `HttpFailure` when it failed otherwise."""
        url = self.endpoint.address()
        try:
            response = await self.http.post(
                self.endpoint.url, json=body, headers=self.endpoint.headers
            )
        except (httpx2.ConnectError, httpx2.ConnectTimeout) as error:  # gone, not busy: fail now
            raise HttpFailure(f"POST {url}: cannot connect: {error}") from error
        except UnicodeEncodeError:  # the message would show part of the value, maybe of a key
            names = [name for name, value in self.endpoint.headers.items() if not value.isascii()]
            raise HttpFailure(f"POST {url}: a header value is not ASCII: {names}") from None
        except (httpx2.HTTPError, httpx2.InvalidURL) as error:
            raise HttpFailure(f"POST {url}: {type(error).__name__}: {error}") from error
        if response.status_code in BUSY:
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
        """Seconds the service asks to wait: OpenAI's `retry-after-ms`, else `Retry-After` as
        seconds or as a date; 0 when it does not say."""
        milliseconds = response.headers.get("retry-after-ms", "").strip()
        if milliseconds.isascii() and milliseconds.isdigit():
            return int(milliseconds) / 1000
        value = response.headers.get("Retry-After", "").strip()
        if value.isascii() and value.isdigit():
            return float(value)
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
        except (ValueError, TypeError):  # TypeError: a date without a timezone
            return 0.0
        return max(seconds, 0.0)


class TokenPaths(Struct, frozen=True, kw_only=True):
    """Where a `JsonAgent` finds an answer's tokens: each a dot-separated path, or a tuple of paths
    whose values are added. The path of `input` and `output`, or the first of their tuple, must be
    in the answer, so a typo fails the turn; their further paths and the other fields may be
    missing or null, as providers leave out what there is nothing to count. A field not given is
    not reported."""

    input: str | tuple[str, ...]
    output: str | tuple[str, ...]
    thinking: str | tuple[str, ...] | None = None
    cache_read: str | tuple[str, ...] | None = None
    cache_write: str | tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        for field in (self.input, self.output):
            self.check(field, none_given=False)
        for field in (self.thinking, self.cache_read, self.cache_write):
            self.check(field, none_given=True)

    def check(self, field: object, none_given: bool) -> None:
        match field:
            case str():
                pass
            case None if none_given:
                pass
            case tuple() if not field:
                raise ValueError("a tuple of token paths needs at least one path")
            case tuple() if all(type(path) is str for path in field):
                pass
            case _:
                raise ValueError(f"token paths: give a path or a tuple of paths, got {field!r}")

    def usage(self, data: object) -> Usage:
        """The answer's tokens. LookupError: a required path is missing; AgentFailure: a value is
        not a count; ValueError: the counts do not fit together."""
        return Usage(
            self.needed(data, self.input),
            self.needed(data, self.output),
            thinking=self.found(data, self.thinking),
            cache_read=self.found(data, self.cache_read),
            cache_write=self.found(data, self.cache_write),
        )

    def needed(self, data: object, paths: str | tuple[str, ...]) -> int:
        first, *further = self.each(paths)
        counts = (self.at(data, path) for path in further)
        return self.count(JsonPath(first).find(data), first) + sum(
            c for c in counts if c is not None
        )

    def found(self, data: object, paths: str | tuple[str, ...] | None) -> int | NotReported:
        if paths is None:
            return NotReported()
        counts = [c for c in (self.at(data, path) for path in self.each(paths)) if c is not None]
        return sum(counts) if counts else NotReported()

    def at(self, data: object, path: str) -> int | None:
        """The count at a path that may be missing or null; None then."""
        try:
            found = JsonPath(path).find(data)
        except LookupError:
            return None
        return None if found is None else self.count(found, path)

    def count(self, found: object, path: str) -> int:
        try:
            return msgspec.convert(found, int)  # a bool is not a count
        except msgspec.ValidationError as error:
            raise AgentFailure(f"{path}: expected a token count: {error}") from None

    def each(self, paths: str | tuple[str, ...]) -> tuple[str, ...]:
        match paths:
            case str():
                return (paths,)
            case tuple():
                return paths


class JsonAgent(Struct, frozen=True):
    """An agent with a JSON API, described by a body template and paths in the answer.

    In `body`, `{text}` becomes the user's message and `{session}` the conversation's id; a value of
    exactly `"{history}"` becomes the dialogue so far. `reply` is the path to the answer's text and
    `tokens` says where its tokens are; paths are dot-separated, numbers are list indexes.
    """

    endpoint: JsonEndpoint
    body: Mapping[str, object]
    reply: str
    tokens: TokenPaths | None = None

    def __post_init__(self) -> None:
        template = json.dumps(self.body)
        if "{text}" not in template and '"{history}"' not in template:
            raise ValueError('the body has neither "{text}" nor "{history}"')
        match self.tokens:
            case TokenPaths() | None:
                pass
            case _:  # convy 0.5 took a tuple of two paths
                raise ValueError(
                    "tokens: write tokens=TokenPaths(input=..., output=...), "
                    "not a tuple or a list of paths"
                )

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
            text = self.text(JsonPath(self.agent.reply).find(data))
            usage = self.usage(data)
        except (HttpFailure, LookupError) as failure:
            raise AgentFailure(str(failure)) from failure
        self.history = [*history, {"role": "assistant", "content": text}]
        return Answer(text, usage)

    def text(self, found: object) -> str:
        try:
            return msgspec.convert(found, str)
        except msgspec.ValidationError as error:
            raise AgentFailure(f"{self.agent.reply}: expected text: {error}") from None

    def usage(self, data: object) -> Usage | NoUsage:
        match self.agent.tokens:
            case TokenPaths() as paths:
                try:
                    return paths.usage(data)
                except ValueError as error:  # counts a Usage cannot hold
                    raise AgentFailure(f"tokens: {error}") from None
            case None:
                return NoUsage()


class Placeholders(Struct, frozen=True):
    """The values of `{text}`, `{session}` and `"{history}"` for one turn."""

    values: dict[str, str]
    history: list[dict[str, str]]

    def fill(self, template: object) -> object:
        match template:
            case "{history}":
                return self.history
            case str():  # one pass, so a message containing "{session}" stays as is
                return PLACEHOLDER.sub(lambda match: self.values[match[1]], template)
            case dict():
                return {key: self.fill(item) for key, item in template.items()}
            case list():
                return [self.fill(item) for item in template]
            case _:
                return template


class JsonPath(Struct, frozen=True):
    """A dot-separated path into JSON; numbers are list indexes."""

    path: str

    def find(self, data: object) -> object:
        for key in self.path.split("."):
            match data:
                case dict() if key in data:
                    data = data[key]
                case list() if key.isdigit() and int(key) < len(data):
                    data = data[int(key)]
                case _:
                    raise LookupError(f"{self.path}: no {key!r} in the answer")
        return data
