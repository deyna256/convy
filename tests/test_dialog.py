import pytest

from convy.agent import Answer, Message
from convy.dialog import Claim, Finished, Judge, SimulatedUser, Transcript, Turn, Verdict
from convy.fakes import FakeModel
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
    ("answer", "verdict"),
    [
        (
            '{"claims": [{"pass": true, "reason": "fine"}]}',
            Verdict((Claim(True, "fine"),)),
        ),
        (
            'Sure: {"note": {"x": 1}} then {"claims": [{"pass": false, "reason": "no"}]} ok',
            Verdict((Claim(False, "no"),)),
        ),
        (
            'I checked {the claims}. {"claims": [{"pass": true}]}',
            Verdict((Claim(True, ""),)),
        ),
    ],
)
async def test_judge_finds_its_verdict_in_the_answer(answer: str, verdict: Verdict):
    assert await Judge(FakeModel(answer)).verdict(TRANSCRIPT, ("greets",)) == verdict


def test_a_verdict_passes_only_when_every_claim_holds():
    assert Verdict((Claim(True, ""), Claim(True, ""))).passed
    assert not Verdict((Claim(True, ""), Claim(False, "no"))).passed


async def test_simulated_user_with_an_empty_message_fails():
    with pytest.raises(ModelFailure, match="the simulated user gave an empty message"):
        await SimulatedUser(FakeModel("  \n"), "").next(TRANSCRIPT)


async def test_judge_without_a_verdict_is_a_model_failure():
    with pytest.raises(ModelFailure, match="did not answer with JSON: I think it passed"):
        await Judge(FakeModel("I think it passed")).verdict(TRANSCRIPT, ("greets",))


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
        await Judge(FakeModel(answer)).verdict(TRANSCRIPT, ("greets",))


async def test_judge_gets_the_dialogue_and_the_numbered_claims():
    model = FakeModel('{"claims": [{"pass": true}, {"pass": true}]}')
    await Judge(model).verdict(TRANSCRIPT, ("greets", "is brief"))
    prompt = model.calls[0][0]["content"]
    assert "User: hi\nAgent: hello" in prompt
    assert "1. greets\n2. is brief" in prompt
