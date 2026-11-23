# 10. Record answer steps and hide them from the judge

**Status:** Accepted

## Context

An answer that took 90 seconds gave no clue which operation took the time. The agent knew what
it did, but an answer could contain only one block of `Thinking` alongside its text and tokens.
That could not represent an agent that thought, called a tool, then thought again.

Model APIs return ordered parts, and tracing systems record the start time and duration of each
operation. These details are useful for diagnosis. An agent's account of its reasoning can be
unreliable, and showing it to a judge can change the verdict.
[Research on reasoning traces](https://www.anthropic.com/research/reasoning-models-dont-say-think) ·
[Research on judge bias](https://arxiv.org/pdf/2410.02736)

## Decision

An agent implementation can attach an ordered list of `Thought` and `Call` steps to its
`Answer`, alongside the reply and its total usage. Calls carry timestamps with a time zone
so the report can place them on the agent's timeline. Sent and received text can be missing;
a reported empty string remains distinguishable from missing text.
[Agent steps](../agents.md#steps) · [Tool counts](0013-tool-invocations.md)

The report shows the step durations and tokens the agent supplied. It keeps the total answer
usage separate because a trace can omit calls. It measures total answer time on convy's clock.

The judge evaluates the exchange without seeing these steps. A Python judge receives a transcript
with empty steps and `steps_complete=False`; turn durations and reported usage remain in its
records. The built-in chat judge sends only the conversation text and claims to the judge model.

## Alternatives and consequences

- A second trace object alongside `Thinking` would represent the same information twice.
- Subtracting call durations from convy's answer time would mix clocks and could double-count
  overlapping calls. Timing every step inside convy would miss work inside a remote service.
- The change replaced `Thinking` and removed `reviews_agent_thinking`. A step that convy cannot
  store fails the turn. See [run compatibility](0005-runs.md).
