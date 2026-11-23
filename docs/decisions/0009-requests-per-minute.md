# 9. Set a request rate for each participant

**Status:** Accepted

## Context

[Concurrency limits](0007-participant-limits.md) and [retries](0008-busy-services.md) alone
could not prevent frequent refusals. In a test, a judge that allowed two requests per second
answered in 0.05 seconds. Even one client could send requests too quickly. A provider may also
enforce a per-minute limit over shorter intervals. [Anthropic rate limits](https://platform.claude.com/docs/en/api/rate-limits)

## Decision

Each participant can have a requests-per-minute limit. Zero (the default) disables pacing.
The scheduler assigns requests start times separated by `60 / limit` seconds. Every try,
including a retry after `Busy`, gets its own start time. Waiting for that time does not count
toward the agent's recorded answer time or `--turn-timeout`.

The retry budget starts at the first refusal. The initial wait for a slot or scheduled start
time therefore leaves the full budget available. See [busy services](0008-busy-services.md).

Configure `agent_per_minute`, `user_per_minute` and `judge_per_minute` alongside the concurrency
limits. An agent-specific table can override `per_minute`. The workspace compares the initial
limits recorded in each run. Resume warns about a change to either of the agent's limits.
See [Runs](../runs.md#how-much-runs-at-once) and [the workspace decision](0014-runs-workspace.md).

## Alternatives and consequences

- Allowing a burst of requests at the start of a minute can exceed the provider's per-second limit.
- Per-key limits in the HTTP client would exclude custom participants. If the simulated user
  and judge share a key, divide its allowance between them.
- The client learns token usage after a request. It can respond to a token-limit refusal with
  `Busy`, but cannot schedule requests by exact token count in advance.

In the two-requests-per-second test, 108 requests per minute produced no refusals. At the
advertised limit of 120, about 20 requests were refused. Network delays can bring arrivals
closer together even when the client spaces their start times.
