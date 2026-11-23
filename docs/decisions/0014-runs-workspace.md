# 14. One workspace for all runs

**Status:** Accepted

## Context

A run index and a separate page for every pair made it hard to compare several builds. A change
in pass rate could also reflect an easier suite, different scoring rules or missing attempts.

## Decision

Use one offline workspace at `results/index.html`. The table, metric groups, resource scatter
plot and scenario matrix share a filtered set of runs. Store summary data and link each scenario
to its run report for decisions and transcripts. This keeps dialogue text in one place.

Show each run’s pass rate and how many answers or tasks contributed to each resource metric.
Choosing a reference shows the difference in pass rates, in percentage points, when both runs
are complete and their recorded settings match.
The [workspace guide](../report.md#runs-workspace) defines those conditions. A snapshot describes
the recorded evaluation. Remote services and code imported by `models.py` can change between runs.

Keep the statistical check in `convy compare`. CI can use `--fail-on-regression` to get a
failing exit code.
The browser shows the observed difference without assigning a statistical verdict.

### How to compare the measurements

The UK Government Analysis Function recommends tables for looking up and comparing values.
NIST describes scatter plots as a way to examine the relationship between two measurements.
We use one column per run for reading a metric across builds, and one point per run for
exploring the tradeoff between quality and resource use.
[Table guidance](https://analysisfunction.civilservice.gov.uk/policy-store/data-visualisation-tables/),
[scatter plot guidance](https://www.itl.nist.gov/div898/handbook/eda/section3/scatterp.htm).

| Metric | Why display it this way |
| --- | --- |
| Attempt quality | Pair the pass rate with the number of passes and counted attempts. [Anthropic's guide to agent evals](https://www.anthropic.com/research/demystifying-evals-for-ai-agents) |
| Repeated scenarios | Count mixed results and scenarios that passed every planned attempt. One attempt alone gives no evidence of repeatability. [τ-bench](https://arxiv.org/abs/2406.12045) |
| Progress and coverage | Separate recorded/planned attempts from measured/recorded answers or tasks. Missing data and zero have different meanings. [UK Government Data Quality Framework](https://www.gov.uk/government/publications/the-government-data-quality-framework/the-government-data-quality-framework) |
| Errors | Compare errors by cause alongside the number of recorded attempts. [Prometheus instrumentation guidance](https://prometheus.io/docs/practices/instrumentation/#failures) |
| Time and total tokens | Show the mean, median, 90th percentile, minimum, maximum and sample size. For task totals, sum each task’s answers before comparing tasks. [Google SRE](https://sre.google/sre-book/monitoring-distributed-systems/#worrying-about-your-tail-or-instrumentation-and-performance-Yms9Ck) · [OpenTelemetry token metrics](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-token-metrics.md) |
| Token composition | Show token shares alongside tokens per measured answer. Include how often the agent reported cached and thinking tokens. [OpenTelemetry GenAI attributes](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/registry/attributes/gen-ai.md) |
| Tool invocations | Include failed tasks and measured zeroes. A task needs complete traces for a tool count. [Execute tool](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/execute-tool.md) · [Client inference](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/client-inference.md) |
| Named calls | Compare calls with the same name. Calls can overlap, so show their share of recorded call seconds and their seconds per answer. [OpenTelemetry traces](https://opentelemetry.io/docs/concepts/signals/traces/) |

## Alternatives and consequences

- A separate pair page duplicates reports and requires selecting two runs before seeing a tradeoff.
- Recomputing each pair’s rates on its shared scenarios would change a run’s displayed rate
  whenever the reference changed. Keeping the original rate lets users inspect a different
  suite in its own report.
