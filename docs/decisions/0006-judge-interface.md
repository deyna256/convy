# 6. Let projects supply their own judge

**Status:** Accepted

## Context

In the shop demo, the same replacement offer received different verdicts on similar answers.
A yes/no decision alone could not tell users when the judge was unsure.

A model's stated confidence can be a poor guide to whether its verdict is correct. In
[Trust or Escalate](https://arxiv.org/abs/2407.18370), token probabilities were more informative,
but some gateways do not expose them. Teams that rely on confidence need to check their judge's
scores against human decisions on their own examples.

## Decision

A judge has a `name` and an async `decide(transcript, claims)` method. It returns one `Claim`
per claim text, with an optional reason and confidence from 0 to 1. The built-in
`ChatJudge(model)` asks a chat model to evaluate the dialogue and does not report confidence.
convy [removes answer steps](0010-answer-steps.md) before calling any judge.

Each run records its confidence threshold, `trust`. A positive decision below that threshold
fails the claim. A missing confidence value leaves the yes/no decision unchanged. The journal
keeps the judge's original decisions. See [attempt scoring](0012-claim-scoring.md).

## Alternatives and consequences

- A built-in confidence estimate or an integration with a particular scoring service would tie
  all projects to one method. The judge interface lets each project choose and test its own.
- Setting `trust` on the report command or with a slider would let the same saved run show
  different results. Storing it in the run makes those results reproducible.
- Dropping uncertain decisions would change how many claims count. Counting them as failures
  means that a strict confidence threshold can lower a run's score.

A judge that fails or returns invalid decisions leaves the attempt without a verdict. Runs with
different confidence thresholds retain their own scores. The CLI declines a regression verdict
for that comparison.
