# Scenarios

A scenario says who the simulated user is, what they want, and what must be true of the dialogue.
It is a YAML file in `scenarios/` or any folder under it, such as `scenarios/bank/cards/`.

```yaml
id: clarify-backup
max_turns: 6
user: |
  You need a backup script. Start short: "Make me a backup script".
  Give details only when the assistant asks for them:
  back up ~/photos to /mnt/backup, once a day.
judge:
  - claim: Before giving a finished script, the agent asked what to back up and where to
    required: true
  - The final script copies ~/photos to /mnt/backup and runs once a day
```

- `user` tells the simulated user who to be and what to want.
- `judge` lists claims as text or mappings with `claim` and an optional boolean `required`.
  A string is shorthand for `required: false`; at least one claim is needed.
- `max_turns` is how many messages the user may send.
- `id` must be unique across all folders.

Write scenarios in any language. The simulated user speaks the language of its instructions.

Each claim needs a yes/no answer. State the condition the dialogue must meet, and split independent
requirements into separate claims so a failure has a clear reason.

Ordered claim scales have been removed. Replace a mapping with `claim`, `grades` and `pass` with a
plain statement of the condition that counts as passing. Such mappings are rejected; convy does not
convert a scale into a yes/no condition for you.

## Passing an attempt

The judge decides every claim independently and gives a reason. It receives the claim texts, not
which ones are required or the passing threshold. convy then scores the attempt:

1. A claim holds when the judge said it passed and its confidence is at least the run's `trust`.
   Missing confidence is accepted. Confidence below `trust` makes the claim fail, even if the raw
   decision passed; it stays in the count.
2. Claim completion is the number that hold divided by **all** claims, including required ones.
   Each claim counts equally.
3. The attempt passes when every required claim holds and completion is at least the run's
   `--claim-threshold` (1, or 100%, by default). The comparison uses the unrounded fraction.

For ten claims and `--claim-threshold 0.8`, eight that hold are enough if every required claim
holds. Nine that hold still fail if the remaining claim is required. With every claim required,
all must hold regardless of the threshold. With no required claims, only completion decides.
A threshold of 0 still requires every required claim to hold and never passes an agent failure.

`--claim-threshold` accepts finite values from 0 to 1. It applies to each attempt in the run;
`--trust` sets the confidence needed for one claim, while
[`--fail-under`](runs.md#exit-codes) sets the fraction of passing attempts needed for CI.

## Errors

A valid verdict always produces a passing or failing attempt, even when all its decisions have
low confidence. Genuine failures to obtain a verdict are different:

- If the agent fails a turn, the attempt fails. The judge is not asked.
- If the agent's service stays busy, the attempt gets no verdict and does not count in the pass
  rate. See [A busy service](agents.md#a-busy-service).
- If one of convy's own models fails, the attempt gets no verdict and does not count in the pass
  rate. That happens when a model does not answer, or the judge does not give one decision per
  claim, or gives a decision whose `pass` is not `true` or `false`.

Agent failures and attempts without a verdict have no measured claim completion percentage.
Agent failures still count as failed attempts in [the pass rate](report.md#tiles).

## Running

```sh
uv run convy run support_bot -k 3                  # every scenario, three attempts each
uv run convy run support_bot --scenarios 'refund-*'
uv run convy run support_bot new_bot               # several agents, one after another
uv run convy run support_bot --turn-timeout 60
uv run convy run support_bot --trust 0.8           # fail claims below this confidence
uv run convy run support_bot --claim-threshold 0.8 # require 80% and every required claim
```

`--turn-timeout` (600 by default) is the seconds the agent has to open a conversation, to answer
each turn, and to close it. Taking longer fails the attempt as an agent error.

How many conversations, messages and decisions run at once is set in the project's
`pyproject.toml`; see [How much runs at once](runs.md#how-much-runs-at-once).
