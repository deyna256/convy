from typing import Any

import msgspec
import pytest

from convy.agent import Answer, Message, Thinking
from convy.dialog import (
    ChatJudge,
    Checked,
    Claim,
    Confidence,
    Finished,
    Grade,
    Graded,
    NoConfidence,
    NoGrade,
    NoReason,
    Reason,
    SimulatedUser,
    Transcript,
    Turn,
    Verdict,
)
from convy.fakes import FakeJudge, FakeModel
from convy.model import ModelFailure

TRANSCRIPT = Transcript().with_turn(Turn(Message("hi"), Answer("hello"), 1.0))
THOUGHT = Transcript((Turn(Message("hi"), Answer("hello", thinking=Thinking("be warm")), 1.0),))


@pytest.mark.parametrize("value", [-0.1, 1.5, float("nan")])
def test_confidence_is_from_0_to_1(value: float):
    with pytest.raises(ValueError, match="confidence must be from 0 to 1"):
        Confidence(value)


def test_a_claim_without_confidence_reads_as_no_confidence():
    written = b'{"pass": true}'
    assert msgspec.json.decode(written, type=Claim) == Claim(True, NoReason(), NoConfidence())


@pytest.mark.parametrize("text", ["", "  "])
def test_a_reason_needs_text(text: str):
    with pytest.raises(ValueError, match=r"a reason needs text; give NoReason\(\) instead"):
        Reason(text)


def test_a_claim_keeps_its_confidence_through_the_run_folder():
    claim = Claim(False, Reason("no"), Confidence(0.93))
    assert msgspec.json.decode(msgspec.json.encode(claim), type=Claim) == claim


async def test_checked_passes_confidence_through():
    decided = (Claim(True, Reason("ok"), Confidence(0.5)),)
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
        ('{"claims": [{"pass": true, "reason": "fine"}]}', (Claim(True, Reason("fine")),)),
        (
            'Sure: {"note": {"x": 1}} then {"claims": [{"pass": false, "reason": "no"}]} ok',
            (Claim(False, Reason("no")),),
        ),
        ('I checked {the claims}. {"claims": [{"pass": true}]}', (Claim(True),)),
    ],
)
async def test_judge_finds_its_decisions_in_the_answer(answer: str, claims: tuple[Claim, ...]):
    assert await ChatJudge(FakeModel(answer)).decide(TRANSCRIPT, ("greets",)) == claims


def test_a_verdict_passes_only_when_every_claim_holds():
    assert Verdict((Claim(True), Claim(True))).passed
    assert not Verdict((Claim(True), Claim(False, Reason("no")))).passed


async def test_simulated_user_with_an_empty_message_fails():
    with pytest.raises(ModelFailure, match="the simulated user gave an empty message"):
        await SimulatedUser(FakeModel("  \n"), "").next(TRANSCRIPT)


async def test_judge_without_a_verdict_is_a_model_failure():
    with pytest.raises(ModelFailure, match="did not answer with JSON: I think it passed"):
        await ChatJudge(FakeModel("I think it passed")).decide(TRANSCRIPT, ("greets",))


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        ('{"claims": [{"pass": "true"}]}', "claim 1: Expected `bool`, got `str`"),
        ('{"claims": [{"pass": 1}]}', "claim 1: Expected `bool`, got `int`"),
        ('{"claims": [{"reason": "no pass"}]}', "claim 1: Object missing required field `pass`"),
        ('{"claims": [{"pass": true, "reason": 5}]}', "claim 1: Expected `str | null`, got `int`"),
        ('{"claims": [{"pass": true, "reason": {}}]}', "claim 1: Expected `str | null`, got"),
        ('{"claims": {"pass": true}}', '"claims" is not a list'),
        ('{"claims": [true]}', "claim 1: Expected `object`, got `bool`"),
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
    reviews_agent_thinking = False

    def __init__(self, answer: Any):  # Any: wrong answers on purpose
        self.answer = answer

    async def decide(
        self, transcript: Transcript, claims: tuple[str | Graded, ...]
    ) -> tuple[Claim, ...]:
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        (KeyError("claims"), "answers: KeyError: 'claims'"),
        (ModelFailure("judge down"), "judge down"),
        (("not a claim",), "answers: the decisions are not claims"),
        (Claim(True, Reason("ok")), "answers: the decisions are not claims"),
        ((Claim(True, Reason("ok")), Claim(True, Reason("ok"))), "answers: decided 2 claims of 1"),
        ((), "answers: decided 0 claims of 1"),
        (
            ({"pass": True, "confidence": {"type": "confidence", "value": 1.5}},),
            "answers: the decisions are not claims: confidence must be from 0 to 1",
        ),
    ],
)
async def test_checked_turns_a_wrong_judge_into_a_model_failure(answer: object, error: str):
    with pytest.raises(ModelFailure, match=error):
        await Checked(Answers(answer)).decide(TRANSCRIPT, ("greets",))


def sure(passed: bool, value: float | None = None) -> Claim:
    return Claim(passed, confidence=NoConfidence() if value is None else Confidence(value))


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


STEPS = Graded("covers every step", ("none", "partial", "full"), "partial")


@pytest.mark.parametrize(
    ("grades", "threshold", "error"),
    [
        (("full",), "full", "at least two grades"),
        (("none", "full", "none"), "full", "a grade is listed twice"),
        ((1, "1"), 1, "a grade is listed twice"),
        (("none", "full"), "partial", "pass must be one of the grades"),
    ],
)
def test_graded_rejects_grades_it_cannot_use(grades: tuple, threshold: str, error: str):
    with pytest.raises(ValueError, match=error):
        Graded("covers every step", grades, threshold)


def test_graded_passes_at_its_threshold_and_above():
    assert [STEPS.passes(grade) for grade in STEPS.levels] == [False, True, True]
    polite = msgspec.convert({"claim": "polite", "grades": [1, 2, 3, 4, 5], "pass": 4}, Graded)
    assert polite.levels == ("1", "2", "3", "4", "5")
    assert [polite.passes(grade) for grade in polite.levels] == [False] * 3 + [True] * 2


def test_a_decision_without_a_grade_has_no_grade():
    assert msgspec.json.decode(b'{"pass": true}', type=Claim).grade == NoGrade()


async def test_judge_grades_a_graded_claim_and_the_scenario_says_if_it_passes():
    model = FakeModel(
        '{"claims": [{"pass": true, "reason": "hi"}, {"grade": "none", "reason": "no steps"}]}'
    )
    decided = await ChatJudge(model).decide(TRANSCRIPT, ("greets", STEPS))
    assert decided == (
        Claim(True, Reason("hi")),
        Claim(False, Reason("no steps"), grade=Grade("none")),
    )
    assert "2. covers every step (grades: none, partial, full)" in model.calls[0][0]["content"]


async def test_judge_reads_a_number_as_its_grade():
    polite = Graded("polite", (1, 2, 3), 2)
    decided = await ChatJudge(FakeModel('{"claims": [{"grade": 3}]}')).decide(TRANSCRIPT, (polite,))
    assert decided == (Claim(True, grade=Grade("3")),)


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        ('{"claims": [{"grade": "most"}]}', "claim 1: the grade 'most' is not one of none, "),
        ('{"claims": [{"pass": true}]}', "claim 1: Object missing required field `grade`"),
        ('{"claims": [{"grade": true}]}', "claim 1: Expected `int | str`, got `bool`"),
    ],
)
async def test_judge_without_one_of_the_grades_is_a_model_failure(answer: str, error: str):
    with pytest.raises(ModelFailure, match=error):
        await ChatJudge(FakeModel(answer)).decide(TRANSCRIPT, (STEPS,))


@pytest.mark.parametrize(
    ("said", "reason"),
    [
        ('{"pass": true}', NoReason()),
        ('{"pass": true, "reason": null}', NoReason()),
        ('{"pass": true, "reason": "  "}', NoReason()),
        ('{"pass": true, "reason": "fine"}', Reason("fine")),
    ],
)
async def test_judge_without_a_reason_gives_no_reason(said: str, reason: Reason | NoReason):
    model = FakeModel(f'{{"claims": [{said}]}}')
    (decided,) = await ChatJudge(model).decide(TRANSCRIPT, ("greets",))
    assert decided.reason == reason


@pytest.mark.parametrize(
    ("claim", "decision", "error"),
    [
        ("greets", Claim(True, grade=Grade("full")), "a grade, 'full', for a claim that is"),
        (STEPS, Claim(True), "no grade for a graded claim"),
        (STEPS, Claim(True, grade=Grade("most")), "the grade 'most' is not one of"),
        (STEPS, Claim(True, grade=Grade("none")), "the grade 'none' fails, but pass is True"),
        (STEPS, Claim(False, grade=Grade("full")), "the grade 'full' passes, but pass is"),
    ],
)
async def test_checked_refuses_a_grade_the_scenario_does_not_allow(
    claim: str | Graded, decision: Claim, error: str
):
    with pytest.raises(ModelFailure, match=f"answers: claim 1: {error}"):
        await Checked(Answers((decision,))).decide(TRANSCRIPT, (claim,))


def test_as_text_shows_the_thinking_the_transcript_has():
    assert THOUGHT.as_text() == "User: hi\nAgent (thinking): be warm\nAgent: hello"
    assert THOUGHT.without_thinking().as_text() == "User: hi\nAgent: hello"


def test_a_chat_judge_that_reviews_the_thinking_has_another_name():
    """The setting changes what the judge reads, so resume and compare must see it in the name."""
    model = FakeModel("{}")
    assert ChatJudge(model).name == model.name
    assert ChatJudge(model, reviews_agent_thinking=True).name == f"{model.name} + agent thinking"


async def test_simulated_user_never_sees_the_thinking():
    model = FakeModel("next")
    await SimulatedUser(model, "Be brief.").next(THOUGHT)
    assert "be warm" not in str(model.calls[0])


@pytest.mark.parametrize("reviews", [False, True])
async def test_checked_gives_a_judge_the_thinking_only_if_it_reviews_it(reviews: bool):
    judge = FakeJudge((Claim(True, Reason("ok")),), reviews_agent_thinking=reviews)
    await Checked(judge).decide(THOUGHT, ("greets",))
    ((seen, _),) = judge.calls
    assert ("be warm" in seen.as_text()) is reviews


async def test_a_judge_that_does_not_say_whether_it_reviews_the_thinking_fails():
    class Silent:
        name = "silent"

        async def decide(self, transcript: Transcript, claims: tuple) -> tuple[Claim, ...]:
            return (Claim(True, Reason("ok")),)

    silent: Any = Silent()  # Any: a judge without the property on purpose
    with pytest.raises(ModelFailure, match="silent: AttributeError"):
        await Checked(silent).decide(THOUGHT, ("greets",))


async def test_a_chat_judge_that_reviews_the_thinking_shows_it_to_its_model():
    model = FakeModel('{"claims": [{"pass": true}]}')
    await Checked(ChatJudge(model, reviews_agent_thinking=True)).decide(THOUGHT, ("greets",))
    assert "Agent (thinking): be warm" in model.calls[0][0]["content"]
