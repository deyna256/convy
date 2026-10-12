import asyncio
import errno
import subprocess
import sys
import time
from datetime import UTC, datetime

import msgspec
import pytest

from convy.agent import AgentFailure
from convy.bench import (
    CONVY,
    Bench,
    Files,
    Finished,
    Interrupted,
    RunFile,
    RunInUse,
    RunJournal,
    Running,
    RunSpec,
)
from convy.dialog import ChatJudge, Claim, NoVerdict, Transcript, Verdict
from convy.fakes import FakeAgent, FakeModel, MemoryJournal
from convy.model import Models
from convy.scenario import Outcome, Scenario

MODELS = Models(user=FakeModel("hi"), judge=ChatJudge(FakeModel('{"claims": [{"pass": true}]}')))
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


async def test_a_run_another_process_plays_is_not_played_or_written(tmp_path):
    journal = RunJournal(tmp_path, SPEC)
    journal.create()
    journal.write(Interrupted(STARTED))
    journal.record(outcome(NoVerdict("down")))
    agent = FakeAgent("hello")
    with journal.held(), pytest.raises(RunInUse, match="is being played by another process"):
        await journal.play(Bench(SCENARIOS, MODELS), agent, journal)
    assert agent.opened == 0
    assert status(journal) == Interrupted(STARTED)
    assert len(lines(journal)) == 1


HOLDER = """
import sys
import time
from pathlib import Path

import msgspec

from convy.bench import RunFile, RunJournal

folder = Path(sys.argv[1])
file = msgspec.json.decode((folder / "run.json").read_bytes(), type=RunFile)
with RunJournal(folder.parent.parent, file.spec).held():
    print("held", flush=True)
    time.sleep(60)
"""


async def test_a_run_whose_process_died_is_played(tmp_path):
    journal = RunJournal(tmp_path, SPEC)
    journal.create()
    with subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(journal.folder())], stdout=subprocess.PIPE, text=True
    ) as holder:
        try:
            out = holder.stdout
            assert out is not None
            assert out.readline() == "held\n"
            with pytest.raises(RunInUse), journal.held():
                pass
        finally:
            holder.kill()  # as a crash would end it, without a word
    deadline = time.monotonic() + 5  # Windows frees a dead process's locks soon, not at once
    while True:
        try:
            with journal.held():
                break
        except RunInUse:
            assert time.monotonic() < deadline, "the lock outlived its process"
            time.sleep(0.05)
    await journal.play(Bench(SCENARIOS, MODELS, 2), FakeAgent("hello"), journal)
    assert isinstance(status(journal), Finished)


async def test_a_file_system_without_locks_plays_as_before(tmp_path, monkeypatch):
    def no_locks(*args: object) -> None:
        raise OSError(errno.ENOLCK, "No locks available")

    monkeypatch.setattr(
        "convy.bench.msvcrt.locking" if sys.platform == "win32" else "convy.bench.fcntl.flock",
        no_locks,
    )
    journal = RunJournal(tmp_path, SPEC)
    journal.create()
    await journal.play(Bench(SCENARIOS, MODELS, 2), FakeAgent("hello"), journal)
    assert isinstance(status(journal), Finished)


def test_a_run_unchanged_has_no_reasons_to_stop():
    assert SPEC.code_changes(Files(), CONVY) == ()
    assert SPEC.label_changes("1", "fake", "fake") == ()


@pytest.mark.parametrize(
    ("files", "convy", "reason"),
    [
        (Files(agent="new"), CONVY, "agents/bot.py changed since the run started"),
        (Files(models="new"), CONVY, "models.py changed since the run started"),
        (Files(), "9.9.9", f"convy is 9.9.9, the run started on {CONVY}"),
    ],
)
def test_changed_code_is_a_reason_not_to_resume(files: Files, convy: str, reason: str):
    assert SPEC.code_changes(files, convy) == (reason,)


def test_a_run_that_does_not_say_its_convy_is_not_resumed():
    spec = msgspec.structs.replace(SPEC, convy="")
    reason = f"convy is {CONVY}, the run does not say which convy started it"
    assert spec.code_changes(Files(), CONVY) == (reason,)


@pytest.mark.parametrize(
    ("now", "reason"),
    [
        (("2", "fake", "fake"), "the agent's version is '2', the run has '1'"),
        (("1", "gpt", "fake"), "the user model is 'gpt', the run has 'fake'"),
        (("1", "fake", "gpt"), "the judge model is 'gpt', the run has 'fake'"),
    ],
)
def test_a_changed_label_is_a_reason_not_to_resume(now: tuple[str, str, str], reason: str):
    assert SPEC.label_changes(*now) == (reason,)


@pytest.mark.parametrize("trust", [-0.5, 1.5])
def test_a_run_spec_rejects_a_trust_outside_0_to_1(trust: float):
    with pytest.raises(ValueError, match="trust must be from 0 to 1"):
        RunSpec("r", "bot", "1", "fake", "fake", 2, 4, 600, SCENARIOS, STARTED, trust=trust)


def test_an_old_run_file_reads_with_trust_0():
    old = msgspec.json.decode(msgspec.json.encode(RunFile(2, SPEC, Running())))
    del old["spec"]["trust"]  # a run.json written before trust existed
    assert msgspec.json.decode(msgspec.json.encode(old), type=RunFile).spec.trust == 0
