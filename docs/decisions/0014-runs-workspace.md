# 14. One workspace for all runs

**Status:** Accepted

## Context

A run index and a separate page for every pair made it hard to compare several builds. A change
in pass rate could also reflect an easier suite, different scoring rules or missing attempts.

## Decision

Use one offline workspace at `results/index.html`. The table, metric groups, resource scatter
plot and scenario matrix share a filtered set of runs. Store summary data and link each scenario
to its run report for decisions and transcripts. This keeps dialogue text in one place.

Show each run’s original pass rate and measured resource coverage. Choosing a reference adds an
observed whole-run difference only for complete runs measured under matching recorded conditions.
The [workspace guide](../report.md#runs-workspace) defines those conditions. A snapshot describes
the recorded evaluation. Remote services and code imported by `models.py` can change between runs.

Keep the two-run statistical check in `convy compare` so CI can test a baseline and candidate
with its existing exit codes. The browser shows descriptive differences and the command prints its
verdict.

### How to compare the measurements

| Metric | What the sources establish | What convy shows and why |
| --- | --- | --- |
| Attempt quality | One successful trial and consistent success across trials answer different evaluation questions. [Anthropic's guide to agent evals](https://www.anthropic.com/research/demystifying-evals-for-ai-agents) | Show the observed pass rate with passed and counted attempts. Use the scatter plot to see how much time or how many tokens each run used at that rate. |
| Repeated scenarios | Replaying the same task can reveal inconsistent outcomes. [τ-bench](https://arxiv.org/abs/2406.12045) | Count mixed-result scenarios and those that passed every planned attempt. Group scenarios by their observed pass rates, giving each scenario one vote. A single trial gives no evidence about repeatability. |
| Progress and coverage | Completeness can differ across records and across fields within a record. [UK Government Data Quality Framework](https://www.gov.uk/government/publications/the-government-data-quality-framework/the-government-data-quality-framework) | Show recorded/planned attempts and measured/recorded answers or tasks separately. A run can finish with only half its answers reporting usage. Keep measured zeroes and mark unavailable statistics. |
| Errors | A failure count needs the number of attempts to put it in proportion. [Prometheus instrumentation guidance](https://prometheus.io/docs/practices/instrumentation/#failures) | Compare counts by cause alongside recorded attempts. Agent failures count against quality. Busy services and evaluation-model errors leave attempts without a verdict. |
| Time and total tokens | A mean can conceal slow requests in the tail. GenAI instrumentation also records token usage as a distribution. [Google SRE](https://sre.google/sre-book/monitoring-distributed-systems/#worrying-about-your-tail-or-instrumentation-and-performance-Yms9Ck), [OpenTelemetry token metrics](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-token-metrics.md) | Align median, P90, extremes, mean and sample size for the same unit in every run. Summing the answers within each attempt first gives the distribution of task totals. |
| Token composition | Cached input and reasoning output belong inside their respective totals. A percentage breakdown conveys composition, while absolute amounts convey scale. [OpenTelemetry GenAI attributes](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/registry/attributes/gen-ai.md), [Statistics Canada chart guidance](https://www150.statcan.gc.ca/n1/pub/89-26-0005/892600052022001-eng.htm) | Pair each part's share with tokens per measured answer. Show cache and thinking coverage so a smaller reported part can be distinguished from less instrumentation. |
| Tool invocations | OpenTelemetry distinguishes executing a named tool from asking a model for a response. [Execute tool](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/execute-tool.md), [Client inference](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/client-inference.md) | Compare calls per task across attempts whose answer traces are complete. Include observed zeroes. This keeps a run with missing traces from appearing more efficient. |
| Named calls | Trace spans measure individual operations and can nest or overlap. [OpenTelemetry traces](https://opentelemetry.io/docs/concepts/signals/traces/) | Align the same call name across runs. Its share of all recorded call seconds identifies where instrumented work went. Its seconds per answer show the magnitude. Inspect the run report for individual calls. |

## Alternatives and consequences

- A separate pair page duplicates reports and requires selecting two runs before seeing a tradeoff.
- Recomputing each pair’s rates on its shared scenarios would give one run different pass rates
  depending on the chosen reference. Preserving whole-run rates leaves a visible gap when suites
  differ, while scenario-level evidence remains available in the individual reports.
