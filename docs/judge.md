# The judge

The judge decides whether each claim holds for a dialogue. Set it in `models.py`.

```python
from convy import ChatJudge, Models, OpenAiModel

from gateway import gateway

models = Models(
    user=OpenAiModel(gateway, "gpt-4.1-mini"),
    judge=ChatJudge(OpenAiModel(gateway, "gpt-4.1-mini")),
)
```

`ChatJudge` sends the dialogue text and claims to a chat model. It asks for a yes/no decision
and a reason for each claim. It does not report confidence. A custom Python judge receives a
`Transcript` with the answer steps removed. It can still read turn durations and reported usage.
See [Answer steps](decisions/0010-answer-steps.md).

## How sure the judge is

A custom judge can report confidence from 0 to 1 for each decision. Set the minimum with
`--trust` (default 0).

```sh
uv run convy run support_bot --trust 0.8
```

At this setting, a positive decision with confidence 0.79 fails the claim. A positive decision
at 0.8 passes, as does one with no confidence score. convy saves the original decisions and
the cutoff with the run. See [Passing an attempt](scenarios.md#passing-an-attempt).

Before relying on a cutoff, compare a sample of the judge's decisions with your own.
A value in the allowed range can still be overconfident.

## Your own judge

Give the judge a `name` and an async `decide` method. Return one `Claim` per input statement,
in the same order. This example uses a service that estimates how likely a statement is to be true.

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

- `decide` receives the claim texts. convy applies the required flags and threshold after judging.
- Return `Claim(True)` or `Claim(False)`. A reason and a confidence score are optional.
  Use `Reason(text)` for a nonempty explanation, or omit the reason.
- Raise `ModelFailure` if the judge cannot decide. An exception or invalid result (for example,
  a missing decision) leaves the attempt without a verdict. The error text appears in the run's
  files and report, so keep credentials out of it.
- Update `name` when a change to your judge could affect its decisions. convy records the name
  and checks it on resume.
- Test HTTP calls with `httpx2.MockTransport`. For a model-based judge, use
  `ChatJudge(FakeModel(...))` from `convy` and `convy.fakes`, respectively.
