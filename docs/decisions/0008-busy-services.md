# 8. A busy service is reported by its caller and waited for by convy

**Status:** Accepted

## Context

Hosted models limit requests per minute, so a run meets "429 Too Many Requests" often. convy
retried only inside `JsonConnection`: four tries with fixed pauses of 2, 4 and 8 seconds, or the
service's `Retry-After`. Measured against a judge limited to 2 requests per second, 60 attempts:

- `Retry-After: 1` used up the four tries in about 3 seconds: 20 attempts had no verdict;
- every request that got a 429 came back at the same moment: up to 163 answers of 429 for 60
  decisions;
- an agent, model or judge of one's own got no retry at all, and a busy agent service failed the
  attempt and lowered the agent's pass rate.

A limit on requests at once ([0007](0007-participant-limits.md)) does not prevent this: with
quick answers one request at a time can still exceed a limit per minute.

The common advice is to wait at least as long as `Retry-After` asks, add a small random delay, back
off exponentially with jitter when the service says nothing, and cap both the tries and the total
time ([OpenAI, Rate limits](https://developers.openai.com/api/docs/guides/rate-limits);
[AWS, Exponential Backoff And Jitter](https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/)).

## Decision

- **The caller reports, convy decides.** Only the code that sent a request knows whether the
  service refused it before acting on it. An `Agent`, `Model` or `Judge` raises `Busy`, with the
  wait the service asked for, exactly then; `JsonConnection` does it for 429 and 503, and retries
  nothing itself. Anything else is a failure as before, so an agent never gets one message twice.
  A service that cannot be reached is not busy but gone, often at a wrong address: it fails at
  once rather than after two minutes of waiting.
- **One `Patience` for every participant.** It waits for a busy service for up to `seconds` in
  all (120 by default, two windows of a limit per minute): at least the asked wait plus a little
  more, or, without one, a random wait up to a window that doubles from 1 to 30 seconds. When the
  asked wait is longer than the time left, it gives up at once.
- **A busy service gets fewer requests at once.** Each time a participant's service says it is
  busy, the participant sends half as many requests at once, down to one, and one more again after
  as many answers, up to its limit: the limit of [0007](0007-participant-limits.md) is a ceiling,
  and convy finds the pace the service keeps up with, as promptfoo
  ([Rate Limits](https://www.promptfoo.dev/docs/configuration/rate-limits/)) and the adaptive
  mode of the AWS SDKs ([Retry behavior](https://docs.aws.amazon.com/general/latest/gr/api-retries.html))
  do. A request holds no place while it waits.
- **An agent whose service stays busy is not judged:** the attempt has no verdict, stops as
  `agent_busy`, and is left out of the pass rate. A model or judge that stays busy is a failure of
  convy's model, as before.
- **Waiting is not answering:** the time per answer and the turn's time limit count only the try
  that got the answer.

## Alternatives

- **Pause all of a participant's requests until the asked moment.** Tried first: the requests
  then went out together when the pause ended and collected their 429s again, and a run without
  `Retry-After` took 4.7 times as long.
- **Fix the retries in `JsonConnection` only.** Classes of one's own would still get none.
- **Retry any failure.** An agent may have acted on a message before it failed, so it would get it
  twice; and a wrong key or a broken answer would only be retried in vain.
- **A limit on requests per minute,** set per API. It avoids 429 instead of answering it, but needs
  the limit known in advance and cannot see a limit on tokens. It can come later, set like the
  limits of [0007](0007-participant-limits.md).

## Consequences

- An agent, model or judge of one's own gets the same handling by raising `Busy`.
- `JsonEndpoint` loses `pauses`: a breaking change of the alpha.
- Opening and closing a conversation are not retried; a busy service there ends the attempt without
  a verdict.
- `seconds` is set only from Python for now.
