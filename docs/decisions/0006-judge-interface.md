# 6. The judge is an interface its owner implements

**Status:** Accepted

## Context

The judge said only "pass" or "fail" for each claim. A clear verdict and a guess counted the same in
the pass rate, in Passing, Flaky and Failing, and in the comparison of two builds. In the demo, "The
agent offered a free replacement" failed on one answer and passed on similar ones: the claim was
unclear and the judge guessed.

How sure a judge is cannot be measured well in one way that fits everyone:

- A model's own word on how sure it is barely works. In
  [Trust or Escalate](https://arxiv.org/abs/2407.18370) (ICLR 2025), stated confidence of GPT-4
  separates right from wrong verdicts with an AUROC of 0.55, close to a coin. Probabilities of the
  answer tokens do better (0.64–0.73) but are still too sure, and not every gateway gives them.
  Asking many times and counting agreement was weak too. The best method there needs examples
  labelled by people.
- Every source agrees that a confidence you can rely on needs a check against people's labels on
  your own data.
- Models built to decide rather than to write, such as Jev by TypeSafe AI, return a probability per
  statement, cheaply and steadily. They give no reason, and their calibration is not published.

## Decision

- **The judge is an interface,** like the agent ([0002](0002-agent-interface.md)): an object with a
  `name` and `async decide(transcript, claims)` that returns one `Claim` per claim. convy ships
  `ChatJudge`, a chat model with a prompt, which does not say how sure it is.
- **A decision may carry a `Confidence` from 0 to 1, or `NoConfidence`.** convy does not check that
  the number is calibrated; that is the judge's owner's job.
- **A run has a `trust` level,** recorded in `run.json` like `k`. A verdict the judge is less sure of
  is cut out of the sample: it counts as neither pass nor fail, and the report shows how many were
  cut next to every pass rate. A decision with no confidence is trusted.
- **Raw decisions and confidence are kept;** `trust` only reads them.

## Alternatives

- **A built-in confidence:** the model's own word, token probabilities, or asking many times. Each
  is either unreliable or works only with some models; picking one would make it convy's promise.
- **A built-in Jev judge.** A closed service in early access, without reasons for its decisions.
  Anyone can write it as their own judge.
- **`trust` applied when pages are built** (`convy report --trust`), not recorded in the run. Then
  the pages depend on the last command: `convy run` rebuilds every page. Since `trust` decides what a
  run measured, it belongs to the run.
- **A slider on the page.** Every number would have to be computed in the browser, a second copy of
  `report.py` without tests.
- **Count an unsure verdict as a fail.** The agent would pay for the judge's doubt.

## Consequences

- `models.py` says `judge=ChatJudge(model)`.
- A judge is user code: any error, or an answer that is not one `Claim` per claim, is a failure of
  convy's model, and the attempt has no verdict.
- Fewer attempts may count at a high `trust`, so the report always says how many were cut.
- Two runs with different `trust` can be compared; each is read with its own.
