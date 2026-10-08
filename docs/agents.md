# Connect an agent

convy talks to your agent as a user would: it sends a message and waits for the answer. It does not
need the agent's code or its model. Each agent is one file in `agents/`.

## An agent with a JSON API

Settings are enough. Add `agents/support_bot.py`:

```python
from pydantic import SecretStr
from convy import Env, JsonAgent, JsonEndpoint


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
    tokens=("data.usage.input_tokens", "data.usage.output_tokens"),
)
```

On every turn convy sends `body`. It puts the user's message in place of `{text}`, and an id that
stays the same for the whole conversation in place of `{session}`. If your agent does not remember
the dialogue, put `"{history}"` where it expects the list of messages. `reply` and `tokens` are paths
in the JSON answer.

Files of the project can import each other, as in a script run from its folder. Put shared settings in
one module, like `gateway.py` in a new project (`from gateway import gateway`).

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

Some agents report only the tokens spent so far, not those of one answer. Read the counter before and
after the turn. The difference is the turn's tokens:

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
time mixes their tokens. Run such an agent with `--parallel 1`.

## No tokens at all

If your agent does not report tokens, the report shows time and results without them. To get them,
add them to the agent's answer, or read them from the model gateway the agent uses.

## Corporate certificates

An agent or a gateway behind a corporate certificate authority takes `Tls` in its endpoint. `ca` is an
extra root certificate; `cert` and `key` are a client certificate. Declare the paths in your `Env` as
pydantic's `FilePath`. Then a wrong path stops convy before the run (`error: …`, exit code 2) instead
of failing every attempt:

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
