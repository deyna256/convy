# Security policy

## Supported versions

While the version is `0.x`, only the latest release receives security fixes.

## Reporting a vulnerability

Report it privately through
[GitHub's vulnerability reporting](https://github.com/deyna256/convy/security/advisories/new),
not in a public issue. Include the affected version, what an attacker can do and the steps to reproduce it.
Keep real credentials, agent answers and other private data out of the report.

## What convy trusts

- **Project files are code.** Running or resuming a benchmark executes project Python files
  in the convy process. Only run projects you trust.
- **Keys** come from `.env` or the environment through `SecretStr` fields and should never appear in
  output, runs or the report. Models are recorded by name only.
- **Run files, reports and exports can contain private data**, including scenario instructions,
  dialogue text, tool inputs and outputs, and error messages. `results/` is ignored by git in projects
  created by `convy init`.
- **Agent answers are untrusted text.** The report shows them only as text, so an answer cannot run
  code in the page.
