# The report

Every run has its own report: `results/<agent>/<run>/report.html`. It is a static page that works
offline, with system, light and dark themes.
[See a real one.](https://deyna256.github.io/convy/report.html)

## Tiles

Five tiles sum up the run:

- **Pass rate**: the share of attempts the judge passed, with the count (`67% · 8 of 12 attempts`).
  With `--trust`, it also says how many attempts were left out (`· 4 not trusted`).
- **Stable scenarios**: those that passed every attempt.
- **Answer time**: the mean per answer, and the slowest. Only the agent's own time counts, not the
  simulated user's or the judge's.
- **Tokens per attempt**: in and out, as the agent reports them.
- **Errors**: of the agent and of convy's models.

## Scenarios

Each scenario gets a row and a status:

- **Failing**: no attempt passed.
- **Flaky**: some attempts passed.
- **Passing**: all attempts passed.
- **No verdict**: no attempt was decided, because one of convy's models failed or the judge was not
  sure enough.

The row also shows answer time and tokens. A filter such as `refund-*` narrows the list.

Click a row to open the scenario. You see what the simulated user was told, and each claim with how
many attempts it held in and how many of its decisions were not trusted. A graded claim also says
how often it got each grade (`held in 3 of 4 · full 2 · partial 1 · none 1`). For each attempt you see
the judge's decision on every claim with its grade, if it has one, and its reason, and the dialogue with the time and tokens of
each answer. If the judge says how sure it is, each decision shows that too, or "sure: not given"
where it did not say. The address keeps the open scenario, so you can send a link to it.

`results/index.html` lists every run, newest first, with a link to its report.

## Compare two runs

Name two runs, by id or by their random part:

```sh
uv run convy compare e46f 4693       # before, then after
```

The page `results/compare/e46f-vs-4693.html` shows the same tiles with the old value and the change.
[See a real one.](https://deyna256.github.io/convy/compare.html)

- Green means better, red means worse.
- Grey with `~` means the pass rate moved within noise. With few scenarios and attempts, a change
  that size can happen by chance.

Scenarios are grouped as **Worse**, **Better**, **Same** and **Not compared**. Inside a scenario,
a graded claim whose typical grade moved says so, such as `full → partial`: red when it fell, green
when it rose, whatever the pass rate did. The typical grade is the middle one of its attempts, the worse of the two
in the middle. A scenario is not
compared if only one run played it, it was edited between the runs, or one run has no verdict for
it. A scenario's window shows both dialogues side by side.

Each run is read with its own `trust`, shown next to it in the page's head.

The runs may be of different agents. The page warns when the user's or the judge's model differs.
