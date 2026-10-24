# The report

Every run has its own report: `results/<agent>/<run>/report.html`. It is a static page that works
offline, with system, light and dark themes.
[See a real one.](https://deyna256.github.io/convy/report.html)

## Tiles

Five tiles sum up the run:

- **Pass rate**: the share of counted attempts that passed, with the count
  (`67% · 8 of 12 attempts`). An attempt counts when the agent failed (it did not pass), or when
  the judge's verdict is decided at the run's trust: every decision is trusted, or a trusted
  decision failed. A decision without a confidence is trusted. Attempts with no verdict — convy's
  models failed, or the agent's service stayed busy — and verdicts not decided are left out; with
  `--trust`, the tile says how many were not trusted (`· 4 not trusted`).
- **Stable scenarios**: those whose `k` attempts were all played, counted and passed.
- **Time per answer**: the mean of the answers' seconds, and the slowest. Only the agent's own
  time counts, not the simulated user's or the judge's.
- **Tokens per attempt**: in and out, as the agent reports them, with the parts it reports: how
  many of the input it read from or wrote to the model's cache, and how many of the output went to
  thinking. A part the agent does not report is left out; a 0 it reports is shown. Each is the mean,
  over the attempts that report it, of the sum of their answers'. The share of input read from the
  cache is the sum of `cache_read` over the sum of input, both over the answers that report
  `cache_read`.
- **Errors**: of the agent, of an agent's service that stayed busy, and of convy's models.

Under the tiles, two panels show how each scenario spreads. **Time per answer** has a bar per
scenario from its fastest answer to its slowest, a tick at the mean and the slowest as text;
**Tokens per attempt** the same from its cheapest attempt to its costliest. The slowest and the
costliest come first, the first ten (**Show all N** shows the rest). Each panel's scale runs from 0
to its largest value, written at its right end, so one very slow answer squashes the other bars;
the numbers stay in the text.

## Scenarios

Each scenario gets a row and a status:

- **Failing**: no counted attempt passed.
- **Flaky**: some counted attempts passed.
- **Passing**: every counted attempt passed.
- **No verdict**: no attempt was counted: none was played yet, or each had no verdict or a verdict
  not decided at the run's trust.

The row also shows time per answer and tokens.
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
By default the steps are folded into one node, such as `2 thoughts · 4 calls · calls ran 2.1 s`; **Show steps**
unfolds them. A thought shows its text. A call shows its bar on the line of the answer's calls,
from the first call's start to the last call's end: bars that overlap ran at the same time. It
shows when it started (`from +0.6 s`), how long it took and its tokens; open it to see what it
sent and received, JSON indented, or "not reported" and "empty".

If the judge says how sure it is, each decision shows that too, or "sure: not given" where it
did not say. The address keeps the open scenario, so you can send a link to it.

`results/index.html` lists the runs by agent, newest first, the newest five (**Show N older runs**
shows the rest). A strip shows each agent's newest 40 runs, newest left: a bar per run as high as
its pass rate and coloured by its result, and a line where the **setup** changed. The setup is what
a run is measured with: the user's model, the judge, convy's version, the trust and the set of
scenarios. The agent's version and the number of attempts are not part of it. In the table, a setup
cell that changed since the agent's previous run is marked; point at it to see the old value. Tick
two runs to get the `convy compare` command for them.

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

Under the tiles, two panels show how each compared scenario changed: a bar from 0, its length the
change of the scenario's mean time per answer or tokens per attempt as a percent of the old one,
on a scale from −100% to +100% (a larger change is cut at the edge, its text keeps the number, such
as `+59% · 1.9 s → 3.0 s`). Right and red is worse, left and green is better. A change under 5%, as
the page rounds it, is grey, on these panels and on the Time per answer and Tokens per attempt
tiles. A scenario that had 0 before has no percent. Each panel shows ten rows, then **Show all N**.

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
