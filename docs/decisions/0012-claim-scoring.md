# 12. Required claims and a run's passing threshold

**Status:** Accepted

## Context

Requiring every claim to pass hides partial progress: nine of ten and one of ten both fail.
Some requirements are essential even when most others hold. Excluding low-confidence judgments
also changes the sample, so uncertainty can make a pass rate look better.

## Decision

Separate the judge's observations from acceptance. A scenario holds immutable `Requirement`
records; the judge sees only their texts and returns independent yes/no `Claim` decisions.
The run records its confidence floor and a claim completion threshold. Required claims can block
acceptance regardless of completion. The complete rule lives in
[Passing an attempt](../scenarios.md#passing-an-attempt).

`Scenario.score` computes one `Score` for a valid verdict. The CLI and report share that result;
there is no browser scoring implementation. Preserve raw decisions, reasons and confidence, and
show insufficient confidence separately from a negative judgment. Keep computed scores out of
the journal and [raw tables](0011-run-as-data.md).

Required flags belong to the scenario snapshot; thresholds belong to the run. Resume uses both
unchanged. A changed required flag makes that scenario different for comparison. Different
scoring settings prevent a quality regression or improvement verdict, while resource measurements
remain available. Compatibility follows the [run-format decision](0005-runs.md): no converters or
legacy scoring branches.

## Alternatives and consequences

- **Only a percentage threshold:** a high score could hide a failed essential requirement.
- **Only required claims:** optional claims would never affect acceptance. Combining a threshold
  with required claims keeps both completeness and essential requirements meaningful.
- **Weighted or graded claims:** more expressive, but harder to author and interpret. Equal yes/no
  contributions keep the completion fraction clear; ordered grades are removed.
- **Exclude low-confidence decisions:** changes the denominator. Counting them as failures makes
  insufficient evidence visible, but means a strict or poorly calibrated judge can lower results.
- **Give the judge the acceptance policy:** could influence its independent decisions. Keeping
  that policy in convy permits deterministic scoring without additional judge calls.

The default threshold preserves all-claims acceptance for trusted decisions in new runs. The Python
scenario input and verdict-scoring APIs change, and earlier run formats must be produced again.
