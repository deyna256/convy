<div align="center">

<h1>convy</h1>

<h3>Conversation tests for AI agents</h3>

<p>A simulated user talks to your agent, a judge rates the dialogue, and convy reports what you need to
decide: <strong>which scenarios the agent passes</strong>, <strong>how many tokens it spends</strong> and
<strong>how long it takes to answer</strong>. Connect any agent that runs as a service — convy needs
neither its code nor its model.</p>

[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/convy)](https://pypi.org/project/convy/)
[![Status: alpha](https://img.shields.io/badge/status-alpha-orange)](#status)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776ab)](pyproject.toml)
<br>
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)](https://github.com/astral-sh/ty)

[Status](#status) · [Why convy](#why-convy) · [Quick start](#quick-start) · [Connect an agent](#connect-an-agent) · [Scenarios](#scenarios) · [Runs](#runs) · [Report](#the-report) · [Python](#run-from-python) · [FAQ](#faq) · [Contributing](CONTRIBUTING.md)

</div>

---

## Status

convy 0.1 is the first release. It is in alpha: the Python API and the format of runs may change
before 1.0, and every change is listed in the [changelog](CHANGELOG.md).

## Why convy

Before a team puts an agent in front of people, it wants to know how the agent behaves in a real
conversation — not on a single prompt, but over several turns with someone who asks vague questions,
changes their mind or never gives the details up front. And when there are several agents, or several
builds of one, it wants to compare them on the same conversations.

convy does exactly that and nothing more:

- **Any agent, connected in minutes.** An agent with a JSON API needs a few lines of settings. Anything
  else — streaming, a two-step login, a custom protocol — is two small Python classes.
- **Conversations, not prompts.** A scenario tells a simulated user who to be and what to want; the
  judge checks plain-language claims about the dialogue.
- **Numbers for a decision.** Pass rate over repeated attempts, the agent's own tokens and its response
  time per turn: a report per run, and two runs side by side with `convy compare`.
- **Small and readable.** About a thousand lines, no evaluation framework and no containers underneath.

## How it works

```text
             scenario                                       claims
                │                                              │
                ▼                                              ▼
       ┌─────────────────┐  message  ┌─────────┐       ┌─────────────┐
       │ simulated user  │ ────────▶ │  agent  │       │    judge    │──▶ verdict
       │     (model)     │ ◀──────── │         │       │   (model)   │
       └─────────────────┘  answer   └─────────┘       └─────────────┘
                │     time and tokens of every turn           ▲
                └───────────────── transcript ────────────────┘
```

For every attempt convy opens a fresh conversation with the agent, lets the simulated user talk to it
until the user is done or the turns run out, and asks the judge whether each claim holds. Every run gets
a folder of its own, and each attempt is written there as soon as it ends, so a stopped run can be
continued. After a run convy writes every run's report, a static page inside its folder, and the
index of all runs; `convy compare` puts two runs side by side.

## Quick start

```sh
uvx convy init my-bench              # a project with examples
cd my-bench
uv run convy run echo --smoke        # check convy itself: free, no models called
cp .env.example .env                 # add the address and key of your model gateway
uv run convy run echo                # a real run with the simulated user and the judge
uv run convy report                  # a report per run, and results/index.html
```

`convy init` creates a project of your own:

```text
my-bench/
├── gateway.py        # the model gateway, shared by models.py and the agents
├── models.py         # the models that play the user and the judge
├── agents/           # one file per agent
├── scenarios/        # one YAML file per scenario, in folders if you like
└── results/          # a folder per run with its report, and the index
```

## Connect an agent

Add `agents/support_bot.py`. For an agent with a JSON API, settings are enough:

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

convy sends the body on every turn with `{text}` replaced by the user's message and `{session}` by an id
that stays the same for the whole conversation. For an agent that does not remember the dialogue, put
`"{history}"` where it expects the list of messages. `reply` and `tokens` are paths in the JSON answer.

Files of the project import each other, as in a script run from its folder: settings that several
agents share go into one module, such as `gateway.py` in a new project (`from gateway import gateway`).

Then check the connection — the agent answers for real, nothing else is called:

```sh
uv run convy run support_bot --smoke
```

Anything a JSON template cannot express is two classes in the same file: an agent that opens a
conversation, and a conversation that answers a message.

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

There is no need to catch errors in `answer`: any exception counts as a failed turn, and convy
records it in the dialogue. The text of an exception from your agent goes to the run's folder and the
report, so keep keys out of it; `Env`'s own errors never show the values read.

### A client without async

convy's interface is async. If your agent's client only has blocking calls, run them in a thread
with `asyncio.to_thread`, so other conversations go on while one waits:

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

When a turn runs out of time, convy stops waiting for it, but a thread cannot be stopped: the call
goes on in the background until it returns. Give the client a timeout of its own if it has one.

### Tokens counted from the start

Some agents report only the tokens spent so far, not those of one answer. Read the counter before
and after the turn; the difference is the turn's tokens:

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

The counter must belong to the conversation. A counter shared by conversations that run at the
same time mixes their tokens; run such an agent with `--parallel 1`.

### Corporate certificates

An agent or a model gateway behind a corporate certificate authority takes `Tls` in its endpoint: `ca`
is an extra root certificate, `cert` and `key` a client certificate. Declare the paths in your `Env` as
pydantic's `FilePath`, so a wrong path stops convy before the run (`error: …`, exit code 2) instead of
failing every attempt:

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

`FilePath` does not expand `~`: write the full path. A file that exists but is damaged shows only on
connection — check an agent with `--smoke`.

## Scenarios

A scenario is a YAML file in `scenarios/` or any folder under it, such as `scenarios/bank/cards/`:

```yaml
id: clarify-backup
max_turns: 6
user: |
  You need a backup script. Start short: "Make me a backup script".
  Give details only when the assistant asks for them:
  back up ~/photos to /mnt/backup, once a day.
judge:
  - Before giving a finished script, the agent asked what to back up and where to
  - The final script copies ~/photos to /mnt/backup and runs once a day
```

`user` tells the simulated user who to be and what to want; `judge` lists claims that must all hold for
the scenario to pass. The judge decides each claim on its own, with a reason, so the report shows which
claim failed. An attempt in which the agent fails a turn does not pass, whatever it said before, and the
judge is not asked. When one of convy's own models fails instead — it does not answer, or the judge
does not give one decision per claim in JSON (`"pass"` of `true` or `false`) — the attempt gets no
verdict and is left out of the pass rate.
Write scenarios in any language — the simulated user speaks the language of its instructions.

```sh
uv run convy run support_bot -k 3                  # every scenario, three attempts each
uv run convy run support_bot --scenarios 'refund-*'
uv run convy run support_bot new_bot               # several agents, one after another
uv run convy run support_bot --turn-timeout 60
```

`--turn-timeout` (600 by default) is the seconds for each step of the agent: opening a conversation,
a turn, closing. A step that takes longer fails the attempt as an agent error.

## Runs

A run is one `convy run` of one agent: the scenarios it played, `k` attempts each. It has a folder of
its own:

```text
results/
├── index.html                          # every run, with a link to its report
├── compare/                            # the pages convy compare writes
└── support_bot/
    └── 2026-10-07T14-02-11_a3f9/       # a run: started at, and a random part
        ├── report.html                 # the run's report
        ├── run.json                    # what it played and with what, and whether it finished
        └── attempts.jsonl              # a line per attempt
```

`run.json` keeps a copy of every scenario as it was played, the agent's `version`, the convy version,
the names of the models, the settings, and fingerprints of `agents/<agent>.py` and `models.py`. A run therefore
describes itself: editing a scenario later does not change what an old run means.

A run stopped by Ctrl+C is `interrupted`; convy says how to continue it:

```text
support_bot: run 2026-10-07T14-02-11_a3f9, 10 scenarios, 3 attempts each
^C
interrupted: 12 of 30 attempts recorded
resume with: convy resume a3f9
```

`convy resume` takes the run's id or its random part and plays the attempts it lacks, exactly as the
run started: the same scenarios, `k`, `--parallel` and `--turn-timeout`. It refuses, and says why, when
the agent's file, `models.py`, the agent's `version` or a model's name has changed since — the run
would no longer measure one thing. It cannot see a change in a module the agent imports, or in the
service behind it. Attempts that ended in an error are recorded and are not played again.

To forget a run, delete its folder and run `convy report`.

## The report

Every run has its own report, `results/<agent>/<run>/report.html`: a static page that works offline,
with a switch between the system, light and dark themes. Five tiles sum the run up:

- **Pass rate** — the share of attempts the judge passed, with the count (`67% · 8 of 12 attempts`);
- **Stable scenarios** — those that passed every attempt;
- **Answer time** — the mean per answer, and the slowest: the agent's own time, the simulated user
  and the judge are not counted;
- **Tokens per attempt** — in and out, the agent's own tokens as it reports them;
- **Errors** — of the agent and of convy's models.

Below them, a row per scenario: **Failing** (no attempt passed), **Flaky** (some did), **Passing**
(all did), or **No verdict**, with its answer time and tokens; a filter such as `refund-*` narrows the
list. Select a row to open the scenario: what the simulated user was told, each claim and how many
attempts it held in, and for each attempt the judge's decision on every claim with the reason and the
dialogue with the time and tokens of each answer. The address keeps the open scenario, so a link opens
it. `results/index.html` lists every run, newest first, with a link to its report.

To see what changed between two runs, name them — by id or by their random part:

```sh
uv run convy compare e46f 4693       # before, then after
```

The page `results/compare/e46f-vs-4693.html` shows the same tiles with the value before and the
change: green when better, red when worse, and grey with `~` when a change of the pass rate is within
noise — with few scenarios and attempts, a difference of that size can happen by chance. Scenarios
are grouped as **Worse**, **Better**, **Same** and **Not compared** (played by only one run, edited
between the runs, or without a verdict in one of them), and a scenario's window shows both runs'
dialogues side by side. The runs may be of different agents; the page warns when the user's or the
judge's model differs.

## Run from Python

Everything the command does is in the library. A run is a `Bench` played against an agent into the
run's folder, which a `RunJournal` writes; the report is built from the runs:

```python
import asyncio
from datetime import datetime
from pathlib import Path

from convy import Bench, Models, Report, RunJournal, Runs, RunSpec, Scenario
from convy.fakes import Echo, FakeModel

scenario = Scenario(
    id="greet",
    max_turns=3,
    instructions="Say hello to the assistant, then thank it.",
    claims=("The agent answered the greeting",),
)
models = Models(  # fakes: nothing is called; use OpenAiModel for real ones
    user=FakeModel("Hello!", "Thank you!", "###STOP###"),
    judge=FakeModel('{"claims": [{"pass": true, "reason": "it answered"}]}'),
)
bench = Bench((scenario,), models)
spec = RunSpec(
    id="first",  # the run's folder: results/echo/first/
    agent="echo",
    version="",
    user=models.user.name,
    judge=models.judge.name,
    k=bench.attempts,
    parallel=bench.parallel,
    turn_timeout=600,
    scenarios=bench.scenarios,
    started=datetime.now().astimezone(),
)
results = Path("results")
journal = RunJournal(results, spec)
journal.create()
outcomes = asyncio.run(journal.play(bench, Echo(), journal))
(run,) = Runs(results)
Path("results/echo/first/report.html").write_text(Report(run).html(), encoding="utf-8")
```

Put your own agent in place of `Echo()`. The fakes in `convy.fakes` are public too, for testing your
agent classes without a model.

## FAQ

**Does convy need to know which model my agent uses?**
No. convy talks to the agent, not to its model. Only convy's own models — the simulated user and the
judge — are set in `models.py`.

**My agent does not report tokens.**
Then the report shows time and results without tokens. If tokens matter, ask for them in the agent's
answer, or read them from the model gateway the agent uses.

**What do the exit codes mean?**
- `0` — every attempt finished;
- `1` — an attempt ended with an agent error or a failure of convy's models (for `convy resume`,
  an attempt it played);
- `2` — the project could not be loaded, or the run cannot be resumed, and nothing ran;
- `130` — the run was interrupted with Ctrl+C; `convy resume` continues it.

**Is it safe to run convy on someone else's project?**
`convy run` executes `models.py` and `agents/*.py`. Treat a project like its tests: run only what you
trust. See the [security policy](SECURITY.md).

## Documentation

| document | covers |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | how the code is laid out and the rules it keeps |
| [docs/decisions/](docs/decisions/) | why the main choices were made |
| [CHANGELOG.md](CHANGELOG.md) | what changed in each release |

## Contributing

Issues and pull requests are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) first, and follow the
[Code of Conduct](CODE_OF_CONDUCT.md). Report vulnerabilities privately, as the
[security policy](SECURITY.md) describes.

## License

[MIT](LICENSE)
