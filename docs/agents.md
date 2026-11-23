# Connect an agent

convy sends messages to your agent and reads its replies. Put the adapter in `agents/<name>.py`.
For example, `agents/support_bot.py` is available as `convy run support_bot`.

## An agent with a JSON API

Define a `JsonAgent` in `agents/support_bot.py`.

```python
from pydantic import SecretStr
from convy import Env, JsonAgent, JsonEndpoint, TokenPaths


class BotEnv(Env):
    bot_token: SecretStr  # BOT_TOKEN in .env


env = BotEnv()
agent = JsonAgent(
    JsonEndpoint(
        "https://bot.example.com/api/chat",
        headers={"Authorization": f"Bearer {env.bot_token.get_secret_value()}"},
    ),
    body={"session_id": "{session}", "message": "{text}"},
    reply="data.answer",
    tokens=TokenPaths(input="data.usage.input_tokens", output="data.usage.output_tokens"),
)
```

On each turn, `JsonAgent` fills in the request body. `{text}` expands to the current message.
`{session}` expands to an ID shared by all turns in this conversation. For an API that expects
the full message list, use `"{history}"` as the entire JSON value. `reply` locates the answer
text in the response. Optional [token paths](#tokens) locate usage counts.

Project files can import shared settings from a module such as `gateway.py` in the project root.

Check the connection with a real request to the agent. Smoke mode uses local fakes for the
simulated user and judge.

```sh
uv run convy run support_bot --smoke
```

## An agent with its own protocol

For streaming, login, or a custom client, define an agent that opens a conversation and a
conversation that answers messages.

```python
from contextlib import asynccontextmanager

import httpx2

from convy import Answer, Message, Usage


class SupportBot:
    @asynccontextmanager
    async def conversation(self):
        async with httpx2.AsyncClient(base_url="https://bot.example.com") as http:
            login = await http.post("/login", json={"user": "convy"})
            yield SupportChat(http, login.raise_for_status().json()["token"])


class SupportChat:
    def __init__(self, http: httpx2.AsyncClient, token: str):
        self.http = http
        self.token = token

    async def answer(self, message: Message) -> Answer:
        response = await self.http.post(
            "/chat",
            json={"text": message.text},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        data = response.raise_for_status().json()
        return Answer(data["text"], Usage(input=data["tokens_in"], output=data["tokens_out"]))


agent = SupportBot()
```

An exception from `answer` normally fails the turn. convy records the error message in the
dialogue and report, so keep secrets out of exceptions.

## A busy service

Raise `Busy` only when the service refused the request **before processing it**. convy may
send the same message again. If you know the requested delay, pass it in seconds as
`Busy(message, retry_after=seconds)`.

```python
from convy import Busy

if response.status_code == 429:
    raise Busy("429")
```

On a busy turn, convy retries and reduces the number of concurrent conversations. The default
retry budget is two minutes from the first refusal. Waiting between tries adds nothing to
the reported answer time or the turn timeout. If the agent stays busy, the attempt gets no
verdict and is excluded from the pass rate. Custom models and judges can also raise `Busy`.
`JsonAgent` and `OpenAiModel` do this automatically for HTTP 429 and 503.

## A client without async

convy is async. If your client only has blocking calls, run them in a thread with
`asyncio.to_thread`. Then other conversations go on while one waits:

```python
import asyncio
from contextlib import asynccontextmanager

from support_sdk import Client  # a client with blocking calls only

from convy import Answer, Message


class SupportBot:
    @asynccontextmanager
    async def conversation(self):
        client = Client("https://bot.example.com")
        session = await asyncio.to_thread(client.start_session)
        try:
            yield SupportChat(client, session)
        finally:
            await asyncio.to_thread(client.close)


class SupportChat:
    def __init__(self, client: Client, session: str):
        self.client = client
        self.session = session

    async def answer(self, message: Message) -> Answer:
        text = await asyncio.to_thread(self.client.send, self.session, message.text)
        return Answer(text)


agent = SupportBot()
```

When a turn times out, the blocking call continues in its thread. Set a timeout on the client
itself if it supports one.

## Tokens

Return `Answer(text)` if the agent has no token counts. To report usage, include the input
and output totals and any breakdown you have.

```python
Usage(input=1200, output=300, thinking=200, cache_read=1000, cache_write=150)
```

`input` includes all input tokens, including cache reads and writes. `output` includes
thinking tokens. Omit an optional count (or use `NotReported()`) if it is unknown. Use zero
only for a measured zero.

With a `JsonAgent`, set `TokenPaths` to the fields in your API's response. For example,
for an OpenAI-style response:

```python
tokens = TokenPaths(
    input="usage.prompt_tokens",
    output="usage.completion_tokens",
    thinking="usage.completion_tokens_details.reasoning_tokens",
    cache_read="usage.prompt_tokens_details.cached_tokens",
)
```

If your API reports cache usage separately from ordinary input tokens, give a tuple of paths
to add together. For example:

```python
tokens = TokenPaths(
    input=(
        "usage.input_tokens",
        "usage.cache_read_input_tokens",
        "usage.cache_creation_input_tokens",
    ),
    output="usage.output_tokens",
    thinking="usage.output_tokens_details.thinking_tokens",
    cache_read="usage.cache_read_input_tokens",
    cache_write="usage.cache_creation_input_tokens",
)
```

The first path for each of `input` and `output` must resolve to an integer. Additional paths
and optional fields can be missing or null.

## Tokens counted from the start

If the API reports a running total, subtract the count before a turn from the count after it.

```python
import httpx2

from convy import Answer, Message, Usage


class SupportChat:
    def __init__(self, http: httpx2.AsyncClient):
        self.http = http

    async def answer(self, message: Message) -> Answer:
        before = await self.spent()
        response = await self.http.post("/chat", json={"text": message.text})
        after = await self.spent()
        text = response.raise_for_status().json()["text"]
        return Answer(text, Usage(input=after[0] - before[0], output=after[1] - before[1]))

    async def spent(self) -> tuple[int, int]:
        """The tokens this conversation has spent so far: input and output."""
        usage = (await self.http.get("/usage")).raise_for_status().json()
        return usage["input_tokens"], usage["output_tokens"]
```

Use a per-conversation counter. If several conversations share one counter, their usage can
overlap. Set `parallel = 1` under `[tool.convy.agents.<agent>]` and make sure no other client
uses the same counter during the run. See [Run limits](runs.md#how-much-runs-at-once).

## Steps

Use `steps` to show thoughts and calls in order alongside the answer. convy removes these
steps before passing the dialogue to the simulated user or judge.

```python
from datetime import UTC, datetime

from convy import Answer, Call, Reported, Thought, Usage

return Answer(
    text,
    Usage(input=3100, output=530),
    steps=(
        Thought("The order number comes first."),
        Call(
            kind="tool",
            name="get_order",
            started=datetime(2026, 10, 20, 12, 0, 1, tzinfo=UTC),
            seconds=1.2,
            sent=Reported("1042"),
            received=Reported('{"status": "damaged"}'),
        ),
    ),
)
```

- `kind` is required: `"model"` for a direct model call, `"tool"` for a tool invocation,
  including search. convy does not infer it from the name or token usage.
- `started` is when a call started, by the agent's own clock, with a time zone:
  `datetime.now(UTC)`, or the start of a span from your tracer. `seconds` is how long it took.
- `usage`, `sent` and `received` are optional. `Reported("")` is text that was empty, such as a
  search that found nothing; `NotReported()`, the default, is text you did not give.
- convy shows the steps as you give them without reconciling their time or tokens with the
  answer; see [why](decisions/0010-answer-steps.md). An invalid call kind, a call without a name
  or a time zone, or seconds below 0 fails the turn as an agent error.

`Answer.steps_complete` defaults to `False`: steps may be partial or absent. Set it to `True`
only when `steps` lists every call made for that answer, including model calls and every tool
retry or failed invocation. The example above leaves it false because it shows only the order
lookup. A complete trace may omit thinking, since thoughts are not calls.

An answer with no calls can explicitly report that fact with `Answer(text, steps_complete=True)`.
An empty or partial trace with `steps_complete=False` has an unknown tool count. Complete traces
enable [tool invocations per task](report.md#tool-invocations); partial steps remain visible.

### Thinking

Record a reported thought as `Thought(text)`. Include thinking tokens in the output total.
If your provider counts them separately, add the visible output and thinking counts.

```python
return Answer(text, Usage(input=120, output=300, thinking=200), steps=(Thought(thought),))
```

When the agent returns thinking in a separate field, keep it out of the visible answer.

```python
    async def answer(self, message: Message) -> Answer:
        response = await self.http.post("/chat", json={"text": message.text})
        data = response.raise_for_status().json()["message"]
        thought = (data.get("reasoning_content") or "").strip()
        return Answer(data["content"], steps=(Thought(thought),) if thought else ())
```

## Corporate certificates

Use `Tls(ca=...)` to trust an additional root certificate. For client authentication, supply
`cert` and `key`. Declare the paths as pydantic `FilePath` settings so a missing file fails
the configuration check before the run.

```python
from pydantic import FilePath
from convy import Env, JsonAgent, JsonEndpoint, Tls


class CorpEnv(Env):
    corp_ca: FilePath  # CORP_CA in .env


env = CorpEnv()
agent = JsonAgent(
    JsonEndpoint("https://bot.corp.example/api/chat", tls=Tls(ca=str(env.corp_ca))),
    body={"message": "{text}"},
    reply="answer",
)
```

Use a full path. `FilePath` does not expand `~`. Use `--smoke` to check that the certificate
works when the agent connects.

## convy's own models

Configure the simulated user and the judge in `models.py`. The agent's model belongs in
the agent's own configuration. See [The judge](judge.md) for an example.
