from datetime import UTC, datetime

import msgspec
import pytest

from convy.agent import AgentFailure
from convy.bench import Bench, JsonlJournal, RunHeader
from convy.dialog import NoVerdict, Transcript, Verdict
from convy.fakes import FakeAgent, FakeModel, MemoryJournal
from convy.model import Models
from convy.scenario import Outcome, Scenario

MODELS = Models(user=FakeModel("hi"), judge=FakeModel('{"pass": true}'))
SCENARIOS = tuple(Scenario(name, 1, "Say hi.", ("greets",)) for name in ("a", "b"))
HEADER = RunHeader("bot", "1", "fake", "fake", 1, 2, datetime(2026, 10, 6, 14, 5, tzinfo=UTC))


async def test_every_scenario_is_played_attempts_times():
    journal = MemoryJournal()
    outcomes = await Bench(SCENARIOS, MODELS, attempts=3).run(FakeAgent("hello"), journal)
    assert [(o.scenario, o.attempt) for o in outcomes] == [
        ("a", 1),
        ("a", 2),
        ("a", 3),
        ("b", 1),
        ("b", 2),
        ("b", 3),
    ]
    assert sorted(journal.outcomes, key=lambda o: (o.scenario, o.attempt)) == list(outcomes)
    assert Bench(SCENARIOS, MODELS, attempts=3).planned() == 6


async def test_at_most_parallel_conversations_run_at_once():
    agent = FakeAgent("hello", delay=0.01)
    await Bench(SCENARIOS, MODELS, attempts=4, parallel=3).run(agent, MemoryJournal())
    assert agent.opened == 8
    assert agent.peak == 3


async def test_a_failed_attempt_does_not_stop_the_others():
    agent = FakeAgent(AgentFailure("down"))
    outcomes = await Bench(SCENARIOS, MODELS, attempts=2).run(agent, MemoryJournal())
    assert [o.stop for o in outcomes] == ["agent_failure"] * 4


@pytest.mark.parametrize(
    ("values", "error"),
    [({"attempts": 0}, "attempts must be at least 1, got 0"), ({"parallel": 0}, "parallel")],
)
def test_a_bench_rejects_values_it_cannot_run(values: dict[str, int], error: str):
    with pytest.raises(ValueError, match=error):
        Bench(SCENARIOS, MODELS, **values)


def outcome(verdict: Verdict | NoVerdict) -> Outcome:
    return Outcome("a", 1, ("greets",), Transcript(), verdict, "max_turns")


def test_jsonl_journal_writes_the_header_once_then_a_line_per_outcome(tmp_path):
    journal = JsonlJournal(tmp_path, HEADER)
    assert not journal.path().exists()
    journal.record(outcome(Verdict(True, "fine")))
    journal.record(outcome(NoVerdict("judge down")))
    assert journal.path() == tmp_path / "bot" / "2026-10-06T14-05-00.000000.jsonl"
    header, *lines = journal.path().read_bytes().splitlines()
    assert msgspec.json.decode(header, type=RunHeader) == HEADER
    assert [msgspec.json.decode(line, type=Outcome).verdict for line in lines] == [
        Verdict(True, "fine"),
        NoVerdict("judge down"),
    ]
