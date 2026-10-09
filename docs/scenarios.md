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
  - Before giving a finished script, the agent asked what to back up and where to
  - The final script copies ~/photos to /mnt/backup and runs once a day
```

- `user` tells the simulated user who to be and what to want.
- `judge` lists claims. All of them must hold for the scenario to pass.
- `max_turns` is how many messages the user may send.
- `id` must be unique across all folders.

Write scenarios in any language. The simulated user speaks the language of its instructions.

## Verdicts

The judge decides each claim on its own and gives a reason, so the report shows which claim failed.

- If the agent fails a turn, the attempt fails. The judge is not asked.
- If one of convy's own models fails, the attempt gets no verdict and does not count in the pass
  rate. That happens when a model does not answer, or the judge does not give one decision per
  claim.
- If the judge is less sure than the run's `--trust`, the attempt does not count either. See
  [The judge](judge.md).

## Running

```sh
uv run convy run support_bot -k 3                  # every scenario, three attempts each
uv run convy run support_bot --scenarios 'refund-*'
uv run convy run support_bot new_bot               # several agents, one after another
uv run convy run support_bot --turn-timeout 60
uv run convy run support_bot --trust 0.8           # leave out unsure verdicts
```

`--turn-timeout` (600 by default) is the seconds for each step of the agent: opening a conversation,
a turn, closing it. A step that takes longer fails the attempt as an agent error.
