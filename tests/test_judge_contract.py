"""The promises every `Judge` keeps, checked on each implementation convy ships."""

import pytest

from convy.dialog import ChatJudge, Claim, Grade, Graded, Judge, Transcript
from convy.fakes import FakeJudge, FakeModel
from convy.model import ModelFailure

DECIDED = '{"claims": [{"pass": true, "reason": "ok"}, {"grade": "most", "reason": "no"}]}'
CLAIMS = ("greets", Graded("is brief", ("long", "most", "brief"), "brief"))
CLAIMED = (Claim(True, "ok"), Claim(False, "no", grade=Grade("most")))

JUDGES = {
    "ChatJudge": lambda: ChatJudge(FakeModel(DECIDED)),
    "FakeJudge": lambda: FakeJudge(CLAIMED),
}
FAILING = {
    "ChatJudge": lambda: ChatJudge(FakeModel(ModelFailure("down"))),
    "FakeJudge": lambda: FakeJudge(ModelFailure("down")),
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
