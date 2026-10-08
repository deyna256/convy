"""The shop demo: its pages, and a way to make it again.

python demo.py site     build the pages from the two runs in results/
python demo.py record   play both builds for real, record the GIF, then build the pages
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

GIF = Path(__file__).parents[2] / "docs" / "assets" / "demo.gif"
TOOLS = ("uv", "vhs", "ttyd", "ffmpeg", "ffprobe")
LEAD = '<!doctype html><meta http-equiv="refresh" content="0; url={0}"><a href="{0}">{0}</a>\n'


class Demo:
    """The demo project in a folder: two runs of shop_bot, build 1.0 then 1.1."""

    def __init__(self, folder: Path):
        self.folder = folder

    def site(self) -> None:
        """The reports, the index and the comparison, with report.html and compare.html at the
        site's root leading to the newer run and to the comparison: the README links those."""
        before, after = self.runs()
        self.convy("report")
        self.convy(f"compare {before} {after}")
        results = self.folder / "results"
        newer = next((results / "shop_bot").glob(f"*_{after}"))
        (results / "report.html").write_text(LEAD.format(f"shop_bot/{newer.name}/report.html"))
        (results / "compare.html").write_text(LEAD.format(f"compare/{before}-vs-{after}.html"))

    def record(self) -> None:
        missing = [tool for tool in TOOLS if shutil.which(tool) is None]
        if missing:
            sys.exit(
                f"missing: {', '.join(missing)}\n"
                "vhs, with ttyd and ffmpeg: https://github.com/charmbracelet/vhs#installation"
            )
        if not (self.folder / ".env").is_file():
            sys.exit("examples/shop/.env is missing: copy .env.example there and fill it in")
        shutil.rmtree(self.folder / "results", ignore_errors=True)
        try:
            self.convy("run shop_bot -k 3", build="1.0")
            self.run("vhs demo.tape")  # build 1.1, played while it is recorded
            before, after = self.runs()
            tape = (self.folder / "compare.tape").read_text()
            with tempfile.NamedTemporaryFile("w", suffix=".tape", dir=self.folder) as compare:
                compare.write(tape.replace("BEFORE AFTER", f"{before} {after}"))
                compare.flush()
                self.run("vhs", compare.name)
            self.gif()
        finally:
            for video in ("run.mp4", "compare.mp4"):
                (self.folder / video).unlink(missing_ok=True)
        self.site()

    def gif(self) -> None:
        """Join the two recordings. The run's wait plays 7 times faster; its first 3 s and its
        last 2.4 s, with the paths of the report, play as they were."""
        length = self.output("ffprobe -v error -show_entries format=duration -of csv=p=0 run.mp4")
        end = float(length) - 2.4
        steps = (
            "[0:v]trim=0:3,setpts=PTS-STARTPTS[start]",
            f"[0:v]trim=3:{end},setpts=(PTS-STARTPTS)/7[wait]",
            f"[0:v]trim={end},setpts=PTS-STARTPTS[end]",
            "[1:v]trim=0.3,setpts=PTS-STARTPTS[compare]",
            "[start][wait][end][compare]concat=n=4,fps=12,split[a][b]",
            "[a]palettegen=max_colors=64:stats_mode=diff[palette]",
            "[b][palette]paletteuse=dither=none:diff_mode=rectangle",
        )
        filters = ";".join(steps)
        self.run("ffmpeg -v error -y -i run.mp4 -i compare.mp4 -filter_complex", filters, str(GIF))

    def runs(self) -> tuple[str, str]:
        """The random parts of the two runs' ids, the older first."""
        folders = sorted(path.name for path in (self.folder / "results" / "shop_bot").iterdir())
        if len(folders) != 2:
            sys.exit(f"examples/shop must hold two runs of shop_bot; found {len(folders)}")
        before, after = (name.rpartition("_")[2] for name in folders)
        return before, after

    def convy(self, line: str, build: str | None = None) -> None:
        env = os.environ | {"SHOP_BOT_BUILD": build} if build else None
        self.run(f"uv run --project ../.. convy {line}", env=env)

    def run(self, line: str, *args: str, env: dict[str, str] | None = None) -> None:
        """Run a command line, split on spaces, with `args` added as they are."""
        subprocess.run([*line.split(), *args], cwd=self.folder, env=env, check=True)

    def output(self, line: str) -> str:
        done = subprocess.run(line.split(), cwd=self.folder, check=True, capture_output=True)
        return done.stdout.decode()


if __name__ == "__main__":
    steps = {"site": Demo.site, "record": Demo.record}
    if len(sys.argv) != 2 or sys.argv[1] not in steps:
        sys.exit(__doc__)
    try:
        steps[sys.argv[1]](Demo(Path(__file__).parent))
    except subprocess.CalledProcessError as error:
        sys.exit(f"failed: {' '.join(error.cmd)}")
