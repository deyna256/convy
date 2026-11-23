# The report

Open `results/index.html` to [compare runs](#runs-workspace). Open a run's
`results/<agent>/<run>/report.html` to see why it passed or failed. Both pages work offline.
The [recorded shop demo](https://deyna256.github.io/convy/report.html) shows an earlier version
of the report.

## Tiles

The tiles at the top of a run report summarize quality and resource use.

- **Pass rate** shows how many counted attempts passed. Agent failures count as failures.
  Attempts with a judge verdict follow the [claim scoring rule](scenarios.md#passing-an-attempt).
  Attempts without a verdict are excluded. For example, eight passes, two agent failures and two
  attempts without a verdict give a pass rate of 80% (8/10). The bar below groups scenarios by
  their pass rate, with unjudged scenarios last.
- **Flaky scenarios** counts scenarios with both a pass and a failure among their counted attempts.
- **Errors** counts agent failures, attempts where the agent stayed busy, and evaluation model failures.
- **Time** and **Tokens** show the mean and median per answer and per task attempt.
  **Tool calls** shows both per task attempt. Each tile gives the number measured out of the number
  recorded, so you can see how much data went into a value.

## Measured population

A task attempt is one play of a scenario. It can contain several answers. For example, an attempt
with answers of 2 and 4 seconds contributes two answer times and one task time of 6 seconds.
The run uses each measured answer or task once. All recorded attempts qualify, including failures
and attempts without a verdict.

| Metric | What one task contributes |
|---|---|
| Time | The sum of recorded answer durations. This excludes time spent opening or closing the conversation, waiting to retry, and running the simulated user or judge. |
| Tokens | The sum of input and output tokens when every recorded answer reports usage. An answer with known usage still contributes to the per-answer statistics if another answer has missing usage. |
| Tool calls | The total across answers when every recorded answer has a complete trace. |

An attempt with no recorded answers contributes to the recorded task count but has no measured
time, tokens or calls. A reported zero counts as a measurement. A dash means the measurement is
unavailable. The single-run report can exclude [outliers](#cutting-outliers).

### Tool invocations

Each recorded [step](agents.md#steps) with `Call(kind="tool")` counts once, including retries
and failed calls. Model calls and thoughts contribute zero. An answer has a known count only
when `steps_complete=True`. A complete, empty trace means zero calls. If the trace is partial,
the report shows any visible calls and leaves the count unknown.

An agent failure during an answer records an error with no complete trace, so the task's tool
count is unknown. A failure while closing the conversation leaves previously recorded answers
intact. Opening and closing the conversation contribute no calls to the count.

## Cutting outliers

Select **Outliers → Cut** to leave out a whole scenario if any of its answers was unusually
slow or used unusually many tokens. The resource tiles, charts and scenario table use the
remaining scenarios. The report names the excluded scenarios and preserves the run's pass rate.
**Keep** restores all scenarios. Links with `#cut=on` preserve the selection.

The report checks time and tokens separately. For each, it takes the logarithms of positive
measurements and finds the lower and upper quartiles (Q1 and Q3). It sets the cutoff at
`Q3 + 3 × (Q3 − Q1)` on that scale. For example, if the middle half of answer times lies
between 2 and 4 seconds, the cutoff is 32 seconds. The cutoff applies only when the metric has
at least four positive values and its quartiles differ. If cutting would remove every scenario,
the report keeps them all.

## Charts

**Tokens per answer by part** shows cache reads, other input, other output and thinking. Each bar
gives the share of reported tokens and the mean per answer reporting usage. Cache writes are part
of input. Unspecified cache reads and thinking tokens remain in the input and output totals.

**Time by call** groups calls by name. Each row gives the name's share of all recorded call time
and its seconds per answer, averaged over every answer kept. Two overlapping one-second calls
contribute two seconds of call time. The report keeps call timing separate from answer timing
because the agent and convy measure them on different clocks. It also keeps call tokens separate
from answer tokens, which may already include them. Open a row to see the slowest calls, five at
first. Select a call to open its answer.

## Percentiles

The median (P50) is the middle value after sorting. P90 is the 90th percentile, near the high
end. The report interpolates between neighboring values when needed. For answer times of 1, 1
and 10 seconds, the median is 1 second and the mean is 4 seconds.

## Scenarios

The table lists failing scenarios first. Filter by ID with a pattern such as `refund-*`.

| Status | Counted attempts |
|---|---|
| Failing | At least one counted, all failed |
| Flaky | Some passed and some failed |
| Passing | At least one counted, all passed |
| No verdict | None counted |

Open a row to see the simulated user's instructions, the required claims and how often each claim
held. Select an attempt square to inspect a particular dialogue. A judged attempt shows how many
claims held, whether a required claim failed and whether it met the run's threshold. Each claim
shows the judge's decision, reason and confidence when supplied. A positive decision below the
run's trust level fails the claim.

The dialogue shows the time and reported tokens for each answer. Choose **Show steps** to expand
thoughts and calls. Call bars overlap when the calls ran at the same time. Open a call to inspect
its model or tool kind, duration, reported tokens, request and response. The page address tracks
the open scenario and attempt so you can share a link.

## Runs workspace

Open `results/index.html` to compare readable runs. Run `convy report` to rebuild the index and
the individual reports from saved results.

- The **runs table** lists each agent, build, run status and progress. Select a run to open its report.
- **Quality and resource use** plots pass rate against time or tokens. Runs missing either value
  still appear in the table. The workspace includes outliers.
- **Scenarios by run** compares pass counts across runs. Revision numbers distinguish changes
  to a scenario with the same ID. The matrix distinguishes a missing scenario from one with no
  counted attempts. Select a cell to open the scenario in that run.

Search by agent, version or run ID, or select individual runs with **Choose runs**. All views use
the selection. Sorting the runs table also orders the columns in both comparison tables.
**Statistic** and **Time and tokens per** change the units in the runs table and scatter plot.

Choose a reference to see the difference in percentage points. For example, 75% is 15 points
above a reference of 60%. Differences appear only while the reference is visible. Both runs
must be finished and readable, with every planned attempt recorded and counted. They must also
have matching scenario definitions, user and judge names, `models.py` fingerprint, convy version,
trust, claim threshold, repetitions, turn timeout and initial participant limits. Different agent
builds can share the same evaluation settings.

### Run metrics

Each column links to a run. Choose a **Metric group** to see more detail.

- **Outcomes** shows planned, recorded, counted and passed attempts. Error counts use recorded
  attempts as their denominator. A stable scenario passed every planned attempt.
- **Scenario pass rates** groups scenarios by pass rate and gives each scenario one vote. If
  three of ten scenarios passed half their counted attempts, the 50% row shows 30% (3/10).
- **Resource distributions** shows minimum, median, mean, P90, maximum and measurement coverage
  for the selected resource and unit. See [what gets counted](#measured-population).
- **Token composition** compares token parts and shows how many answers reported usage, cache
  reads or thinking. The two cache ratios use different input totals. If two answers each report
  100 input tokens and only one reports cache reads (80 tokens), cache reads are 40% of all
  input and 80% of input on answers reporting cache reads.
- **Named calls** compares a selected model or tool call name across runs. Counts include
  calls visible in partial traces. Mean seconds and reported tokens per answer use all recorded
  answers. The timing distribution includes only answers containing that name and sums its calls
  within each answer. An absent name counts as zero when every answer has a complete trace.

## Compare two runs

For a terminal or CI check, give the baseline first and the candidate second. Use full run IDs
or unique suffixes.

```sh
uv run convy compare e46f 4693
uv run convy compare e46f 4693 --fail-on-regression
```

The command requires finished runs with the same trust and claim threshold. It prints the overall
pass rates and checks for evidence of a change on scenarios that were unchanged and counted
in both runs. A regression requires a lower overall pass rate and evidence of a decline in an
exact two-sided test at the 5% level. Small samples often give an inconclusive result.
`--fail-on-regression` also sets an [exit code for CI](runs.md#fail-ci-when-the-pass-rate-regresses).
