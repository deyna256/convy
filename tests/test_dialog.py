from typing import Any

import pytest

from convy.agent import Answer, Message
from convy.dialog import (
    ChatJudge,
    Checked,
    Claim,
    Finished,
    SimulatedUser,
    Transcript,
    Turn,
    Verdict,
)
from convy.fakes import FakeJudge, FakeModel
from convy.model import ModelFailure

TRANSCRIPT = Transcript().with_turn(Turn(Message("hi"), Answer("hello"), 1.0))


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
