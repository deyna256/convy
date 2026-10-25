# The report

Every run has its own report: `results/<agent>/<run>/report.html`. It is a static page that works
offline, with system, light and dark themes.
[See a real one.](https://deyna256.github.io/convy/report.html)

## Tiles

The page reads from the top down: five tiles, the **Precision** panel, three charts, then the
**Scenarios**, the failing first.

From the agent's second run on, each tile also says how it changed since the agent's run just
before, such as `▼ 44 pts vs 5e85`, coloured and greyed under noise as on a
[comparison](#compare-two-runs); `same as 5e85` when nothing changed. When the models or convy
changed since then, the header says so. The command at the foot of the page compares the two runs
in full.

- **Pass rate**: the share of counted attempts that passed, with the count
  (`67% · 8 of 12 attempts`). An attempt counts when the agent failed (it did not pass), or when
  the judge's verdict is decided at the run's trust: every decision is trusted, or a trusted
  decision failed. A decision without a confidence is trusted. Attempts with no verdict — convy's
  models failed, or the agent's service stayed busy — and verdicts not decided are left out; with
  `--trust`, the tile says how many were not trusted (`· 4 not trusted`). A bar splits the
  attempts into passed, failed and without a verdict.
- **Flaky scenarios**: those with passed and failed counted attempts, with a square per scenario,
  the flaky ones coloured.
- **Errors**: of the agent, of an agent's service that stayed busy, and of convy's models; only
  the kinds that happened are named.
- **Time per answer**: the statistic the precision panel sets, over the answers it keeps. Only
  the agent's own time counts, not the simulated user's or the judge's.
- **Tokens per answer**: the same for an answer's input and output together, over the answers
  that report them (`40 of 44 answers report tokens`).

## Precision

Every time and token number is a spread: how many values, the least, the 10th, 50th and 90th
percentiles, the most and the mean. **P50**, the median, is the value half the values are at or
under; **P90** the value 9 in 10 are at or under; **Max** the largest; **Mean** the sum over the
count. Percentiles are linear between the sorted values, as numpy's default.

The **Precision** panel sets two things that every time and token number on the page follows: the
tiles, the charts by category and the table.

- **Statistic**: **P50 · P90 · Max · Mean**, P50 by default: the one number per answer, scenario
  or category shown.
- **Outliers**: **Keep all**, the default, or **Leave out**: an answer whose time is more than 1.5
  times the interquartile range past the quartiles, Tukey's fences, is left out of every time
  number; one whose tokens are, of every token number. An answer left out of the time still
  counts in the tokens, and back. With fewer than four answers nothing is left out.

Beside them, a chart per number shows how the answers spread: a column per 1/24 of the range from
0 to the largest value, as high as how many answers fall in it. Answers left out are hatched, past
a dashed fence; a line marks where the chosen statistic falls. Point at a column for its range and
count.

The address keeps both (`#stat=p90&trim=out`), so a link opens on them. Other pages have the
statistic switch alone, in their header.

## Charts

**Scenarios by pass rate** has a column per pass rate of a scenario's counted attempts, from 0%,
as high as how many scenarios have it, coloured by their status; those without a verdict last.
Point at a column for its scenarios.

**Tokens by category** and **Time by category** show where the answers' tokens and time went, a
bar per category as long as the chosen statistic per answer it has a number in, the most in total
first. Under each name: in how many answers, how many calls, and its share of the whole.

- For tokens, **The answer itself** is the answer's own usage, split into what was read from the
  cache, the new input (cache writes included), the output and the thinking by their shares of the
  mean. Each call name that reports tokens is its own category. convy does not know whether an
  answer's usage holds its calls' tokens, so the shares may count them twice.
- For time, each call name is a category; calls that ran together each count their own seconds.
  **Outside calls** is the rest of the answer: its time past the span from its first call's start
  to its last call's end, or all of it when it gives no [steps](agents.md#steps).

Open a call to see its largest calls, five at first, each with its scenario, attempt and turn;
click one to open that answer with the call unfolded.

## Scenarios

Each scenario gets a row and a status:

- **Failing**: no counted attempt passed.
- **Flaky**: some counted attempts passed.
- **Passing**: every counted attempt passed.
- **No verdict**: no attempt was counted: none was played yet, or each had no verdict or a verdict
  not decided at the run's trust.

The row also shows the chosen statistic of its time and of its tokens per answer, over the answers
the precision panel keeps, each with its Max under it (its P50 when Max is chosen).
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
shows the rest). A strip shows each agent's newest 40 runs, newest left: a bar per run as high as
its pass rate and coloured by its result, and a line where the **setup** changed. The setup is what
a run is measured with: the user's model, the judge, convy's version, the trust and the set of
scenarios. The agent's version and the number of attempts are not part of it. In the table, a setup
cell that changed since the agent's previous run is marked; point at it to see the old value. Tick
two runs to get the `convy compare` command for them.

Under the strip, three more strips cover the same runs: the chosen statistic of the time per
answer and of the tokens per attempt, and the share of input read from the cache. Each has its own
scale from 0, and the newest run's number is written beside it; a run without the number has a
stub. The table's Time / answer and Tokens / attempt follow the switch.

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
