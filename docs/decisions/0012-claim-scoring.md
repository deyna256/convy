# 12. Score attempts with required claims and a passing threshold

**Status:** Accepted

## Context

Under an all-or-nothing rule, passing nine of ten claims gives the same outcome as passing
one. A simple percentage has the opposite problem. An agent could pass while missing a
requirement the author considers essential.

## Decision

The scenario author can mark a claim as required. The judge receives the claim texts and
returns a yes/no decision for each one. convy applies the run's `trust` setting to those
decisions, then checks two conditions. Every required claim must hold, and the fraction of
**all** claims that hold must meet `claim_threshold`. The default threshold is 1.0.
[Passing an attempt](../scenarios.md#passing-an-attempt)

`Scenario.score` supplies this calculation to the CLI and report. The journal and
[exports](0011-run-as-data.md) keep the original decisions, reasons and confidence. A report
can therefore show whether a claim failed because the judge said no or because its confidence
was too low.

The run saves the scenario's required flags and the run's thresholds for resume. Changing a
required flag changes the scenario snapshot. Different scoring settings prevent a quality
comparison. Resource measurements remain available.

## Alternatives and consequences

- Requiring only the essential claims would make optional claims irrelevant to passing.
- Weighted or graded claims would make it harder to explain how much each claim contributes.
  Each yes/no claim counts once.
- Dropping low-confidence claims could raise the pass rate as the judge became less certain.
  They count as failed claims instead.
- Giving the scoring policy to the judge could influence its decisions. convy can apply the
  rule to the raw verdict without another judge call.

The change removed ordered grades and changed the Python scoring API. See
[run compatibility](0005-runs.md).
