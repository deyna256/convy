# Scenarios

A scenario says who the simulated user is, what they want, and what must be true of the dialogue.
Save it as a `.yaml` file in `scenarios/` or any folder under it, such as `scenarios/bank/cards/`.

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
  A plain string means the claim is optional. Include at least one claim.
- `max_turns` sets the maximum number of user messages. Use a positive integer.
- `id` must be unique across all folders.

Write scenarios in any language. The simulated user speaks the language of its instructions.

Each claim needs a yes/no answer. State the condition the dialogue must meet, and split independent
requirements into separate claims so a failure has a clear reason.

To update an older scenario with `grades` and `pass`, rewrite each graded claim as a yes/no statement.

## Passing an attempt

The judge returns one decision per claim. convy applies the run settings to those decisions.

1. A claim holds when the judge said it passed and its confidence is at least the run's `trust`.
   Missing confidence is accepted. Confidence below `trust` makes the claim fail, even if the raw
   decision passed; it stays in the count.
2. Claim completion is the number that hold divided by **all** claims, including required ones.
   Each claim counts equally.
3. The attempt passes when every required claim holds and completion is at least the run's
   `--claim-threshold` (1, or 100%, by default). The comparison uses the unrounded fraction.

With ten claims and `--claim-threshold 0.8`, eight passes are enough if all required claims
pass. Even nine passes are insufficient if the failed claim was required. At a threshold of
zero, required claims must still pass.

`--claim-threshold` accepts values from 0 to 1. It applies to **one attempt**.
[`--fail-under`](runs.md#exit-codes) applies to the **run's pass rate**.

## Errors

- An agent error fails the attempt and counts against the pass rate. convy skips the judge.
- If the agent's service stays [busy](agents.md#a-busy-service), the simulated user fails,
  or the judge cannot return valid decisions, the attempt has no verdict. convy excludes it
  from the pass rate.

Neither outcome has a claim completion percentage. A valid verdict with low-confidence
decisions still receives a score.

## Running

```sh
uv run convy run support_bot -k 3                  # every scenario, three attempts each
uv run convy run support_bot --scenarios 'refund-*'
uv run convy run support_bot new_bot               # several agents, one after another
uv run convy run support_bot --turn-timeout 60
uv run convy run support_bot --trust 0.8           # fail claims below this confidence
uv run convy run support_bot --claim-threshold 0.8 # require 80% and every required claim
```

`--turn-timeout` sets a separate time limit for opening a conversation, answering each message,
and closing the conversation. The default is 600 seconds. A timeout counts as an agent error.

How many conversations, messages and decisions run at once is set in the project's
`pyproject.toml`; see [How much runs at once](runs.md#how-much-runs-at-once).
