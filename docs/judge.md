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

The judge reads only what the user and the agent said, never the agent's thinking or the other
steps of an answer; see [why](decisions/0010-answer-steps.md).

## How sure the judge is

A judge may say, for each decision, how sure it is: a number from 0 to 1. Run with `--trust` to
set the minimum confidence needed for a claim to hold:

```sh
uv run convy run support_bot --trust 0.8
```

A decision below 0.8 fails the claim and remains in the attempt's claim count. Confidence equal
to 0.8 is accepted, and a decision without confidence is trusted. The original yes/no decision,
reason and confidence are kept, so the report can distinguish a negative judgment from insufficient
confidence. See [Passing an attempt](scenarios.md#passing-an-attempt) for the complete scoring rule.

`trust` defaults to 0 and is saved with the run, so its report and `convy resume` use it.

convy checks the range, not whether the confidence is calibrated. Before you rely on a level,
compare the judge's decisions with your own on some dialogues.

## Your own judge

A judge is any object with a `name` and `decide`. `decide` gets the
dialogue and the claims, and returns one `Claim` per claim, in their order. This one asks a service
that scores how likely a statement is true of a text:

```python
import httpx2

from convy import Claim, Confidence, ModelFailure, Reason, Transcript


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
                decided.append(Claim(p >= 0.5, Reason(f"p = {p:.2f}"), Confidence(max(p, 1 - p))))
            return tuple(decided)
```

Put it in `models.py`, or in a module `models.py` imports, and set `judge=Classifier()`.

- Each input claim is a `str`; required flags and the run's threshold are not sent to the judge.
  Return `Claim(True)` or `Claim(False)`, with an optional reason
  and confidence. Ordered grades are not supported; `Graded`, `Grade` and `NoGrade` are removed
  from the Python API.
- A reason is `Reason(text)`. When there is none, leave it out or give `NoReason()`; an empty
  `Reason("")` is refused.
- Raise `ModelFailure` when the judge cannot decide. Any other error counts the same way: the
  attempt gets no verdict, and the agent is not blamed. The text of the error goes into the run's
  folder and the report, so keep keys out of it.
- An answer with the wrong number of claims, a confidence outside 0 to 1, or a `pass` that is not
  `true` or `false` also leaves the attempt without a verdict.
- `name` is saved with the run. `convy resume` refuses to go on if it changes. If a setting of
  your judge can change its verdicts, change `name` with it.
- Test a judge that calls a service with `httpx2.MockTransport`. Test a judge built on a model
  with the fakes in `convy.fakes`, e.g. `ChatJudge(FakeModel(...))`.
