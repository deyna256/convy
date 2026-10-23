# Connect an agent

convy talks to your agent as a user would: it sends a message and waits for the answer. It does not
need the agent's code or its model. Each agent is one file in `agents/`. Its name is the file name
without `.py`, such as `support_bot`. A name cannot be a path: no `/`, no `..`, and on Windows
no `\`.

## An agent with a JSON API

Settings are enough. Add `agents/support_bot.py`:

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

On every turn convy sends `body`. It puts the user's message in place of `{text}`, and an id that
stays the same for the whole conversation in place of `{session}`. If your agent does not remember
the dialogue, put `"{history}"` where it expects the list of messages. `reply` is a path
in the JSON answer, and `tokens` says where its tokens are; see [Tokens](#tokens).

Files of the project can import each other, as in a script run from its folder. Put shared settings
in one module, like `gateway.py` in a new project (`from gateway import gateway`).

Check the connection. The agent answers for real; nothing else is called:

```sh
uv run convy run support_bot --smoke
```

## An agent with its own protocol

Streaming, a two-step login or any other protocol takes two small classes in the same file: an agent
that opens a conversation, and a conversation that answers a message.

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

You do not need to catch errors in `answer`. Any exception fails the turn, and convy writes it into
the dialogue. The text of the exception goes into the run's folder and the report, so keep keys out
of it. `Env`'s own errors never show the values they read.

## A busy service

When the service refuses a message because it is busy, such as with "429 Too Many Requests", raise
`Busy`, and pass the seconds the service asks to wait, if it says:

```python
from convy import Busy

if response.status_code == 429:
    raise Busy("429")
```

convy then sends the message again, for up to 2 minutes after the first refusal, and the wait counts
neither in the time per answer nor against `--turn-timeout`. While the service is busy, convy also
opens fewer conversations at once. If it stays busy, the attempt has no verdict and is left out of
the pass rate: convy sent too much, the agent did nothing wrong. Raise `Busy` only when the service
did not act on the message, or the agent may get it twice. A model or a judge of your own raises
`Busy` the same way; `JsonAgent` and `OpenAiModel` do it on 429 and 503.

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

When a turn runs out of time, convy stops waiting. But a thread cannot be stopped: the call goes on
until it returns. Give the client its own timeout if it has one.

## Tokens counted from the start

Some agents report only the tokens spent so far, not those of one answer. Read the counter before
and after the turn. The difference is the turn's tokens:

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

The counter must belong to the conversation. A counter shared by conversations that run at the same
time mixes their tokens. Give such an agent a limit of 1, `parallel = 1` under
`[tool.convy.agents.<agent>]`; see [How much runs at once](runs.md#how-much-runs-at-once).

## Tokens

An answer's `Usage` has its input and output tokens, and the parts of them you can report:

```python
Usage(input=1200, output=300, thinking=200, cache_read=1000, cache_write=150)
```

`input` is every token the model read, those read from or written to its cache included; `output`
every token it wrote, thinking included. A count you do not give, or that is missing from the
answer, shows as not reported, not as 0; `thinking=0` says none was spent.

A `JsonAgent` reads them with `TokenPaths`. OpenAI counts them as convy does:

```python
tokens = TokenPaths(
    input="usage.prompt_tokens",
    output="usage.completion_tokens",
    thinking="usage.completion_tokens_details.reasoning_tokens",
    cache_read="usage.prompt_tokens_details.cached_tokens",
)
```

A tuple of paths adds their values. Anthropic's `input_tokens` leaves the cache out, so add it:

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

The path of `input` and of `output`, or the first of their tuple, must be in the answer, so a typo
fails the turn at once. The other paths may be missing or `null`: providers leave them out when
there is nothing to count.

## No tokens at all

If your agent does not report tokens, the report shows time and results without them. To get them,
add them to the agent's answer, or read them from the model gateway the agent uses.

## Steps

An answer can say how the agent got there: what it thought and what it called, in order. The
report shows the steps next to the answer; the simulated user and the judge never see them.

```python
from datetime import UTC, datetime

from convy import Answer, Call, Reported, Thought, Usage

return Answer(
    text,
    Usage(input=3100, output=530),
    steps=(
        Thought("The order number comes first."),
        Call(
            name="get_order",
            started=datetime(2026, 10, 20, 12, 0, 1, tzinfo=UTC),
            seconds=1.2,
            sent=Reported("1042"),
            received=Reported('{"status": "damaged"}'),
        ),
    ),
)
```

- `started` is when a call started, by the agent's own clock, with a time zone:
  `datetime.now(UTC)`, or the start of a span from your tracer. `seconds` is how long it took.
- `usage`, `sent` and `received` are optional. `Reported("")` is text that was empty, such as a
  search that found nothing; `NotReported()`, the default, is text you did not give.
- convy shows the steps as you give them and checks them against nothing; see
  [why](decisions/0010-answer-steps.md). A call without a name or a time zone, or with seconds
  below 0, fails the turn as an agent error.

### Thinking

The agent's thinking is a `Thought`. Its tokens go in `Usage`: `thinking` is the part of `output`
spent on thinking. OpenAI and Anthropic report it that way, so pass their numbers as they are. If a
provider counts thinking apart from the answer, as Gemini does, add the two: `output` is the
answer's tokens plus the thinking's.

A thinking count you do not give shows as not reported; see [Tokens](#tokens).

```python
return Answer(text, Usage(input=120, output=300, thinking=200), steps=(Thought(thought),))
```

convy does not guess where an agent keeps its thinking; your `answer` knows. An agent that sends it
in a field of its own:

```python
    async def answer(self, message: Message) -> Answer:
        response = await self.http.post("/chat", json={"text": message.text})
        data = response.raise_for_status().json()["message"]
        thought = (data.get("reasoning_content") or "").strip()
        return Answer(data["content"], steps=(Thought(thought),) if thought else ())
```

An agent that puts it inside the text, as some open models do with `<think>…</think>`:

```python
    async def answer(self, message: Message) -> Answer:
        response = await self.http.post("/chat", json={"text": message.text})
        text = response.raise_for_status().json()["text"].strip()
        thought, mark, said = text.partition("</think>")  # some models leave out the opening tag
        if not mark:  # cut off while thinking, or no thinking at all
            thought, said = (text, "") if text.startswith("<think>") else ("", text)
        thought = thought.removeprefix("<think>").strip()
        return Answer(said.strip(), steps=(Thought(thought),) if thought else ())
```

## Corporate certificates

An agent or a gateway behind a corporate certificate authority takes `Tls` in its endpoint. `ca` is
an extra root certificate; `cert` and `key` are a client certificate. Declare the paths in your
`Env` as pydantic's `FilePath`. Then a wrong path stops convy before the run (`error: …`, exit
code 2) instead of failing every attempt:

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

`FilePath` does not expand `~`, so write the full path. A file that exists but is damaged shows only
when convy connects. Check the agent with `--smoke`.

## convy's own models

convy talks to the agent, not to its model, so it does not need to know which model the agent uses.
Only convy's own models are set in `models.py`: the one that plays the user and the judge.
