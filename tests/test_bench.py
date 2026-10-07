import asyncio
from datetime import UTC, datetime

import msgspec
import pytest

from convy.agent import AgentFailure
from convy.bench import Bench, Files, Finished, Interrupted, RunFile, RunJournal, Running, RunSpec
from convy.dialog import Claim, NoVerdict, Transcript, Verdict
from convy.fakes import FakeAgent, FakeModel, MemoryJournal
from convy.model import Models
from convy.scenario import Outcome, Scenario

MODELS = Models(user=FakeModel("hi"), judge=FakeModel('{"claims": [{"pass": true}]}'))
SCENARIOS = tuple(Scenario(name, 1, "Say hi.", ("greets",)) for name in ("a", "b"))
STARTED = datetime(2026, 10, 6, 14, 5, tzinfo=UTC)
SPEC = RunSpec(
    "2026-10-06T14-05-00_a3f9", "bot", "1", "fake", "fake", 2, 4, 600, SCENARIOS, STARTED
)


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


def outcome(verdict: Verdict | NoVerdict, scenario: str = "a") -> Outcome:
    return Outcome(scenario, 1, Transcript(), verdict, "max_turns")


def status(journal: RunJournal) -> object:
    return msgspec.json.decode((journal.folder() / "run.json").read_bytes(), type=RunFile).status


def lines(journal: RunJournal) -> list[bytes]:
    return (journal.folder() / "attempts.jsonl").read_bytes().splitlines()


async def test_only_the_attempts_not_done_are_played():
    outcomes = await Bench(SCENARIOS, MODELS, attempts=2).run(
        FakeAgent("hello"), MemoryJournal(), done=frozenset({("a", 1), ("b", 2)})
    )
    assert [(o.scenario, o.attempt) for o in outcomes] == [("a", 2), ("b", 1)]


def test_a_spec_lists_every_attempt_of_the_run():
    assert SPEC.pairs() == (("a", 1), ("a", 2), ("b", 1), ("b", 2))


def test_a_new_run_gets_its_folder_and_never_overwrites_one(tmp_path):
    journal = RunJournal(tmp_path, SPEC)
    journal.create()
    assert journal.folder() == tmp_path / "bot" / "2026-10-06T14-05-00_a3f9"
    file = msgspec.json.decode((journal.folder() / "run.json").read_bytes(), type=RunFile)
    assert file == RunFile(2, SPEC, Running())
    assert not (journal.folder() / "run.json.tmp").exists()
    with pytest.raises(FileExistsError):
        journal.create()


def test_attempts_are_appended_a_line_each(tmp_path):
    journal = RunJournal(tmp_path, SPEC)
    journal.create()
    journal.record(outcome(Verdict((Claim(True, "fine"),))))
    journal.record(outcome(NoVerdict("judge down")))
    assert [msgspec.json.decode(line, type=Outcome).verdict for line in lines(journal)] == [
        Verdict((Claim(True, "fine"),)),
        NoVerdict("judge down"),
    ]


def test_an_attempt_after_a_line_cut_short_starts_on_a_new_line(tmp_path):
    journal = RunJournal(tmp_path, SPEC)
    journal.create()
    (journal.folder() / "attempts.jsonl").write_bytes(b'{"scenario": "a", "att')
    journal.record(outcome(NoVerdict("down")))
    cut, written = lines(journal)
    assert cut == b'{"scenario": "a", "att'
    assert msgspec.json.decode(written, type=Outcome) == outcome(NoVerdict("down"))


async def test_a_played_run_is_finished(tmp_path):
    journal = RunJournal(tmp_path, SPEC)
    journal.create()
    outcomes = await journal.play(Bench(SCENARIOS, MODELS, 2), FakeAgent("hello"), journal)
    assert len(outcomes) == len(lines(journal)) == 4
    assert isinstance(status(journal), Finished)


class Broken:
    """A journal that fails, as a bug in convy would."""

    def record(self, outcome: Outcome) -> None:
        raise RuntimeError("disk full")


async def test_a_run_stopped_by_an_error_is_interrupted_and_keeps_its_attempts(tmp_path):
    journal = RunJournal(tmp_path, SPEC)
    journal.create()
    journal.record(outcome(NoVerdict("down")))
    with pytest.raises(ExceptionGroup):
        await journal.play(Bench(SCENARIOS, MODELS), FakeAgent("hello"), Broken())
    assert isinstance(status(journal), Interrupted)
    assert len(lines(journal)) == 1


async def test_a_cancelled_run_is_interrupted(tmp_path):
    journal = RunJournal(tmp_path, SPEC)
    journal.create()
    playing = asyncio.create_task(
        journal.play(Bench(SCENARIOS, MODELS), FakeAgent("hello", delay=10), journal)
    )
    await asyncio.sleep(0.01)
    playing.cancel()  # what asyncio.run does on Ctrl+C
    with pytest.raises(asyncio.CancelledError):
        await playing
    assert isinstance(status(journal), Interrupted)


def test_a_run_unchanged_has_no_reasons_to_stop():
    assert SPEC.changes("1", "fake", "fake", Files()) == ()


@pytest.mark.parametrize(
    ("now", "reason"),
    [
        (("2", "fake", "fake"), "the agent's version is '2', the run has '1'"),
        (("1", "gpt", "fake"), "the user model is 'gpt', the run has 'fake'"),
        (("1", "fake", "gpt"), "the judge model is 'gpt', the run has 'fake'"),
    ],
)
def test_a_changed_version_or_model_is_a_reason_not_to_resume(now: tuple[str, str, str], reason):
    assert SPEC.changes(*now, Files()) == (reason,)
