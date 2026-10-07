import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx2
import msgspec
import pytest
from pydantic_settings import SettingsConfigDict

from convy.agent import AgentFailure, Answer, Usage
from convy.bench import RunJournal, RunSpec
from convy.dialog import Claim, Failed, NoVerdict, Verdict
from convy.env import Env
from convy.fakes import EchoConversation, FakeAgent, FakeModel
from convy.http import JsonEndpoint, Tls
from convy.model import ModelFailure, Models, OpenAiModel
from convy.report import Runs
from convy.scenario import Matching, Outcome, Scenario, Scenarios

SCENARIO = Scenario(id="greet", max_turns=2, instructions="Say hi.", claims=("greets",))
PASS = '{"claims": [{"pass": true, "reason": "fine"}]}'


def models(*user: str | ModelFailure, judge: str | ModelFailure = PASS) -> Models:
    return Models(user=FakeModel(*user), judge=FakeModel(judge))


async def test_turns_run_out():
    outcome = await SCENARIO.outcome(
        FakeAgent(Answer("hello", Usage(3, 4))), models("hi"), attempt=1
    )
    assert outcome.stop == "max_turns"
    assert outcome.verdict == Verdict((Claim(True, "fine"),))
    assert [t.answer.usage for t in outcome.transcript.turns] == [Usage(3, 4)] * 2
    assert all(t.seconds >= 0 for t in outcome.transcript.turns)
    assert (outcome.scenario, outcome.attempt) == ("greet", 1)


async def test_the_user_finishes():
    outcome = await SCENARIO.outcome(FakeAgent("hello"), models("hi", "###STOP###"), attempt=1)
    assert outcome.stop == "user_stop"
    assert len(outcome.transcript.turns) == 1


@pytest.mark.parametrize("error", [AgentFailure("down"), KeyError("bug")])
async def test_a_failed_turn_fails_the_attempt_without_the_judge(error: Exception):
    judge = FakeModel(PASS)
    used = Models(user=FakeModel("hi"), judge=judge)
    outcome = await SCENARIO.outcome(FakeAgent("hello", error), used, attempt=1)
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

    outcome = await SCENARIO.outcome(Agent(), models("hi"), attempt=1)
    assert outcome.stop == "agent_failure"
    assert "the answer is not a valid Answer" in outcome.transcript.turns[-1].answer.text
    msgspec.json.decode(msgspec.json.encode(outcome), type=Outcome)  # the journal can read it


async def test_an_agent_that_cannot_open_a_conversation_fails():
    class Closed:
        def conversation(self):
            raise ConnectionError("no session")

    outcome = await SCENARIO.outcome(Closed(), models("hi"), attempt=1)
    assert outcome.stop == "agent_failure"
    assert outcome.verdict == Failed("[agent error: ConnectionError: no session]")


@pytest.mark.parametrize(
    "used", [models(ModelFailure("user down")), models("hi", judge=ModelFailure("judge down"))]
)
async def test_a_failed_model_leaves_no_verdict(used: Models):
    outcome = await SCENARIO.outcome(FakeAgent("hello"), used, attempt=1)
    assert outcome.stop == "model_failure"
    assert isinstance(outcome.verdict, NoVerdict)


class Buggy:
    name = "buggy"

    async def reply(self, messages: list[dict[str, str]]) -> str:
        raise KeyError("choices")


@pytest.mark.parametrize(
    "used",
    [
        Models(user=Buggy(), judge=FakeModel(PASS)),
        Models(user=FakeModel("hi", "###STOP###"), judge=Buggy()),
    ],
)
async def test_a_bug_in_a_model_is_a_model_failure(used: Models):
    outcome = await SCENARIO.outcome(FakeAgent("hello"), used, attempt=1)
    assert outcome.stop == "model_failure"
    assert outcome.verdict == NoVerdict("buggy: KeyError: 'choices'")


async def test_a_judge_answer_without_a_verdict_leaves_no_verdict():
    outcome = await SCENARIO.outcome(FakeAgent("hello"), models("hi", judge="Looks fine."), 1)
    assert outcome.stop == "model_failure"
    assert outcome.verdict == NoVerdict("the judge did not answer with JSON: Looks fine.")


async def test_a_judge_reply_that_cannot_be_encoded_leaves_no_verdict(tmp_path):
    verdict = '{"claims": [{"pass": true, "reason": "\ud83d"}]}'  # half an emoji
    content = json.dumps({"choices": [{"message": {"content": verdict}}]}).encode()
    service = httpx2.MockTransport(lambda request: httpx2.Response(200, content=content))
    judge = OpenAiModel(JsonEndpoint("https://llm.test", transport=service), "gpt")
    used = Models(user=FakeModel("hi", "###STOP###"), judge=judge)
    outcome = await SCENARIO.outcome(FakeAgent("hello"), used, attempt=1)
    assert outcome.stop == "model_failure"
    started = datetime(2026, 10, 6, tzinfo=UTC)
    spec = RunSpec("run", "bot", "", "fake", "gpt", 1, 1, 600, (SCENARIO,), started)
    journal = RunJournal(tmp_path, spec)
    journal.create()
    journal.record(outcome)
    (run,) = Runs(tmp_path)
    assert run.outcomes == (outcome,)


async def test_a_judge_with_a_broken_tls_leaves_no_verdict():
    endpoint = JsonEndpoint("https://llm.test/chat/completions", tls=Tls(ca="/missing.pem"))
    used = Models(user=FakeModel("hi", "###STOP###"), judge=OpenAiModel(endpoint, "gpt"))
    outcome = await SCENARIO.outcome(FakeAgent("hello"), used, attempt=1)
    assert outcome.stop == "model_failure"
    assert isinstance(outcome.verdict, NoVerdict)
    assert "/missing.pem" in outcome.verdict.error


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
    outcome = await SCENARIO.outcome(Agent(), models("hi"), attempt=1)
    assert outcome.stop == "agent_failure"
    assert "url" in str(outcome.verdict)
    assert b"sk-SECRET123" not in msgspec.json.encode(outcome)


def write(directory, name: str, text: str) -> None:
    (directory / name).write_text(text, encoding="utf-8")


def test_scenarios_are_read_from_yaml(tmp_path):
    write(tmp_path, "a.yaml", "id: a\nmax_turns: 3\nuser: |\n  Say no.\njudge:\n  - no\n")
    assert list(Scenarios(tmp_path)) == [Scenario("a", 3, "Say no.\n", ("no",))]


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("id: a\nmax_turns: 3\nuser: x\njudge: [y]\nworkspace: z\n", "unknown field `workspace`"),
        ("id: a\nmax_turns: 3\nuser: x\n", "missing required field `judge`"),
        ("id: a\nmax_turns: 0\nuser: x\njudge: [y]\n", "max_turns must be at least 1, got 0"),
        ("id: a\nmax_turns: 3\nuser: x\njudge: []\n", "judge must list at least one claim"),
        ("id: [a\n", "a.yaml"),
    ],
)
def test_a_wrong_scenario_names_the_file_and_the_problem(tmp_path, text: str, error: str):
    write(tmp_path, "a.yaml", text)
    with pytest.raises(ValueError, match=error):
        list(Scenarios(tmp_path))


@pytest.mark.parametrize(
    ("max_turns", "claims", "error"),
    [(0, ("y",), "max_turns must be at least 1"), (1, (), "judge must list at least one claim")],
)
def test_a_scenario_rejects_values_it_cannot_play(max_turns: int, claims: tuple, error: str):
    with pytest.raises(ValueError, match=error):
        Scenario("a", max_turns, "x", claims)


def test_scenario_ids_are_unique(tmp_path):
    for name in ("a.yaml", "b.yaml"):
        write(tmp_path, name, "id: same\nmax_turns: 1\nuser: x\njudge: [y]\n")
    with pytest.raises(ValueError, match="already has the id 'same'"):
        list(Scenarios(tmp_path))


def test_matching_keeps_scenarios_by_mask():
    scenarios = [SCENARIO, Scenario("refund-late", 1, "x", ("y",))]
    assert [s.id for s in Matching(scenarios, "refund-*")] == ["refund-late"]
    with pytest.raises(ValueError, match="no scenario matches 'nope'"):
        list(Matching(scenarios, "nope"))


def test_a_fingerprint_changes_with_what_the_scenario_asks_not_with_its_id():
    same = Scenario("other-id", 2, "Say hi.", ("greets",))
    assert SCENARIO.fingerprint() == same.fingerprint()
    assert len(SCENARIO.fingerprint()) == 8
    for changed in (
        Scenario("greet", 3, "Say hi.", ("greets",)),
        Scenario("greet", 2, "Say hello.", ("greets",)),
        Scenario("greet", 2, "Say hi.", ("greets", "is brief")),
    ):
        assert changed.fingerprint() != SCENARIO.fingerprint()
