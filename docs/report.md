# The report

Every run has its own report: `results/<agent>/<run>/report.html`. It is a static page that works
offline, with system, light and dark themes.
[See a real one.](https://deyna256.github.io/convy/report.html)

## Tiles

The page reads from the top down: quality and resource tiles, the tokens by part and the time
by call, then the **Scenarios**, the failing first.

Each tile has its label, its number and what the number counts. The run's page shows the run
alone; how it changed since another run is on a [comparison](#compare-two-runs), whose command is
at the foot of the page.

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
and unavailable statistics display as a dash. The same token rule applies to the attempt detail
and comparison pages; the individual answers keep their available measurements.

All resource metrics use the same [outlier selection](#cutting-outliers). The run tiles and
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
each count their own time, so their shares are of more than the answers' time.

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

## Percentiles and the switch

Every time and token number is a spread: how many values, the least, the 50th and 90th
percentiles, the most and the mean. **P50**, the median, is the value half the values are at or
under; **P90** the value 9 in 10 are at or under; **Max** the largest; **Mean** the sum over the
count. Percentiles are linear between the sorted values, as numpy's default.

The run's tiles and scenario rows show mean and median together for answers and task attempts.
The comparison has a switch in its header, **Show P50 · P90 · Max ·
Mean**, P50 by default, that sets the one number per scenario or turn its charts and tables show;
the address keeps it (`#stat=p90`).

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

## The index

`results/index.html` lists the runs by agent, newest first, the newest five (**Show N older runs**
shows the rest). The **setup** is what a run is measured with: the user's model, the judge,
convy's version, the trust, the claim threshold and the set of scenarios; not the agent's version
or the number of attempts. Each agent's header names its newest run's user and judge, its scenarios × attempts, and
its trust when there is one. Beside it a strip shows the agent's newest 40 runs, newest left: a bar
per run as high as its pass rate and coloured by its result, and a line where the setup changed.

A run's row gives its pass rate with how many attempts passed, its version and when it started,
and how many errors it had if any. Under the run where the setup changed, a line says what changed
(`Changed: judge: a → b`, `scenarios: +1 −2`). Tick two runs to get the `convy compare` command for
them. Time and tokens are on each run's page.

## Compare two runs

Name two runs, by id or by their random part:

```sh
uv run convy compare e46f 4693       # before, then after
```

The page `results/compare/e46f-vs-4693.html` shows quality and resource tiles with the old value and
the change. Its resource units are time per answer and tokens per attempt.
Pass-rate changes are in **percentage points**, not relative percent.
[See a real one.](https://deyna256.github.io/convy/compare.html)

Under Tokens per attempt, the share of input read from the cache shows how it changed, such as
`from cache 83% → 20%`: red when it fell, green when it rose, the change in percentage points when
you point at it. It says `not reported` when only one of the runs reports it, and is not there
when neither does.

The Time per answer and Tokens per attempt tiles show the after run's P50, P90, Max and Mean, each
with its change in seconds or tokens, and the before run's four on one line. A change under 5% of
the old value, as the page rounds it, is grey. A change of Max is grey with `~`: one answer
moves it. An unchanged Max shows `=`.

Under the tiles, two panels show how each compared scenario changed: a bar from 0, its length the
change of the chosen statistic of the scenario's time per answer or tokens per attempt as a
percent of the old one, on a scale from −100% to +100% (a larger change is cut at the edge, its
text keeps the number, such as `+59% · 1.9 s → 3.0 s`). Right and red is worse, left and green is
better; grey under 5%, as on the tiles. A scenario whose statistic was 0 before has no percent for
it. Each panel shows ten rows, then **Show all N**.

**Tokens by turn** shows both runs side by side on one scale, the turns lined up, and **Tokens by
part** two thin bars per compared scenario, before and after, as long as the chosen statistic of
its tokens per attempt (`1,018 → 1,522`), the parts keeping their shares of the mean; under it,
the share of the input read from the cache (`78% → 21%`).

- Green means better, red means worse.
- Grey with `~` means the pass rate's change may be chance. convy looks at the scenarios both
  runs played unchanged and asks how often the same agent would give a result this unlikely by
  chance alone. At 5% or more, the change is grey. Each scenario counts by its attempts: a fall
  from 20 of 20 to 10 of 20 weighs more than a fall from 1 of 1 to 0 of 1. With few scenarios
  or attempts, even a large change can be grey. Scenarios that got better and scenarios that got
  worse weigh against each other. The tile is also grey when these scenarios and the whole pass
  rate point different ways.

Scenarios are grouped as **Worse**, **Better**, **Same** and **Not compared**; each row shows the
squares of its attempts before and after and how many more or fewer passed. A scenario is not
compared if only one run played it, it was edited between the runs, or one run has no verdict for
it. A scenario's window shows both dialogues side by side.

Each run is read with its own `trust` and `claim_threshold`, shown in its setup. Changing a claim's
required flag changes the scenario, so that scenario is not compared. If either scoring setting
differs, the page cannot establish a quality improvement or regression, and
[`--fail-on-regression`](runs.md#fail-ci-when-the-pass-rate-regresses) exits with 3. Time and token
measurements remain available.

The runs may be of different agents. The page warns when the user's or the judge's model, or the
convy version, differs.
