"""The README's examples run as written."""

import re
from pathlib import Path

import pytest

import convy

README = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")


def test_run_from_python_example_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    section = README[README.index("## Run from Python") :]
    found = re.search(r"```python\n(.*?)```", section, re.DOTALL)
    assert found is not None
    monkeypatch.chdir(tmp_path)
    exec(found[1], {})
    page = (tmp_path / "results" / "index.html").read_text(encoding="utf-8")
    assert '"id":"echo"' in page
    assert (tmp_path / "results" / "echo" / "first" / "run.json").is_file()


def test_running_from_python_is_public_api():
    names = {"Bench", "Scenario", "Scenarios", "Matching", "Outcome", "Verdict", "NoVerdict"}
    names |= {"Claim", "Failed", "Transcript", "Turn", "Journal", "RunJournal", "RunSpec"}
    names |= {"Files", "Running", "Finished", "Interrupted", "Run", "Runs", "Report"}
    assert names <= set(convy.__all__)
    assert all(hasattr(convy, name) for name in convy.__all__)
