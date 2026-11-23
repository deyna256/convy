<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/deyna256/convy/main/docs/assets/mark-dark.svg">
  <img alt="convy" src="https://raw.githubusercontent.com/deyna256/convy/main/docs/assets/mark-light.svg" height="72">
</picture>

<h3>Did the new build make your agent worse?</h3>

<p>A simulated user talks to your agent through its API.<br>
A judge checks the dialogue against the claims in your scenario.</p>

[![PyPI](https://img.shields.io/pypi/v/convy)](https://pypi.org/project/convy/)
[![Python](https://img.shields.io/pypi/pyversions/convy)](https://pypi.org/project/convy/)
[![CI](https://github.com/deyna256/convy/actions/workflows/ci.yml/badge.svg)](https://github.com/deyna256/convy/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](https://github.com/deyna256/convy/blob/main/LICENSE)

[Quick start](https://github.com/deyna256/convy#quick-start) ·
[Docs](https://github.com/deyna256/convy/tree/main/docs) ·
[Changelog](https://github.com/deyna256/convy/blob/main/CHANGELOG.md)

</div>

<p align="center">
  <img alt="Historical recording of a shop bot run and its two-build comparison" src="https://raw.githubusercontent.com/deyna256/convy/main/docs/assets/demo.gif" width="800">
</p>

<p align="center">
  <a href="https://deyna256.github.io/convy/report.html"><b>See a real report →</b></a>
  &nbsp;&nbsp;
  <a href="https://deyna256.github.io/convy/compare.html"><b>See the historical comparison →</b></a>
</p>

## What convy measures

A scenario gives the simulated user a task and lists the claims a judge should check.
Run each scenario several times to see which attempts pass, how long the agent takes to answer,
and how many tokens and tool calls it reports. Open a failed attempt to read the dialogue
alongside the judge's decisions.

## Quick start

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then create a project.

```sh
uvx convy init my-bench              # a project with examples
cd my-bench
uv run convy run echo --smoke        # check convy itself: free, no models called
cp .env.example .env
```

The commands above install the published release. To try the features described on `main`,
run `uv add --editable /path/to/convy` in `my-bench`, using the path to your local checkout.

Set `GW_BASE_URL` and `GW_API_KEY` in `.env` for your OpenAI-compatible gateway.
Check the model names in `models.py`, then run `uv run convy run echo` to play the scenarios.

Open `results/index.html` in a browser to see the runs. Each one links to its own
`results/<agent>/<run>/report.html` with the judge’s decisions and the dialogues.

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

A scenario says who the user is, what they want, and what the judge should check:

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

The judge marks each claim as passed or failed and can give a reason. The report shows which claim failed, in which
attempt, next to the dialogue. More in
[Scenarios](https://github.com/deyna256/convy/blob/main/docs/scenarios.md).

## Connect your agent

An agent with a JSON API needs only settings. Put this in `agents/support_bot.py`:

```python
from convy import JsonAgent, JsonEndpoint, TokenPaths

agent = JsonAgent(
    JsonEndpoint("https://bot.example.com/api/chat"),
    body={"session_id": "{session}", "message": "{text}"},
    reply="data.answer",
    tokens=TokenPaths(input="data.usage.input_tokens", output="data.usage.output_tokens"),
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

Open `results/index.html` after running both builds. Compare their pass counts, answer times,
token use and tool calls. Choose a reference to see pass-rate differences for comparable runs,
or open a scenario from the matrix to read the dialogue that explains a failure.

In CI, identify the baseline and candidate by run ID or unique suffix.

```sh
uv run convy compare 7ad8 5e85 --fail-on-regression   # before, then after
```

With both runs loaded, exit code 3 means the check found evidence of a regression
or could not compare the runs.
See [The report](https://github.com/deyna256/convy/blob/main/docs/report.md) and
[CI exit codes](https://github.com/deyna256/convy/blob/main/docs/runs.md#fail-ci-when-the-pass-rate-regresses).

## convy and other tools

convy uses YAML scenarios and writes offline reports. For scenarios written in code, see
[LangWatch Scenario](https://github.com/langwatch/scenario). If you already use an evaluation
framework, see [promptfoo’s simulated user](https://www.promptfoo.dev/docs/providers/simulated-user/)
or [DeepEval’s conversation simulator](https://deepeval.com/docs/conversation-simulator).

## Status

convy is in alpha. The Python API and the format of runs may change before 1.0. See the
[changelog](https://github.com/deyna256/convy/blob/main/CHANGELOG.md).

`convy run` executes project Python files, including the selected agent. Run projects you trust. See the [security policy](https://github.com/deyna256/convy/blob/main/SECURITY.md).

## Documentation

| page | what is in it |
|---|---|
| [Connect an agent](https://github.com/deyna256/convy/blob/main/docs/agents.md) | JSON agents, your own classes, tokens, certificates |
| [Scenarios](https://github.com/deyna256/convy/blob/main/docs/scenarios.md) | how to write them, verdicts, `convy run` options |
| [The judge](https://github.com/deyna256/convy/blob/main/docs/judge.md) | how sure it is, `--trust`, your own judge |
| [Runs](https://github.com/deyna256/convy/blob/main/docs/runs.md) | the run folder, stop and resume, exit codes |
| [The report](https://github.com/deyna256/convy/blob/main/docs/report.md) | runs workspace, scenario details, two-run CLI comparison |
| [Results as data](https://github.com/deyna256/convy/blob/main/docs/results.md) | a run as tables, convy export, pandas |
| [Run from Python](https://github.com/deyna256/convy/blob/main/docs/python.md) | the library behind the command |
| [The shop demo](https://github.com/deyna256/convy/tree/main/examples/shop) | the bot behind the recorded demo |
| [Architecture](https://github.com/deyna256/convy/blob/main/ARCHITECTURE.md) | for people who change convy's code |

## Contributing

Issues and pull requests are welcome. Read
[CONTRIBUTING.md](https://github.com/deyna256/convy/blob/main/CONTRIBUTING.md) first, and follow the
[Code of Conduct](https://github.com/deyna256/convy/blob/main/CODE_OF_CONDUCT.md). Report
vulnerabilities privately, as the
[security policy](https://github.com/deyna256/convy/blob/main/SECURITY.md) says.

## License

[MIT](https://github.com/deyna256/convy/blob/main/LICENSE)
