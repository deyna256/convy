"""The promises every `Judge` keeps, checked on each implementation convy ships."""

import pytest

from convy.busy import Busy, Patience, Places
from convy.dialog import (
    ChatJudge,
    Claim,
    Grade,
    Graded,
    Judge,
    PatientJudge,
    Reason,
    Transcript,
)
from convy.fakes import FakeJudge, FakeModel
from convy.model import ModelFailure

DECIDED = '{"claims": [{"pass": true, "reason": "ok"}, {"grade": "most", "reason": "no"}]}'
CLAIMS = ("greets", Graded("is brief", ("long", "most", "brief"), "brief"))
CLAIMED = (Claim(True, Reason("ok")), Claim(False, Reason("no"), grade=Grade("most")))

JUDGES = {
    "ChatJudge": lambda: ChatJudge(FakeModel(DECIDED)),
    "FakeJudge": lambda: FakeJudge(CLAIMED),
    "PatientJudge": lambda: PatientJudge(FakeJudge(CLAIMED), Patience(), Places(1)),
}
FAILING = {
    "ChatJudge": lambda: ChatJudge(FakeModel(ModelFailure("down"))),
    "FakeJudge": lambda: FakeJudge(ModelFailure("down")),
    "PatientJudge": lambda: PatientJudge(FakeJudge(ModelFailure("down")), Patience(), Places(1)),
}
BUSY = {
    "ChatJudge": lambda: ChatJudge(FakeModel(Busy("slow down", 1))),
    "FakeJudge": lambda: FakeJudge(Busy("slow down", 1)),
    "PatientJudge": lambda: PatientJudge(
        FakeJudge(Busy("slow down", 1)), Patience(seconds=0), Places(1)
    ),
}


@pytest.mark.parametrize("make", JUDGES.values(), ids=JUDGES)
async def test_decide_gives_one_claim_per_claim_in_order_and_name_is_set(make):
    judge: Judge = make()
    assert await judge.decide(Transcript(), CLAIMS) == CLAIMED
    assert judge.name


@pytest.mark.parametrize("make", FAILING.values(), ids=FAILING)
async def test_failure_is_model_failure(make):
    with pytest.raises(ModelFailure):
        await make().decide(Transcript(), CLAIMS)


@pytest.mark.parametrize("make", JUDGES.values(), ids=JUDGES)
def test_a_judge_says_whether_it_reviews_the_agent_thinking(make):
    assert make().reviews_agent_thinking is False


@pytest.mark.parametrize("make", BUSY.values(), ids=BUSY)
async def test_a_busy_service_is_busy(make):
    """A decision the service refused because it is busy raises `Busy`, which convy waits on."""
    with pytest.raises(Busy):
        await make().decide(Transcript(), CLAIMS)
