# The judge

The judge reads the dialogue and decides each claim of the scenario: whether it holds, and why. It
is set in `models.py`:

```python
from convy import ChatJudge, Models, OpenAiModel

from gateway import gateway

models = Models(
    user=OpenAiModel(gateway, "gpt-4.1-mini"),
    judge=ChatJudge(OpenAiModel(gateway, "gpt-4.1-mini")),
)
```

`ChatJudge` asks a chat model, with a prompt of convy's. It does not say how sure it is.

## How sure the judge is

A judge may say, for each decision, how sure it is: a number from 0 to 1. Run with `--trust` to
leave out what it is less sure of:

```sh
uv run convy run support_bot --trust 0.8
```

A decision below 0.8 is not trusted. An attempt counts only if some trusted claim failed, or every
claim is trusted. An attempt that does not count is neither a pass nor a fail: it is left out of the
pass rate, and the report says how many were left out. A decision with no number is trusted.

`trust` is saved with the run, so its report and `convy resume` use it. Without `--trust` every
decision counts.

convy does not check the numbers. Before you rely on a level, compare the judge's decisions with
your own on some dialogues.

## Your own judge

A judge is any object with a `name` and `decide`. `decide` gets the dialogue and the claims, and
returns one `Claim` per claim, in their order. This one asks a service that scores how likely a
statement is true of a text:

```python
import httpx2

from convy import Claim, Confidence, ModelFailure, Transcript


class Classifier:
    name = "claim-classifier"

    async def decide(self, transcript: Transcript, claims: tuple[str, ...]) -> tuple[Claim, ...]:
        async with httpx2.AsyncClient(base_url="https://classifier.example.com") as http:
            decided = []
            for claim in claims:
                response = await http.post(
                    "/score", json={"text": transcript.as_text(), "statement": claim}
                )
                if response.is_error:
                    raise ModelFailure(f"the classifier answered {response.status_code}")
                p = response.json()["probability"]  # how likely the claim holds
                decided.append(Claim(p >= 0.5, f"p = {p:.2f}", Confidence(max(p, 1 - p))))
            return tuple(decided)
```

Put it in `models.py`, or in a module `models.py` imports, and set `judge=Classifier()`.

- Raise `ModelFailure` when the judge cannot decide. Any other error counts the same way: the
  attempt gets no verdict, and the agent is not blamed.
- An answer with the wrong number of claims, or a confidence outside 0 to 1, also leaves the attempt
  without a verdict.
- `name` is saved with the run. `convy resume` refuses to go on if it changes.
- Test a judge that calls a service with `httpx2.MockTransport`. Test a judge built on a model
  with the fakes in `convy.fakes`, e.g. `ChatJudge(FakeModel(...))`.
