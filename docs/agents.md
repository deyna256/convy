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
the dialogue, put `"{history}"` where it expects the list of messages. `reply` and `tokens` are
paths in the JSON answer.

Files of the project can import each other, as in a script run from its folder. Put shared settings
in one module, like `gateway.py` in a new project (`from gateway import gateway`).

Check the connection. The agent answers for real; nothing else is called:

```sh
uv run convy run support_bot --smoke
```

## Label a build

An agent's build is the `version` line in its file, for example `version = "1.1"`. Reports and
comparisons show it. `convy resume` refuses a run whose version changed, because the run would no
longer measure one thing.

## Time limits

A request through `JsonEndpoint` gives up after 120 seconds. `--turn-timeout` does not override this for `JsonAgent`.

## Retries

convy retries on 429, 503 and connection refused, up to three times. It does not retry 5xx that may have been processed.

## convy's own models

Set in `models.py` with `Models(user=..., judge=...)`. The template uses `GW_BASE_URL` and `GW_API_KEY`.
