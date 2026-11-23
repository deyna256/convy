# 8. Retry requests that a busy service refused

**Status:** Accepted

## Context

The original HTTP client tried each request four times, with fixed delays or the server's
`Retry-After` value. In a test of 60 attempts against a judge limited to two requests per
second, 20 attempts ended without a verdict. Requests retried together and caused another wave
of refusals. Custom agents and models had no equivalent retry handling.

## Decision

An agent, model or judge raises `Busy` when its service refused a request before acting on it.
The built-in JSON client reports HTTP 429 and 503 this way. Connection failures and errors that
may have occurred after processing are ordinary failures. Retrying those could repeat an
action the agent already took.

Each participant has a retry budget, `Patience.seconds` (120 seconds by default). The budget
starts at the first refusal. If the server asks for more time than remains, convy gives up.
Otherwise it waits for the requested delay plus a small random interval, up to the remaining
budget. Without a requested delay, it picks a random wait from a window that doubles from
1 second to a maximum of 30. Random delays spread retries across time.
[OpenAI rate limits](https://developers.openai.com/api/docs/guides/rate-limits) ·
[AWS backoff and jitter](https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/)

A refusal during a request halves the participant's concurrency, down to one. After as many
successes as its current limit, convy allows one more, up to the
[configured maximum](0007-participant-limits.md). User and judge requests release their slots
between tries. An open agent conversation retains its slot. Answer time covers the individual
turn and excludes the wait before a retry.

## Alternatives and consequences

- Pausing every request for the same interval caused bursts when the pause ended. In one test
  without `Retry-After`, this took 4.7 times as long as using separate delays.
- Retrying only in the HTTP client would exclude custom implementations.
  [Decision 9](0009-requests-per-minute.md) added pacing for services with a known rate limit.
- If an agent remains busy, the attempt ends as `agent_busy` and receives no verdict.
  A simulated user or judge that remains busy produces a model failure, also without a verdict.
- Opening and closing a conversation are each tried once. A refusal at either point ends the
  attempt without a verdict.
- The change removed `JsonEndpoint.pauses`. Python callers can configure `Patience`.
