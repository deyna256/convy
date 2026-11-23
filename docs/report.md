# The report

Every run has its own report: `results/<agent>/<run>/report.html`. It is a static page that works
offline, with system, light and dark themes.
[See a real one.](https://deyna256.github.io/convy/report.html)

## Tiles

The page reads from the top down: quality and resource tiles, the tokens by part and the time
by call, then the **Scenarios**, the failing first.

Each tile gives a value and what it counts. Open the [runs workspace](#runs-workspace) to see
those measurements across runs.

- **Pass rate**: the share of counted attempts that passed, and beside it how many of how many
  (`67% 8 / 12`). An attempt counts when the agent failed (it did not pass), or when it has a
  valid judge verdict. The [scoring rule](scenarios.md#passing-an-attempt) determines whether a
  judged attempt passed; low-confidence decisions count as failed claims. Attempts with no verdict
  — convy's models failed, or the agent's service stayed busy — are left out and counted separately.
  Under the tile, one line splits the scenarios by the share of their counted attempts that passed,
  from 0%, each part as long as how many scenarios have it, coloured by their status and with their
  count; those without a verdict last. Pointing at a part lights it up.
- **Flaky scenarios**: how many have passed and failed counted attempts.
- **Errors**: of the agent, of an agent's service that stayed busy, and of convy's models, with
  their kinds (`1 agent failure · 2 model failures`), or `none failed`.
- **Time**: mean and median, both per answer and per task attempt, with the number measured out of
  the number kept. Only recorded answer time counts, not the simulated user's or the judge's.
- **Tokens**: the same for input and output tokens together. Each unit has its own coverage:
  an answer can report tokens even when another answer of its task does not.
- **Tool calls**: mean and median per task attempt, with the number of tasks whose counts
  are known out of the recorded tasks kept; see [the counting rule](#tool-invocations).

## Measured population

A task attempt is one recorded play of a scenario, which can contain several answers. For task
metrics, convy first adds the answers within each attempt, then calculates the mean and median
of those totals. It does not add answer medians or average scenario medians. At run level every
measured answer or attempt counts once, so longer dialogues contribute more answers but still
one task each.

The mean is the sum divided by the number measured. The median describes the middle of the sample:
for answer times of 1, 1 and 10 seconds, the mean is 4 seconds and the median is 1 second. With an
even number of measurements, the median is the mean of the two middle values; with one, both
statistics equal that value.

Resource statistics include recorded attempts regardless of whether they passed, failed or have
no judge verdict. Attempts still running or never recorded contribute nothing. A failed attempt's
time describes only the answer durations recorded before it ended. Task time is their sum, not
elapsed wall time: it excludes the simulated user, judge, waits between answers, and opening or
closing the conversation.

An attempt's token total is measured only when it has at least one answer and every recorded
answer reports its input and output tokens. A partial total is unavailable, rather than a smaller
complete total. Reported zero tokens count as a measurement. An attempt with no recorded answers
has no measured task time or token use. Coverage counts include such attempts in the denominator,
and unavailable statistics display as a dash. The attempt detail and the runs workspace use the same
token rule. Individual answers keep their available measurements.

Within a run's report all resource metrics use the same [outlier selection](#cutting-outliers). The run tiles and
scenario rows show measured counts against the answers or attempts kept; excluded scenarios are
identified separately. The population for resource metrics is independent of the pass-rate population.

### Tool invocations

Each `Call(kind="tool")` in an answer's [steps](agents.md#steps) counts once, including repeated
calls to the same tool, retries and failed invocations. Search is a tool invocation. Model calls
and thoughts do not count. The count is known only when `steps_complete=True` asserts that every
call for the answer is recorded. Empty steps with that flag mean zero; empty or partial steps
without it mean unknown, even when some tool calls are visible.

An attempt's count is the sum over its recorded answers, known only when there is at least one
answer and all those answers have complete traces. Run and scenario means and medians use these
known task counts, including zero. Coverage is known tasks out of all recorded tasks kept; an
attempt with no answers or an incomplete trace stays in the denominator but supplies no value.

The population includes passed, failed and unjudged attempts. An answer failure adds a synthetic
answer without a complete trace, leaving the task's count unknown. A failure while closing the
conversation can leave complete answers and a known count. These are counts of observed answer
calls, not a promise that the whole task finished; opening and closing work is excluded. An
attempt still running or never recorded is absent.

## Cutting outliers

One slow answer, a retry or a cold start, can move a mean a long way. **Outliers** in the page's
header, beside the theme, is **Keep**, the default, or **Cut**: Cut leaves out every scenario with
an answer far slower or far larger than the run's others. Every time, token and tool-invocation
metric on the page follows it: the tiles, the charts and the table, which leaves the cut scenarios
out and names them under it. The pass rate does not change. Tool counts use this same selection;
they do not define another outlier fence.

- The unit is the scenario, not the answer. A slow or large answer mostly comes from what the
  scenario asks: more calls, a longer dialogue, an agent going round in circles. Cutting only that
  answer would keep the scenario's other answers and still mix it into the numbers.
- "Far" is Tukey's far-out fence on a log scale: the upper quartile of the logs of the run's
  answer times plus three interquartile ranges, and the same for tokens. If the middle half of
  the answers take 2 to 4 s, the fence is at 4 s · 2³ = 32 s. Time and tokens have a long right
  tail, which the log makes even, so ordinary slow answers stay in.
- When nothing is far out, Cut leaves out nothing. It also cuts nothing with fewer than four
  answers, when the middle half of the answers take the same time (the quartiles are equal), or
  when it would leave no scenario.

convy does not cut by percentile: a percentile always takes its share, a tenth of the answers at
P90, even when none of them is an outlier.

The address keeps the cut (`#cut=on`), so a link opens on it.

## Charts

**Tokens per answer by part** splits the tokens the agent reported for an answer: what was read
from the cache, the new input (cache writes included), the output and the thinking. Each part shows
its share of the tokens, large and as its bar, and under it its mean per answer over the answers
kept that report tokens. The parts add up to the answer's tokens;
a part the agent does not report stays in the whole: without cache reads, the new input is all the
input.

**Time by call** shows where the answers' calls spent their time, a row per call name. Each shows
its share of the calls' time together, large and as its bar, and under it what it adds to an
answer on average: its total over every answer kept. Under each name: how many calls, and in how
many answers; point at a row for its spread over the answers it is in. Calls that ran together
each count their own time. For example, two calls lasting one second each contribute two call
seconds even if they start together.

- A call name whose calls report tokens shows them under its time, per answer on average. They
  are apart from the answer's tokens: convy does not know whether the answer's usage holds its
  calls' tokens, so it never adds the two.
- The answer's time outside its calls is not shown. The calls are timed by the agent's clock and
  the answer by convy's, which also counts the network; setting one against the other would mix
  the two ([decision 10](decisions/0010-answer-steps.md)). Without [steps](agents.md#steps) the
  chart is empty.

Both charts give a mean per answer, not the run's total: a total grows with the scenarios, the
attempts and the turns, so two runs of different size could not be set side by side; a mean per
answer can, and it matches the tiles' per-answer means. The shares are the same either way.

Open a call name to see its slowest calls, five at first, each with its scenario, attempt and turn;
click one to open that answer with the call unfolded.

## Percentiles

Every time and token number is a spread: how many values, the least, the 50th and 90th
percentiles, the most and the mean. **P50**, the median, is the value half the values are at or
under; **P90** the value 9 in 10 are at or under; **Max** the largest; **Mean** the sum over the
count. Percentiles are linear between the sorted values, as numpy's default.

The run's tiles and scenario rows show mean and median together for answers and task attempts.

## Scenarios

Each scenario gets a row and a status:

- **Failing**: no counted attempt passed.
- **Flaky**: some counted attempts passed.
- **Passing**: every counted attempt passed.
- **No verdict**: no attempt was counted: none was played yet, or each had no verdict.

The row's Time and Tokens columns each show mean and median per answer and per task attempt;
Tool calls shows both per task. Each has coverage counts over the
[measured population](#measured-population) the cut keeps.
**Attempts** has a square per attempt: ✓ passed, ✕ failed, – no verdict. Click one
to open that attempt. A filter such as `refund-*` narrows the list.

Click a row to open the scenario. You see what the simulated user was told, required claims marked,
and how many attempts each claim held in. A claim's count includes all its decisions; insufficient
confidence is a failed claim. Each judged attempt shows its completion count and percentage next to
its final result. A failed attempt identifies the required claims that failed, an unmet percentage
threshold, or both. Agent failures and attempts without a verdict have no measured completion.

For each claim you can see its effective result, the original yes/no decision, reason and
confidence. A confidence failure is explained separately from the judge's reason. The dialogue comes
with the time and tokens of each answer; **Total answer time** adds them up for the attempt. An
answer's tokens show their parts, such as `1.2k in, 1.0k from cache · 300 out, 200 thinking`: cached
tokens are part of the input, and thinking part of the output, not added to them. A part the agent
does not report is left out; a 0 it reports is shown.

An answer that gives its [steps](agents.md#steps) shows them as a line that ends in the answer.
By default the steps are folded into one node, such as `2 thoughts · 4 calls · calls ran 2.1 s`;
**Show steps** at the end of the answer's head, or a click on the node, unfolds them, and **Hide
steps** in the same place folds them. A thought shows its text. A call shows its bar on the line of the answer's calls,
from the first call's start to the last call's end: bars that overlap ran at the same time. It
shows its model or tool kind, when it started (`from +0.6 s`), how long it took and its tokens;
open it to see what it sent and received, JSON indented, or "not reported" and "empty". Partial steps remain visible
when the [tool count](#tool-invocations) is unknown.

If the judge says how sure it is, each decision shows that too, or "sure: not given" where it
did not say. The address keeps the open scenario, so you can send a link to it.

## Runs workspace

Open `results/index.html` to compare all readable runs in one offline page. Run `convy report`
to rebuild it and the individual reports from the saved results.

- **Runs table.** Each row identifies the agent, version and run, shows its status, and links to
  its report. Recorded attempts out of planned attempts show progress. Passing attempts out of
  counted attempts give the run's original pass rate. For example, a run with 8 passes, 2 agent
  failures and 2 attempts without a verdict has 12 recorded attempts and a pass rate of 8/10.
- **Resources.** Compare mean and median time or tokens per task or per answer, and tool calls per
  task. Coverage gives the number measured out of the recorded answers or tasks. A reported zero
  contributes to the statistic. Missing measurements leave a gap. The workspace includes outliers
  and uses the same [measurement rules](#measured-population) as the run report.
- **Quality versus resources.** The scatter plot puts pass rate and a resource measurement on
  common axes. Choose time or tokens for the resource axis. A point needs both coordinates.
  The table also shows runs with only one measurement.
- **Scenario matrix.** Read across a scenario to see how often it passed in each run. Follow a
  cell to its scenario in the run report for the attempts, claim decisions and dialogues.
  Revision numbers identify different snapshots under the same scenario ID. An absent scenario
  and one with no counted attempts have separate labels.

Search by agent, version or run ID, or use **Choose runs** to include individual runs. All
views use that selection. Sorting the runs table also orders the columns of the scenario matrix
and the **Run metrics** table. **Statistic** and **Time and tokens per** select the statistic
and unit for the runs table and scatter plot. Tool calls always use the task as their unit.

Choose an optional reference to see how many percentage points a run's pass rate differs from the
reference. A change from 60% to 75% is +15 points. Filtering out the reference hides differences
until it is in scope again.

A whole-run difference needs matching scenario snapshots and recorded evaluation settings. These
include the simulated user and judge, convy version, trust, claim threshold, attempts per
scenario, turn timeout and initial participant limits. Both runs must record the same nonempty
fingerprint of `models.py`. A Python run that omits this fingerprint still shows its own pass
rate. Both runs must be finished and readable with every planned attempt recorded and counted.
Where those conditions differ, use each run's original rate, counts and linked report to inspect
the results. Different agent builds can be compared with the same evaluation setup.

### Run metrics

Choose a **Metric group** to compare one quantity across the visible runs. Each column links to
its individual report.

- **Outcomes.** Read from planned to recorded to counted attempts, then see how many passed.
  Error counts use recorded attempts as their denominator. Agent failures also count as failed
  attempts. Busy-agent and model failures also count as attempts without a verdict. A stable
  scenario passed every planned attempt. A flaky scenario had both a pass and a failure among
  its counted attempts. With one repetition, there is no opportunity to observe flakiness.
- **Scenario pass rates.** Each row groups scenarios by their observed pass rate. For example,
  if 3 of 10 scenarios passed half their counted attempts, the 50% row shows 30% (3/10).
  Each scenario contributes once, including unplayed scenarios in the no-verdict group.
- **Resource distributions.** Choose time or tokens per answer or per task, or tool calls per
  task. Read the median alongside P90 to see how much larger the upper end of the sample is.
  Minimum, mean, maximum and measured/recorded counts are available for the same sample.
  Task time sums the recorded answer durations. Token and tool totals require measurements
  for every recorded answer in the task.
- **Token composition.** Compare cache reads, other input, other output and thinking as both a
  share of reported tokens and a mean per answer reporting usage. Unitemized cache reads stay
  in other input and unitemized thinking stays in other output. Use the reporting counts to
  interpret the two cache ratios. For example, if two answers each report 100 input tokens and
  only one itemizes cache reads (80), cache reads are 40% of all input and 80% of input on
  answers reporting cache reads.
- **Named calls.** Choose a model or tool call name. The call count and timing describe the
  occurrences visible in the traces, including partial traces. Check how many answers have
  complete traces and how many of the selected calls reported tokens. The share uses total
  recorded call seconds across all names. Seconds and reported tokens per answer use all
  recorded answers. The distribution sums the selected calls' seconds within each answer
  containing that name. Open the individual report to locate the slowest calls.

## Compare two runs

To check two runs from the terminal, name the baseline first, then the candidate. A full run ID or
its unique random suffix identifies each run.

```sh
uv run convy compare e46f 4693
uv run convy compare e46f 4693 --fail-on-regression
```

Both forms print the pass-rate verdict and any scenarios with lower observed rates, or the reason
a verdict is unavailable. `--fail-on-regression` also signals the outcome through the exit code.

The CLI uses an exact two-sided test on the scenarios that both runs played unchanged and
counted. A scenario with more attempts carries more evidence. A regression requires a lower
overall pass rate and evidence of a decline at the 5% significance level. With few attempts,
even a large difference can be inconclusive. See
[exit codes and CI usage](runs.md#fail-ci-when-the-pass-rate-regresses).
