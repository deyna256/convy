<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/deyna256/convy/main/docs/assets/mark-dark.svg">
  <img alt="convy" src="https://raw.githubusercontent.com/deyna256/convy/main/docs/assets/mark-light.svg" height="72">
</picture>

<h3>Did the new build make your agent worse?</h3>

<p>A simulated user talks to your agent through its API, a judge checks every claim,<br>
and convy shows what passed, what it cost and what changed.</p>

[![PyPI](https://img.shields.io/pypi/v/convy)](https://pypi.org/project/convy/)
[![Python](https://img.shields.io/pypi/pyversions/convy)](https://pypi.org/project/convy/)
[![CI](https://github.com/deyna256/convy/actions/workflows/ci.yml/badge.svg)](https://github.com/deyna256/convy/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](https://github.com/deyna256/convy/blob/main/LICENSE)

[Live report](https://deyna256.github.io/convy/report.html) ·
[Quick start](https://github.com/deyna256/convy#quick-start) ·
[Docs](https://github.com/deyna256/convy/tree/main/docs) ·
[Changelog](https://github.com/deyna256/convy/blob/main/CHANGELOG.md)

</div>

<p align="center">
  <img alt="convy runs a support bot's new build: each attempt prints as it ends, then convy compare writes a page for the old and new build" src="https://raw.githubusercontent.com/deyna256/convy/main/docs/assets/demo.gif" width="800">
</p>

<p align="center">
  <a href="https://deyna256.github.io/convy/report.html"><b>See a real report →</b></a>
  &nbsp;&nbsp;
  <a href="https://deyna256.github.io/convy/compare.html"><b>See a comparison →</b></a>
</p>

## Why convy

You change a prompt, a model or a tool. Does the agent still behave in a real conversation? convy
answers that, and nothing more.

- **Any agent behind an API.** A JSON API takes a few lines of settings. Anything else takes two
  small classes. convy needs neither the agent's code nor its model.
- **Real conversations.** The simulated user asks vague questions, changes its mind and gives
  details late. The judge checks plain-language claims about the dialogue.
- **Numbers you can act on.** Pass rate over repeated attempts, the agent's tokens and its answer
  time. And a page that shows what changed between two builds.
- **Small.** Four dependencies. No platform, no account, no containers.

## Quick start

```sh
uvx convy init my-bench              # a project with examples
cd my-bench
uv run convy run echo --smoke        # check convy itself: free, no models called
cp .env.example .env                 # add the address and key of your model gateway
uv run convy run echo                # a real run with the simulated user and the judge
```

convy prints where the report is: `results/<agent>/<run>/report.html`. Open it in a browser.

A new project looks like this:

```text
my-bench/
├── gateway.py        # the model gateway, shared by models.py and the agents
├── models.py         # the models that play the user and the judge
├── agents/           # one file per agent
├── scenarios/        # one YAML file per scenario, in folders if you like
└── results/          # a folder per run with its report, and the index
```

## Write a scenario

A scenario says who the user is, what they want, and what must be true of the dialogue:

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

The judge decides each claim on its own and says why. The report shows which claim failed, in which
attempt, next to the dialogue. More in
[Scenarios](https://github.com/deyna256/convy/blob/main/docs/scenarios.md).

## Connect your agent

An agent with a JSON API needs only settings. Put this in `agents/support_bot.py`:

```python
from convy import JsonAgent, JsonEndpoint

agent = JsonAgent(
    JsonEndpoint("https://bot.example.com/api/chat"),
    body={"session_id": "{session}", "message": "{text}"},
    reply="data.answer",
    tokens=("data.usage.input_tokens", "data.usage.output_tokens"),
)
```

Then check the connection and run it:

```sh
uv run convy run support_bot --smoke   # the agent answers for real, nothing else is called
uv run convy run support_bot -k 3      # every scenario, three attempts each
```

Keys, streaming, logins, blocking clients and certificates are in
[Connect an agent](https://github.com/deyna256/convy/blob/main/docs/agents.md).

## Compare two builds

Run the old build and the new one, then name the two runs:

```sh
uv run convy compare 7ad8 5e85       # before, then after
```

The page shows each number before and after. Green is better, red is worse, and grey with `~` means
the change is within noise. Scenarios are grouped as Worse, Better and Same, and you can read both
dialogues side by side. More in
[The report](https://github.com/deyna256/convy/blob/main/docs/report.md).

## convy and other tools

Checked against their docs on 8 October 2026.

- [**Scenario**](https://github.com/langwatch/scenario) by LangWatch also has a simulated user and a
  judge. You write scenarios as code in Python, TypeScript or Go and run them with pytest or vitest.
  Pick it if you want scenarios next to your tests, or to script a dialogue step by step.
- [**promptfoo**](https://www.promptfoo.dev/docs/providers/simulated-user/) tests prompts, models
  and agents, and does red teaming. Its simulated user is one provider among many. Pick it if you
  need a wide toolkit.
- [**deepeval**](https://deepeval.com/docs/conversation-simulator) has a conversation simulator you
  call from Python, and many ready metrics. Pick it if you want those metrics.

convy does one job. It checks a running agent through its API, with scenarios in YAML, repeated
attempts and a verdict per claim. Then it shows what changed between two builds, and whether the
change is real or noise. The report is a file: no account, no server.

## Status

convy is in alpha. The Python API and the format of runs may change before 1.0. Every change is in
the [changelog](https://github.com/deyna256/convy/blob/main/CHANGELOG.md).

`convy run` runs `models.py` and `agents/*.py`. Treat a project like its tests: run only what you
trust. See the [security policy](https://github.com/deyna256/convy/blob/main/SECURITY.md).

## Documentation

| page | what is in it |
|---|---|
| [Connect an agent](https://github.com/deyna256/convy/blob/main/docs/agents.md) | JSON agents, your own classes, tokens, certificates |
| [Scenarios](https://github.com/deyna256/convy/blob/main/docs/scenarios.md) | how to write them, verdicts, `convy run` options |
| [Runs](https://github.com/deyna256/convy/blob/main/docs/runs.md) | the run folder, stop and resume, exit codes |
| [The report](https://github.com/deyna256/convy/blob/main/docs/report.md) | tiles, statuses, the scenario window, comparing runs |
| [Run from Python](https://github.com/deyna256/convy/blob/main/docs/python.md) | the library behind the command |
| [The shop demo](https://github.com/deyna256/convy/tree/main/examples/shop) | the bot behind the live report |
| [Architecture](https://github.com/deyna256/convy/blob/main/ARCHITECTURE.md) | for people who change convy's code |

## Contributing

Issues and pull requests are welcome. Read
[CONTRIBUTING.md](https://github.com/deyna256/convy/blob/main/CONTRIBUTING.md) first, and follow the
[Code of Conduct](https://github.com/deyna256/convy/blob/main/CODE_OF_CONDUCT.md). Report
vulnerabilities privately, as the
[security policy](https://github.com/deyna256/convy/blob/main/SECURITY.md) says.

## License

[MIT](https://github.com/deyna256/convy/blob/main/LICENSE)
