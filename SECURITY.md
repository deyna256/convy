# Security policy

## Supported versions

While the version is `0.x`, only the latest release receives security fixes.

## Reporting a vulnerability

Report it privately through
[GitHub's vulnerability reporting](https://github.com/deyna256/convy/security/advisories/new),
not in a public issue. Include the affected version, what an attacker can do and the steps to reproduce it.
Keep real credentials, agent answers and other private data out of the report.

## What convy trusts

- **Project files are code.** `convy run` imports `models.py` and `agents/*.py` from the project and runs
  them in its own process. Run convy only on projects you trust, as you would run their tests.
- **Keys** come from `.env` or the environment through `SecretStr` fields and should never appear in
  output, runs or the report. Models are recorded by name only.
- **Runs and the report contain the dialogues** with the agent, which may hold private data from the
  agent's answers, and the text of every scenario played. `results/` is ignored by git in projects
  created by `convy init`.
- **Agent answers are untrusted text.** The report shows them only as text, so an answer cannot run
  code in the page.

Relevant areas include how keys and certificates are handled, what convy sends to its models (the
scenario's instructions and the dialogue), and how the report embeds dialogue text in HTML.
