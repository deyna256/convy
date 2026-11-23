import json
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2
import msgspec
import pytest
from pydantic_settings import SettingsConfigDict

from convy import Requirement
from convy.agent import AgentFailure, Answer, Usage
from convy.bench import RunJournal, RunSpec
from convy.busy import Busy, Patience, Places
from convy.dialog import ChatJudge, Claim, Failed, NoVerdict, Reason, Verdict
from convy.env import Env
from convy.fakes import EchoConversation, FakeAgent, FakeJudge, FakeModel
from convy.http import JsonEndpoint, Tls
from convy.model import ModelFailure, Models, OpenAiModel
from convy.report import Runs
from convy.scenario import Matching, Outcome, Scenario, Scenarios

SCENARIO = Scenario(
    id="greet", max_turns=2, instructions="Say hi.", claims=(Requirement("greets"),)
)
PASS = '{"claims": [{"pass": true, "reason": "fine"}]}'
PATIENCE = Patience()  # frozen, so one serves every test


def alone(patience: Patience = PATIENCE) -> Places:
    """The places of an agent played outside a bench: one conversation, each test its own."""
    return Places(1, patience)


def models(*user: str | ModelFailure, judge: str | ModelFailure = PASS) -> Models:
    return Models(user=FakeModel(*user), judge=ChatJudge(FakeModel(judge)))


async def test_turns_run_out():
    outcome = await SCENARIO.outcome(
        FakeAgent(Answer("hello", Usage(3, 4))), models("hi"), attempt=1, places=alone()
    )
    assert outcome.stop == "max_turns"
    assert outcome.verdict == Verdict((Claim(True, Reason("fine")),))
    assert [t.answer.usage for t in outcome.transcript.turns] == [Usage(3, 4)] * 2
    assert all(t.seconds >= 0 for t in outcome.transcript.turns)
    assert (outcome.scenario, outcome.attempt) == ("greet", 1)


async def test_the_user_finishes():
    outcome = await SCENARIO.outcome(
        FakeAgent("hello"), models("hi", "###STOP###"), attempt=1, places=alone()
    )
    assert outcome.stop == "user_stop"
    assert len(outcome.transcript.turns) == 1


@pytest.mark.parametrize("error", [AgentFailure("down"), KeyError("bug")])
async def test_a_failed_turn_fails_the_attempt_without_the_judge(error: Exception):
    judge = FakeModel(PASS)
    used = Models(user=FakeModel("hi"), judge=ChatJudge(judge))
    outcome = await SCENARIO.outcome(FakeAgent("hello", error), used, attempt=1, places=alone())
    assert outcome.stop == "agent_failure"
    assert isinstance(outcome.verdict, Failed)
    assert outcome.transcript.turns[-1].answer.text.startswith(
        f"[agent error: {type(error).__name__}"
    )
    assert judge.calls == []


@pytest.mark.parametrize(
    "answer", [Answer("x", Usage(True, 1)), "not an Answer", Answer("\ud83d"), object()]
)
async def test_a_wrong_answer_fails_the_turn(answer: object):
    class Wrong:
        async def answer(self, message: object) -> object:
            return answer

    class Agent:
        @asynccontextmanager
        async def conversation(self):
            yield Wrong()

    outcome = await SCENARIO.outcome(Agent(), models("hi"), attempt=1, places=alone())
    assert outcome.stop == "agent_failure"
    assert "the answer is not a valid Answer" in outcome.transcript.turns[-1].answer.text
    msgspec.json.decode(msgspec.json.encode(outcome), type=Outcome)  # the journal can read it


class LikeUsage(msgspec.Struct, frozen=True, tag="usage"):
    """The shape of `Usage` without its check, as an agent's own class might send it."""

    input: int = 1
    output: int = 2
    thinking: int = 5


@pytest.mark.parametrize("build", [lambda: Usage(1, 2, 5), LikeUsage])
async def test_thinking_tokens_above_the_output_fail_the_turn_not_the_run(build):
    class Talking:
        async def answer(self, message: object) -> Answer:
            return Answer("x", build())

    class Agent:
        @asynccontextmanager
        async def conversation(self):
            yield Talking()

    outcome = await SCENARIO.outcome(Agent(), models("hi"), attempt=1, places=alone())
    assert outcome.stop == "agent_failure"
    assert "thinking tokens must be from 0 to the output's 2" in str(outcome.verdict)


class LikeCall(msgspec.Struct, frozen=True, tag="call", kw_only=True):
    """The shape of `Call` without its checks, as an agent's own class might send it."""

    name: str = "search"
    started: datetime = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
    seconds: float = -1


async def test_a_step_convy_cannot_store_fails_the_turn_not_the_run():
    class Talking:
        async def answer(self, message: object) -> Answer:
            steps: Any = (LikeCall(),)  # Any: a step without Call's checks on purpose
            return Answer("x", steps=steps)

    class Agent:
        @asynccontextmanager
        async def conversation(self):
            yield Talking()

    outcome = await SCENARIO.outcome(Agent(), models("hi"), attempt=1, places=alone())
    assert outcome.stop == "agent_failure"
    assert "call 'search': seconds must be a finite number, 0 or more" in str(outcome.verdict)


async def test_waiting_for_a_busy_agent_is_not_answer_time():
    agent = FakeAgent(Busy("429", 0.1), "hello")  # every conversation starts the list over
    outcome = await SCENARIO.outcome(agent, models("hi"), 1, alone(Patience(first=0.01)))
    assert outcome.verdict == Verdict((Claim(True, Reason("fine")),))
    assert [turn.answer.text for turn in outcome.transcript.turns] == ["hello", "hello"]
    assert all(turn.seconds < 0.1 for turn in outcome.transcript.turns)


async def test_an_agent_whose_service_stays_busy_is_not_judged():
    judge = FakeModel(PASS)
    used = Models(user=FakeModel("hi"), judge=ChatJudge(judge))
    patience = Patience(seconds=0.05, first=0.01, longest=0.01)
    outcome = await SCENARIO.outcome(FakeAgent(Busy("503")), used, 1, alone(patience))
    assert outcome.stop == "agent_busy"
    assert outcome.failed()
    assert outcome.verdict == NoVerdict(
        "the agent's service stayed busy: 503; convy waits up to 0.05 s for a busy service"
    )
    assert judge.calls == []


async def test_an_agent_busy_when_a_conversation_opens_is_not_judged():
    class Full:
        def conversation(self):
            raise Busy("no free session")

    outcome = await SCENARIO.outcome(Full(), models("hi"), attempt=1, places=alone())
    assert outcome.stop == "agent_busy"
    assert outcome.verdict == NoVerdict("the agent's service stayed busy: no free session")


async def test_an_agent_that_cannot_open_a_conversation_fails():
    class Closed:
        def conversation(self):
            raise ConnectionError("no session")

    outcome = await SCENARIO.outcome(Closed(), models("hi"), attempt=1, places=alone())
    assert outcome.stop == "agent_failure"
    assert outcome.verdict == Failed("[agent error: ConnectionError: no session]")


@pytest.mark.parametrize(
    "used", [models(ModelFailure("user down")), models("hi", judge=ModelFailure("judge down"))]
)
async def test_a_failed_model_leaves_no_verdict(used: Models):
    outcome = await SCENARIO.outcome(FakeAgent("hello"), used, attempt=1, places=alone())
    assert outcome.stop == "model_failure"
    assert isinstance(outcome.verdict, NoVerdict)


class Buggy:
    name = "buggy"

    async def reply(self, messages: list[dict[str, str]]) -> str:
        raise KeyError("choices")


@pytest.mark.parametrize(
    "used",
    [
        Models(user=Buggy(), judge=ChatJudge(FakeModel(PASS))),
        Models(user=FakeModel("hi", "###STOP###"), judge=ChatJudge(Buggy())),
    ],
)
async def test_a_bug_in_a_model_is_a_model_failure(used: Models):
    outcome = await SCENARIO.outcome(FakeAgent("hello"), used, attempt=1, places=alone())
    assert outcome.stop == "model_failure"
    assert outcome.verdict == NoVerdict("buggy: KeyError: 'choices'")


async def test_a_judge_answer_without_a_verdict_leaves_no_verdict():
    outcome = await SCENARIO.outcome(
        FakeAgent("hello"), models("hi", judge="Looks fine."), 1, alone()
    )
    assert outcome.stop == "model_failure"
    assert outcome.verdict == NoVerdict("the judge did not answer with JSON: Looks fine.")


async def test_a_judge_reply_that_cannot_be_encoded_leaves_no_verdict(tmp_path):
    verdict = '{"claims": [{"pass": true, "reason": "\ud83d"}]}'  # half an emoji
    content = json.dumps({"choices": [{"message": {"content": verdict}}]}).encode()
    service = httpx2.MockTransport(lambda request: httpx2.Response(200, content=content))
    judge = OpenAiModel(JsonEndpoint("https://llm.test", transport=service), "gpt")
    used = Models(user=FakeModel("hi", "###STOP###"), judge=ChatJudge(judge))
    outcome = await SCENARIO.outcome(FakeAgent("hello"), used, attempt=1, places=alone())
    assert outcome.stop == "model_failure"
    started = datetime(2026, 10, 6, tzinfo=UTC)
    spec = RunSpec(
        id="run",
        agent="bot",
        version="",
        user="fake",
        judge="gpt",
        k=1,
        turn_timeout=600,
        scenarios=(SCENARIO,),
        started=started,
    )
    journal = RunJournal(tmp_path, spec)
    journal.create()
    journal.record(outcome)
    (run,) = Runs(tmp_path)
    assert run.outcomes == (outcome,)


async def test_a_judge_with_a_broken_tls_leaves_no_verdict():
    endpoint = JsonEndpoint("https://llm.test/chat/completions", tls=Tls(ca="/missing.pem"))
    used = Models(user=FakeModel("hi", "###STOP###"), judge=ChatJudge(OpenAiModel(endpoint, "gpt")))
    outcome = await SCENARIO.outcome(FakeAgent("hello"), used, attempt=1, places=alone())
    assert outcome.stop == "model_failure"
    assert isinstance(outcome.verdict, NoVerdict)
    assert str(Path("/missing.pem")) in outcome.verdict.error


async def test_settings_missing_in_an_agent_do_not_leak_keys(tmp_path, monkeypatch):
    class BotEnv(Env):
        model_config = SettingsConfigDict(env_prefix="BOT_")
        url: str
        key: str

    class Agent:
        @asynccontextmanager
        async def conversation(self):
            BotEnv()
            yield EchoConversation()

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("BOT_URL", raising=False)
    monkeypatch.setenv("BOT_KEY", "sk-SECRET123")
    outcome = await SCENARIO.outcome(Agent(), models("hi"), attempt=1, places=alone())
    assert outcome.stop == "agent_failure"
    assert "url" in str(outcome.verdict)
    assert b"sk-SECRET123" not in msgspec.json.encode(outcome)


def write(directory, name: str, text: str) -> None:
    (directory / name).write_text(text, encoding="utf-8")


def test_scenarios_are_read_from_yaml(tmp_path):
    write(tmp_path, "a.yaml", "id: a\nmax_turns: 3\nuser: |\n  Say no.\njudge:\n  - no\n")
    assert list(Scenarios(tmp_path)) == [Scenario("a", 3, "Say no.\n", (Requirement("no"),))]


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("id: a\nmax_turns: 3\nuser: x\njudge: [y]\nworkspace: z\n", "unknown field `workspace`"),
        ("id: a\nmax_turns: 3\nuser: x\n", "missing required field `judge`"),
        ("id: a\nmax_turns: 0\nuser: x\njudge: [y]\n", "max_turns must be at least 1, got 0"),
        ("id: a\nmax_turns: 3\nuser: x\njudge: []\n", "judge must list at least one claim"),
        ("id: [a\n", "a.yaml"),
        (
            "id: a\nmax_turns: 3\nuser: x\njudge:\n"
            "  - claim: y\n    grades: [no, yes]\n    pass: maybe\n",
            "unknown field `grades`",
        ),
    ],
)
def test_a_wrong_scenario_names_the_file_and_the_problem(tmp_path, text: str, error: str):
    write(tmp_path, "a.yaml", text)
    with pytest.raises(ValueError, match=error):
        list(Scenarios(tmp_path))


@pytest.mark.parametrize(
    ("max_turns", "claims", "error"),
    [
        (0, (Requirement("y"),), "max_turns must be at least 1"),
        (1, (), "judge must list at least one claim"),
    ],
)
def test_a_scenario_rejects_values_it_cannot_play(max_turns: int, claims: tuple, error: str):
    with pytest.raises(ValueError, match=error):
        Scenario("a", max_turns, "x", claims)


def test_scenario_ids_are_unique(tmp_path):
    for name in ("a.yaml", "b.yaml"):
        write(tmp_path, name, "id: same\nmax_turns: 1\nuser: x\njudge: [y]\n")
    with pytest.raises(ValueError, match="already has the id 'same'"):
        list(Scenarios(tmp_path))


def test_scenarios_are_found_in_folders_at_any_depth(tmp_path):
    (tmp_path / "bank" / "cards").mkdir(parents=True)
    write(tmp_path, "top.yaml", "id: top\nmax_turns: 1\nuser: x\njudge: [y]\n")
    write(tmp_path / "bank", "deposit.yaml", "id: deposit\nmax_turns: 1\nuser: x\njudge: [y]\n")
    write(tmp_path / "bank" / "cards", "lost.yaml", "id: lost\nmax_turns: 1\nuser: x\njudge: [y]\n")
    assert sorted(s.id for s in Scenarios(tmp_path)) == ["deposit", "lost", "top"]


def test_an_id_repeated_in_another_folder_names_the_file(tmp_path):
    (tmp_path / "bank").mkdir()
    write(tmp_path, "a.yaml", "id: same\nmax_turns: 1\nuser: x\njudge: [y]\n")
    write(tmp_path / "bank", "b.yaml", "id: same\nmax_turns: 1\nuser: x\njudge: [y]\n")
    with pytest.raises(
        ValueError,
        match=re.escape(f"{Path('bank', 'b.yaml')}: another scenario already has the id"),
    ):
        list(Scenarios(tmp_path))


def test_matching_keeps_scenarios_by_mask():
    scenarios = [SCENARIO, Scenario("refund-late", 1, "x", (Requirement("y"),))]
    assert [s.id for s in Matching(scenarios, "refund-*")] == ["refund-late"]
    with pytest.raises(ValueError, match="no scenario matches 'nope'"):
        list(Matching(scenarios, "nope"))


def test_yaml_normalizes_plain_and_required_claims(tmp_path):
    write(
        tmp_path,
        "a.yaml",
        "id: a\nmax_turns: 1\nuser: Ask.\njudge:\n"
        "  - greets\n  - claim: asks\n    required: true\n"
        "  - claim: explains\n  - claim: polite\n    required: false\n",
    )
    (scenario,) = Scenarios(tmp_path)
    assert scenario.claims == (
        Requirement("greets"),
        Requirement("asks", required=True),
        Requirement("explains"),
        Requirement("polite"),
    )


@pytest.mark.parametrize(
    ("claim", "error"),
    [
        ('{claim: asks, required: "true"}', "Expected `bool`, got `str`"),
        ("{claim: asks, required: 1}", "Expected `bool`, got `int`"),
        ("{claim: asks, required: null}", "Expected `bool`, got `null`"),
        ("{claim: asks, pass: yes}", "unknown field `pass`"),
        ("{required: true}", "missing required field `claim`"),
        ("{claim: 4}", "Expected `str`, got `int`"),
    ],
)
def test_yaml_rejects_invalid_requirement_mappings(tmp_path, claim, error):
    write(tmp_path, "a.yaml", f"id: a\nmax_turns: 1\nuser: Ask.\njudge: [{claim}]\n")
    with pytest.raises(ValueError, match=error):
        list(Scenarios(tmp_path))


@pytest.mark.parametrize(
    ("required", "passed", "threshold", "held", "failed", "accepted"),
    [
        ((False, False, False), (True, True, True), 1, 3, (), True),
        ((False, False, False), (True, True, False), 1, 2, (), False),
        ((True, False, False), (True, False, False), 1 / 3, 1, (), True),
        ((True, False, False), (True, True, False), 0.5, 2, (), True),
        ((True, False, False), (False, True, True), 0.5, 2, (1,), False),
        ((False, False, False), (True, True, False), 2 / 3, 2, (), True),
        ((False, False, False), (True, True, False), 0.667, 2, (), False),
        ((False, False, False), (False, False, False), 0, 0, (), True),
        ((True, True, True), (True, False, True), 0, 2, (2,), False),
        ((True, True, True), (False, False, False), 0, 0, (1, 2, 3), False),
    ],
)
def test_scoring_requires_mandatory_claims_and_the_unrounded_share_of_all_claims(
    required, passed, threshold, held, failed, accepted
):
    scenario = Scenario(
        "s", 1, "Ask.", tuple(Requirement(str(i), flag) for i, flag in enumerate(required))
    )
    score = scenario.score(Verdict(tuple(Claim(value) for value in passed)), threshold=threshold)
    assert (score.held, score.total, score.required_failed) == (held, 3, failed)
    assert score.fraction == held / 3
    assert score.threshold == threshold
    assert score.passed is accepted


def test_scoring_defaults_to_all_claims_and_accepts_missing_confidence():
    assert SCENARIO.score(Verdict((Claim(True),)), trust=1).passed
    assert not SCENARIO.score(Verdict((Claim(False),))).passed
    assert SCENARIO.score(Verdict((Claim(True),))).threshold == 1


async def test_the_judge_sees_only_requirement_texts_in_order():
    judge = FakeJudge((Claim(True), Claim(False)))
    scenario = Scenario("s", 1, "Ask.", (Requirement("one", True), Requirement("two")))
    result = await scenario.outcome(FakeAgent("hello"), Models(FakeModel("hi"), judge), 1, alone())
    assert judge.calls == [(result.transcript, ("one", "two"))]


@pytest.mark.parametrize("setting", ["trust", "threshold"])
@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan"), float("inf"), -float("inf")])
def test_direct_scoring_rejects_invalid_acceptance_settings(setting, value):
    with pytest.raises(ValueError, match="must be from 0 to 1"):
        SCENARIO.score(Verdict((Claim(True),)), **{setting: value})
