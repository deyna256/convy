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
- `judge` lists claims as text. All of them must hold for the scenario to pass.
- `max_turns` is how many messages the user may send.
- `id` must be unique across all folders.

Write scenarios in any language. The simulated user speaks the language of its instructions.

Each claim needs a yes/no answer. State the condition the dialogue must meet, and split independent
requirements into separate claims so a failure has a clear reason.

Ordered claim scales have been removed. Replace a mapping with `claim`, `grades` and `pass` with a
plain statement of the condition that counts as passing. Such mappings are rejected; convy does not
convert a scale into a yes/no condition for you.

## Verdicts

The judge decides each claim on its own and gives a reason, so the report shows which claim failed.

- If the agent fails a turn, the attempt fails. The judge is not asked.
- If the agent's service stays busy, the attempt gets no verdict and does not count in the pass
  rate. See [A busy service](agents.md#a-busy-service).
- If one of convy's own models fails, the attempt gets no verdict and does not count in the pass
  rate. That happens when a model does not answer, or the judge does not give one decision per
  claim, or gives a decision whose `pass` is not `true` or `false`.
- If the judge is less sure than the run's `--trust`, the attempt may not count;
  [the pass rate](report.md#tiles) gives the rule. See [The judge](judge.md).

## Running

```sh
uv run convy run support_bot -k 3                  # every scenario, three attempts each
uv run convy run support_bot --scenarios 'refund-*'
uv run convy run support_bot new_bot               # several agents, one after another
uv run convy run support_bot --turn-timeout 60
uv run convy run support_bot --trust 0.8           # leave out unsure verdicts
```

`--turn-timeout` (600 by default) is the seconds the agent has to open a conversation, to answer
each turn, and to close it. Taking longer fails the attempt as an agent error.

How many conversations, messages and decisions run at once is set in the project's
`pyproject.toml`; see [How much runs at once](runs.md#how-much-runs-at-once).
