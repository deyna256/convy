# 7. Set a separate concurrency limit for each participant

**Status:** Accepted

## Context

An agent may support 50 open conversations while its judge can handle only two requests at once.
Another agent may need to run one conversation at a time because conversations share a token
counter. The former `--parallel` flag held one slot from the start of the conversation until the
judge finished. It forced all three participants to use the same limit.

## Decision

Give the agent, simulated user and judge separate limits. An agent slot covers an open
conversation. A user or judge slot covers one request attempt. Judging starts after the agent's
conversation closes. Waiting for an agent slot consumes none of the agent's turn timeout.

Set the limits in the project's `[tool.convy]` table. An agent can have its own settings, and
environment variables can override file settings. See [Runs](../runs.md#how-much-runs-at-once).
This follows practices used by [Inspect](https://inspect.aisi.org.uk/models-concurrency.html)
for model limits and [Locust](https://locust.readthedocs.io/en/stable/configuration.html) for
configuration.

A run records its initial limits. Resume uses the project's current limits and warns if the
agent's limit changed. The [workspace](0014-runs-workspace.md) checks the recorded limits before
showing a difference from a reference run.

## Alternatives and consequences

- One limit per run makes a slow judge throttle an agent that could handle more conversations.
  Separate CLI flags would make shared CI configurations harder to maintain.
- Storing limits in an agent's Python file would change its fingerprint every time the team
  adjusted its load, preventing resume. Environment-only settings would be hard to share.
- [Decision 8](0008-busy-services.md) later added temporary reductions when a service reports
  that it is busy. The configured concurrency remains the upper limit.

The change removed `--parallel` and the `parallel` fields of `Bench` and `RunSpec`. If an agent
resumes under a different load, its reported answer times span both loads.
