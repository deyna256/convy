# 10. The answer is made of steps; the judge sees only what was said

**Status:** Accepted

## Context

A report could show that an agent took 90 seconds per answer, but not why. convy treats the agent
as a black box; the agent's owner knows what happened but had no way to tell convy. Besides its
text and tokens, an answer had only `Thinking`: one block of text, with no time and no order, which
cannot hold an agent that thinks, calls a tool, then thinks again. A judge could read it if it set
`reviews_agent_thinking`.

Model APIs give an answer as ordered parts, thinking being one kind, with one usage per response
(Anthropic's content blocks, OpenAI's output items, pydantic-ai's parts). Tracing tools add a start
and a duration per step, as absolute times (OTel, Langfuse, the OpenAI Agents SDK).

What an agent writes as its thinking is not a faithful record of what it does
([Anthropic](https://www.anthropic.com/research/reasoning-models-dont-say-think)); judges are
swayed by reasoning they read ([arXiv 2410.02736](https://arxiv.org/pdf/2410.02736)); and "it's
often better to grade what the agent produced, not the path it took"
([Anthropic](https://anthropic.com/engineering/demystifying-evals-for-ai-agents)).

## Decision

- **An answer is its text, its total usage and its steps in order**, a step being a `Thought` or a
  `Call`; the thinking is a thought. How to give them is in [Connect an agent](../agents.md#steps).
- **convy shows the steps and checks nothing between them and its own numbers:** it neither adds up
  the calls' tokens nor sets the calls against its own time of the answer. Calls are placed against
  each other, by the agent's clock, which needs an absolute time with a time zone.
- **A text a call sent or received is reported or not:** an empty result is not a missing one.
- **The judge sees only what the user and the agent said**; `reviews_agent_thinking` is removed.
- **Only an agent's own class gives steps** for now.

## Alternatives

- **A trace next to the answer.** No break, but three fields that overlap.
- **Usage summed from the steps.** A partial trace would understate it silently.
- **Calls on convy's time of the answer,** with the time no call covers. It needs two clocks to
  agree, and compares the agent's numbers with convy's.
- **convy times the steps itself,** through an object given to `answer()`: exact, but only for
  work in convy's process. It can come later.
- **A judge that reads thinking or steps.** Thinking is not faithful, and grading the path makes
  tests brittle.

## Consequences

- An answer shows where its time and tokens went, as far as the agent tells; a wrong report is
  shown as given, and a step convy cannot store fails the turn.
- `Answer` and the judge interface change, a break of the alpha. Runs move to format 5
  ([0005](0005-runs.md)).
