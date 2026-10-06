import pytest

from convy.agent import Answer, Message
from convy.dialog import Finished, Judge, SimulatedUser, Transcript, Turn, Verdict
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
        ('{"pass": true, "reason": "fine"}', Verdict(True, "fine")),
        ('Sure: {"note": {"x": 1}} then {"pass": false, "reason": "no"} ok', Verdict(False, "no")),
        ('I checked {the claims}. {"pass": true, "reason": "ok"}', Verdict(True, "ok")),
    ],
)
async def test_judge_finds_its_verdict_in_the_answer(answer: str, verdict: Verdict):
    assert await Judge(FakeModel(answer)).verdict(TRANSCRIPT, ("greets",)) == verdict


async def test_simulated_user_with_an_empty_message_fails():
    with pytest.raises(ModelFailure, match="the simulated user gave an empty message"):
        await SimulatedUser(FakeModel("  \n"), "").next(TRANSCRIPT)


async def test_judge_without_a_verdict_is_a_model_failure():
    with pytest.raises(ModelFailure, match="did not answer with JSON: I think it passed"):
        await Judge(FakeModel("I think it passed")).verdict(TRANSCRIPT, ("greets",))


@pytest.mark.parametrize("answer", ['{"pass": "true", "reason": "fine"}', '{"pass": 1}'])
async def test_judge_with_a_pass_that_is_not_a_bool_is_a_model_failure(answer: str):
    with pytest.raises(ModelFailure, match=r'"pass" is not true or false: \{"pass": '):
        await Judge(FakeModel(answer)).verdict(TRANSCRIPT, ("greets",))


async def test_judge_gets_the_dialogue_and_the_claims():
    model = FakeModel('{"pass": true}')
    await Judge(model).verdict(TRANSCRIPT, ("greets", "is brief"))
    prompt = model.calls[0][0]["content"]
    assert "User: hi\nAgent: hello" in prompt
    assert "- greets\n- is brief" in prompt
