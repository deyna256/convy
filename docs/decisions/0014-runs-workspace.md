# 14. One workspace for all runs

**Status:** Accepted

## Context

A run index and a separate page for every pair made it hard to compare several builds. A change
in pass rate could also reflect an easier suite, different scoring rules or missing attempts.

## Decision

Use one offline workspace at `results/index.html`. The table, resource scatter plot and scenario
matrix share a filtered set of runs. Store summary data and link each scenario to its run report
for decisions and transcripts. This keeps dialogue text in one place.

Show each run’s original pass rate and measured resource coverage. Choosing a reference adds an
observed whole-run difference only for complete runs measured under matching recorded conditions.
The [workspace guide](../report.md#runs-workspace) defines those conditions. A snapshot describes
the recorded evaluation. Remote services and code imported by `models.py` can change between runs.

Keep the two-run statistical check in `convy compare` so CI can test a baseline and candidate
with its existing exit codes. The browser shows descriptive differences and the command prints its
verdict.

## Alternatives and consequences

- A separate pair page duplicates reports and requires selecting two runs before seeing a tradeoff.
- Recomputing each pair’s rates on its shared scenarios would give one run different pass rates
  depending on the chosen reference. Preserving whole-run rates leaves a visible gap when suites
  differ, while scenario-level evidence remains available in the individual reports.
