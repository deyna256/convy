# The shop demo

A support bot for a made-up shop, in two builds. Build 1.1 cut the prompt to save tokens and lost the
shop's rules on the way. convy shows it got worse.

- [The 1.1 run's report](https://deyna256.github.io/convy/shop_bot/2026-10-08T14-38-03_5e85/report.html)
- [1.0 and 1.1 compared](https://deyna256.github.io/convy/compare/7ad8-vs-5e85.html)

The runs in `results/` are real. CI builds the pages from them with `just demo-site`.

## Run it yourself

You need an OpenAI-compatible gateway. Copy `.env.example` to `.env` and fill it in.

```sh
cd examples/shop
SHOP_BOT_BUILD=1.0 uv run --project ../.. convy run shop_bot -k 3
SHOP_BOT_BUILD=1.1 uv run --project ../.. convy run shop_bot -k 3
uv run --project ../.. convy compare <1.0 run> <1.1 run>
```

## Record the GIF

`demo.tape` plays build 1.1, `compare.tape` compares the runs. Both need
[vhs](https://github.com/charmbracelet/vhs). Then join them, with the wait sped up:

```sh
vhs demo.tape && vhs compare.tape
ffmpeg -i run.mp4 -i compare.mp4 -filter_complex "\
[0:v]trim=0:3,setpts=PTS-STARTPTS[a];[0:v]trim=3:END,setpts=(PTS-STARTPTS)/7[b];\
[0:v]trim=END,setpts=PTS-STARTPTS[c];[1:v]trim=0.3,setpts=PTS-STARTPTS[d];\
[a][b][c][d]concat=n=4:v=1,fps=12,split[x][y];[x]palettegen=max_colors=64:stats_mode=diff[p];\
[y][p]paletteuse=dither=none:diff_mode=rectangle" ../../docs/assets/demo.gif
```

`END` is the length of `run.mp4` minus 2.4 seconds, so the last screen stays still.
