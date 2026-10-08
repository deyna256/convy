# The report

Every run has its own report: `results/<agent>/<run>/report.html`. It is a static page that works
offline, with system, light and dark themes. [See a real one.](https://deyna256.github.io/convy/shop_bot/2026-10-08T14-38-03_5e85/report.html)

## Tiles

Five tiles sum up the run:

- **Pass rate**: the share of attempts the judge passed, with the count (`67% · 8 of 12 attempts`).
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
- **No verdict**: one of convy's models failed, so no attempt was decided.

The row also shows answer time and tokens. A filter such as `refund-*` narrows the list.

Click a row to open the scenario. You see what the simulated user was told, and each claim with how
many attempts it held in. For each attempt you see the judge's decision on every claim with its
reason, and the dialogue with the time and tokens of each answer. The address keeps the open
scenario, so you can send a link to it.

`results/index.html` lists every run, newest first, with a link to its report.

## Compare two runs

Name two runs, by id or by their random part:

```sh
uv run convy compare e46f 4693       # before, then after
```

The page `results/compare/e46f-vs-4693.html` shows the same tiles with the old value and the change.
[See a real one.](https://deyna256.github.io/convy/compare/7ad8-vs-5e85.html)

- Green means better, red means worse.
- Grey with `~` means the pass rate moved within noise. With few scenarios and attempts, a change that
  size can happen by chance.

Scenarios are grouped as **Worse**, **Better**, **Same** and **Not compared**. A scenario is not
compared if only one run played it, it was edited between the runs, or one run has no verdict for it.
A scenario's window shows both dialogues side by side.

The runs may be of different agents. The page warns when the user's or the judge's model differs.
