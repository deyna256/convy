# 9. A participant can keep to a limit of requests per minute

**Status:** Accepted

## Context

convy limits a participant's requests under way at once ([0007](0007-participant-limits.md)) and
waits for a busy service ([0008](0008-busy-services.md)), but not how many requests it sends per
minute. A service that answers quickly can be sent far more than its limit even one request at a
time: a judge limited to 2 requests per second that answers in 0.05 s met 275 to 562 answers of 429
for 60 decisions. None was lost, but each reached the service.

Hosted models publish their limits per minute, and may enforce them over shorter times: "a rate of
60 requests per minute (RPM) might be enforced as 1 request per second. Short bursts of requests can
exceed the limit" ([Anthropic, Rate limits](https://platform.claude.com/docs/en/api/rate-limits)).

## Decision

- **A limit per minute for each participant,** set next to its limit at once: `agent_per_minute`,
  `user_per_minute` and `judge_per_minute` under `[tool.convy]`, `per_minute` in an agent's own
  table, and `CONVY_*` variables over them. 0, the default, is no limit.
- **Requests are spaced evenly,** one every 60 / limit seconds, with no burst, since a limit per
  minute may be enforced per second.
- **Every try counts,** a try again after `Busy` too. The wait for its turn counts neither in the
  time per answer nor against `--turn-timeout`, like the wait for a place.

## Alternatives

- **A token bucket that allows a burst.** Faster at the start of a run, but a burst is what a
  service enforcing its limit per second refuses.
- **A limit per API key,** set on `JsonEndpoint`. It fits a key shared by the user and the judge,
  but only for convy's own classes, and as code, not a setting.
- **Limits on tokens per minute.** A request's tokens are known only after its answer, so convy
  cannot keep to them in advance; `Busy` handles them.

## Consequences

- A limit set a little below the provider's meets no 429: against the judge above, 108 a minute
  met none and 120, the service's own limit, met about 20, since delays on the way bring two
  requests closer. An unknown limit is still found through `Busy`.
- The user and the judge on one key each need their share of its limit.
