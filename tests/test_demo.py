"""The recorded demo stays usable when its journals are no longer supported."""

import json
import shutil
from pathlib import Path

import pytest

from convy.cli import main


def test_a_rejected_demo_rebuild_leaves_its_recordings_and_pages_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
):
    root = Path(__file__).parents[1]
    monkeypatch.syspath_prepend(str(root))
    from examples.shop.demo import Demo

    recorded = root / "examples" / "shop" / "results"
    results = shutil.copytree(recorded, tmp_path / "results")
    for path in results.glob("*/*/run.json"):
        path.write_text(json.dumps({**json.loads(path.read_bytes()), "format": 0}))
    before = {p.relative_to(results): p.read_bytes() for p in results.rglob("*") if p.is_file()}
    assert Path("index.html") in before
    assert Path("report.html") in before
    assert Path("compare.html") in before
    monkeypatch.chdir(tmp_path)

    def command(self: Demo, line: str, build: str | None = None) -> None:
        main(line.split())

    monkeypatch.setattr(Demo, "convy", command)
    with pytest.raises(SystemExit) as stopped:
        Demo(tmp_path).site()
    assert stopped.value.code == 2
    assert "unsupported run format" in capsys.readouterr().err
    assert {
        p.relative_to(results): p.read_bytes() for p in results.rglob("*") if p.is_file()
    } == before
