# The report

Every run has its own report: `results/<agent>/<run>/report.html`. It is a static page that works
offline, with system, light and dark themes.
[See a real one.](https://deyna256.github.io/convy/report.html)

## Tiles

The page reads from the top down: five tiles, the pass rate beside the other four, the tokens by
part and the time by call, then the **Scenarios**, the failing first.

Each tile has its label, its number and what the number counts. The run's page shows the run
alone; how it changed since another run is on a [comparison](#compare-two-runs), whose command is
at the foot of the page.

- **Pass rate**: the share of counted attempts that passed, and beside it how many of how many
  (`67% 8 / 12`). An attempt counts when the agent failed (it did not pass), or when
  the judge's verdict is decided at the run's trust: every decision is trusted, or a trusted
  decision failed. A decision without a confidence is trusted. Attempts with no verdict — convy's
  models failed, or the agent's service stayed busy — and verdicts not decided are left out; with
  `--trust`, the tile says how many were not trusted (`· 4 not trusted`). Under it, one line
  splits the scenarios by the share of their counted attempts that passed, from 0%, each part as
  long as how many scenarios have it, coloured by their status and with their count; those without
  a verdict last. Pointing at a part lights it up.
- **Flaky scenarios**: how many have passed and failed counted attempts.
- **Errors**: of the agent, of an agent's service that stayed busy, and of convy's models, with
  their kinds (`1 agent failure · 2 model failures`), or `none failed`.
- **Time per answer**: the mean over the answers kept, how many, and how many scenarios were cut.
  Only the agent's own time counts, not the simulated user's or the judge's.
- **Tokens per answer**: the same for an answer's input and output together, over the answers
  that report them (`mean of the 40 of 44 answers that report tokens`).

## Cutting outliers

One slow answer, a retry or a cold start, can move a mean a long way. **Outliers** in the page's
header, beside the theme, is **Keep**, the default, or **Cut**: Cut leaves out every scenario with
an answer far slower or far larger than the run's others. Every time and token number on the page
follows it: the tiles, the charts and the table, which leaves the cut scenarios out and names them
under it. The pass rate does not change.

- The unit is the scenario, not the answer. A slow or large answer mostly comes from what the
  scenario asks: more calls, a longer dialogue, an agent going round in circles. Cutting only that
  answer would keep the scenario's other answers and still mix it into the numbers.
- "Far" is Tukey's far-out fence on a log scale: the upper quartile of the logs of the run's
  answer times plus three interquartile ranges, and the same for tokens. If the middle half of
  the answers take 2 to 4 s, the fence is at 4 s · 2³ = 32 s. Time and tokens have a long right
  tail, which the log makes even, so ordinary slow answers stay in.
- When nothing is far out, Cut leaves out nothing. It also cuts nothing with fewer than four
  answers, when half the answers or more take the same time, or when it would leave no scenario.

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
answer can, and it matches the tiles. The shares are the same either way.

Open a call name to see its slowest calls, five at first, each with its scenario, attempt and turn;
click one to open that answer with the call unfolded.

## Percentiles and the switch

Every time and token number is a spread: how many values, the least, the 50th and 90th
percentiles, the most and the mean. **P50**, the median, is the value half the values are at or
under; **P90** the value 9 in 10 are at or under; **Max** the largest; **Mean** the sum over the
count. Percentiles are linear between the sorted values, as numpy's default.

The run's page shows means. The comparison has a switch in its header, **Show P50 · P90 · Max ·
Mean**, P50 by default, that sets the one number per scenario or turn its charts and tables show;
the address keeps it (`#stat=p90`).

## Scenarios

Each scenario gets a row and a status:

- **Failing**: no counted attempt passed.
- **Flaky**: some counted attempts passed.
- **Passing**: every counted attempt passed.
- **No verdict**: no attempt was counted: none was played yet, or each had no verdict or a verdict
  not decided at the run's trust.

The row also shows the mean of its time and of its tokens per answer, over the answers the cut
keeps, each with its Max under it.
**Attempts** has a square per attempt: ✓ passed, ✕ failed, – no verdict or not trusted. Click one
to open that attempt. A filter such as `refund-*` narrows the list.

Click a row to open the scenario. You see what the simulated user was told, and each claim with how
many attempts it held in, a square per attempt with the judge's decision on it, and how many of its
decisions were not trusted. A claim's count is over its trusted decisions. Its typical grade is the
middle one of its trusted grades; with two in the middle, the worse. A graded claim also says how
often it got each grade (`held in 3 of 4 · full 2 · partial 1 · none 1`). For each attempt you see
the judge's decision on every claim with its grade, if it has one, and its reason, and the dialogue
with the time and tokens of each answer; **Total answer time** adds them up for the attempt. An
answer's tokens show their parts, such as `1.2k in, 1.0k from cache · 300 out, 200 thinking`: cached
tokens are part of the input, and thinking part of the output, not added to them. A part the agent
does not report is left out; a 0 it reports is shown.

An answer that gives its [steps](agents.md#steps) shows them as a line that ends in the answer.
By default the steps are folded into one node, such as `2 thoughts · 4 calls · calls ran 2.1 s`;
**Show steps** at the end of the answer's head, or a click on the node, unfolds them, and **Hide
steps** in the same place folds them. A thought shows its text. A call shows its bar on the line of the answer's calls,
from the first call's start to the last call's end: bars that overlap ran at the same time. It
shows when it started (`from +0.6 s`), how long it took and its tokens; open it to see what it
sent and received, JSON indented, or "not reported" and "empty".

If the judge says how sure it is, each decision shows that too, or "sure: not given" where it
did not say. The address keeps the open scenario, so you can send a link to it.

## The index

`results/index.html` lists the runs by agent, newest first, the newest five (**Show N older runs**
shows the rest). Each agent's header names its newest run's **setup**, what a run is measured
with: the user's model, the judge, the scenarios and attempts, and the trust when there is one.
Beside it a strip shows the agent's newest 40 runs, newest left: a bar per run as high as its pass
rate and coloured by its result, and a line where the setup changed. The agent's version and the
number of attempts are not part of the setup.

A run's row gives its pass rate with how many attempts passed, its version and when it started,
and how many errors it had if any. Under the run where the setup changed, a line says what changed
(`Changed: judge: a → b`, `scenarios: +1 −2`). Tick two runs to get the `convy compare` command for
them. Time and tokens are on each run's page.

## Compare two runs

Name two runs, by id or by their random part:

```sh
uv run convy compare e46f 4693       # before, then after
```

The page `results/compare/e46f-vs-4693.html` shows the same tiles with the old value and the change.
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
part** two thin bars per compared scenario, before and after, with the mean tokens per attempt
(`1,018 → 1,522`) and, under it, the share read from the cache (`78% → 21%`).

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

A graded claim whose typical grade moved says so in the window, such as `full → partial`: red when
it fell, green when it rose, whatever the pass rate did. The typical grade is as in
[the scenario's window](#scenarios).

Each run is read with its own `trust`, shown next to it in the page's head.

The runs may be of different agents. The page warns when the user's or the judge's model, or the
convy version, differs.
