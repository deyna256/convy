from typing import Any

import msgspec
import pytest

from convy.agent import Answer, Message
from convy.dialog import (
    ChatJudge,
    Checked,
    Claim,
    Confidence,
    Finished,
    NoConfidence,
    SimulatedUser,
    Transcript,
    Turn,
    Verdict,
)
from convy.fakes import FakeJudge, FakeModel
from convy.model import ModelFailure

TRANSCRIPT = Transcript().with_turn(Turn(Message("hi"), Answer("hello"), 1.0))


@pytest.mark.parametrize("value", [-0.1, 1.5, float("nan")])
def test_confidence_is_from_0_to_1(value: float):
    with pytest.raises(ValueError, match="confidence must be from 0 to 1"):
        Confidence(value)


def test_a_claim_without_confidence_reads_as_no_confidence():
    old = b'{"pass": true, "reason": "ok"}'  # a line written before confidence existed
    assert msgspec.json.decode(old, type=Claim) == Claim(True, "ok", NoConfidence())


def test_a_claim_keeps_its_confidence_through_the_run_folder():
    claim = Claim(False, "no", Confidence(0.93))
    assert msgspec.json.decode(msgspec.json.encode(claim), type=Claim) == claim


async def test_checked_passes_confidence_through():
    decided = (Claim(True, "ok", Confidence(0.5)),)
    assert await Checked(FakeJudge(decided)).decide(TRANSCRIPT, ("greets",)) == decided


def test_with_turn_keeps_the_original():
    assert Transcript().turns == ()
    assert len(TRANSCRIPT.with_turn(TRANSCRIPT.turns[0]).turns) == 2
    assert len(TRANSCRIPT.turns) == 1


def test_as_text_is_for_the_judge():
    assert TRANSCRIPT.as_text() == "User: hi\nAgent: hello"


async def test_simulated_user_sees_its_messages_as_its_own():
    model = FakeModel("next")
    assert await SimulatedUser(model, "Be brief.").next(TRANSCRIPT) == Message("next")
    system, opening, own, agent = model.calls[0]
    assert "Be brief." in system["content"]
    assert opening["role"] == "user"
    assert own == {"role": "assistant", "content": "hi"}
    assert agent == {"role": "user", "content": "hello"}


async def test_simulated_user_finishes_on_stop():
    assert await SimulatedUser(FakeModel("Thanks! ###STOP###"), "").next(TRANSCRIPT) == Finished()


@pytest.mark.parametrize(
    ("answer", "claims"),
    [
        ('{"claims": [{"pass": true, "reason": "fine"}]}', (Claim(True, "fine"),)),
        (
            'Sure: {"note": {"x": 1}} then {"claims": [{"pass": false, "reason": "no"}]} ok',
            (Claim(False, "no"),),
        ),
        ('I checked {the claims}. {"claims": [{"pass": true}]}', (Claim(True, ""),)),
    ],
)
async def test_judge_finds_its_decisions_in_the_answer(answer: str, claims: tuple[Claim, ...]):
    assert await ChatJudge(FakeModel(answer)).decide(TRANSCRIPT, ("greets",)) == claims


def test_a_verdict_passes_only_when_every_claim_holds():
    assert Verdict((Claim(True, ""), Claim(True, ""))).passed
    assert not Verdict((Claim(True, ""), Claim(False, "no"))).passed


async def test_simulated_user_with_an_empty_message_fails():
    with pytest.raises(ModelFailure, match="the simulated user gave an empty message"):
        await SimulatedUser(FakeModel("  \n"), "").next(TRANSCRIPT)


async def test_judge_without_a_verdict_is_a_model_failure():
    with pytest.raises(ModelFailure, match="did not answer with JSON: I think it passed"):
        await ChatJudge(FakeModel("I think it passed")).decide(TRANSCRIPT, ("greets",))


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        ('{"claims": [{"pass": "true"}]}', '"pass" is not true or false'),
        ('{"claims": [{"pass": 1}]}', '"pass" is not true or false'),
        ('{"claims": [{"reason": "no pass"}]}', '"pass" is not true or false'),
        ('{"claims": {"pass": true}}', '"claims" is not a list of objects'),
        ('{"claims": [true]}', '"claims" is not a list of objects'),
        ('{"claims": [{"pass": true}, {"pass": true}]}', "decided 2 claims of 1"),
        ('{"claims": []}', "decided 0 claims of 1"),
    ],
)
async def test_judge_with_claims_it_cannot_use_is_a_model_failure(answer: str, error: str):
    with pytest.raises(ModelFailure, match=error):
        await ChatJudge(FakeModel(answer)).decide(TRANSCRIPT, ("greets",))


async def test_judge_gets_the_dialogue_and_the_numbered_claims():
    model = FakeModel('{"claims": [{"pass": true}, {"pass": true}]}')
    await ChatJudge(model).decide(TRANSCRIPT, ("greets", "is brief"))
    prompt = model.calls[0][0]["content"]
    assert "User: hi\nAgent: hello" in prompt
    assert "1. greets\n2. is brief" in prompt


class Answers:
    """A judge whose answer is given as is, right or wrong."""

    name = "answers"

    def __init__(self, answer: Any):  # Any: wrong answers on purpose
        self.answer = answer

    async def decide(self, transcript: Transcript, claims: tuple[str, ...]) -> tuple[Claim, ...]:
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


async def test_checked_passes_a_right_answer_through():
    decided = (Claim(True, "ok"),)
    assert await Checked(FakeJudge(decided)).decide(TRANSCRIPT, ("greets",)) == decided


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        (KeyError("claims"), "answers: KeyError: 'claims'"),
        (ModelFailure("judge down"), "judge down"),
        (("not a claim",), "answers: the decisions are not claims"),
        (Claim(True, "ok"), "answers: the decisions are not claims"),
        ((Claim(True, "ok"), Claim(True, "ok")), "answers: decided 2 claims of 1"),
        ((), "answers: decided 0 claims of 1"),
    ],
)
async def test_checked_turns_a_wrong_judge_into_a_model_failure(answer: object, error: str):
    with pytest.raises(ModelFailure, match=error):
        await Checked(Answers(answer)).decide(TRANSCRIPT, ("greets",))


def sure(passed: bool, value: float | None = None) -> Claim:
    return Claim(passed, "", NoConfidence() if value is None else Confidence(value))


@pytest.mark.parametrize(
    ("claims", "decided", "passed"),
    [
        ((sure(True, 0.9), sure(True, 0.95)), True, True),
        ((sure(True, 0.9), sure(False, 0.85)), True, False),
        ((sure(True, 0.6), sure(False, 0.85)), True, False),
        ((sure(True, 0.9), sure(False, 0.6)), False, False),
        ((sure(True), sure(True, 0.8)), True, True),
    ],
)
def test_a_verdict_counts_when_a_trusted_claim_failed_or_every_claim_is_trusted(
    claims: tuple[Claim, ...], decided: bool, passed: bool
):
    verdict = Verdict(claims)
    assert verdict.decided(0.8) is decided
    assert verdict.passed is passed


def test_trust_0_trusts_every_decision():
    assert Verdict((sure(True, 0.0), sure(False, 0.1))).decided(0)
