# The shop demo

A support bot for a made-up shop, in two builds. Build 1.1 cut the prompt to save tokens and lost
the shop's rules on the way. convy shows it got worse.

- [The 1.1 run's report](https://deyna256.github.io/convy/report.html)
- [Historical comparison of 1.0 and 1.1](https://deyna256.github.io/convy/compare.html)

The runs in `results/` are real historical recordings. Their standalone HTML pages still open,
but their run format predates the current reader. Rebuilding them with the current convy requires
new recordings. CI publishes the committed HTML pages, including the comparison page from the
older release.
`just demo-site` rebuilds pages only after new runs have been recorded in the supported format.

## Run it yourself

You need an OpenAI-compatible gateway. Copy `.env.example` to `.env` and fill it in.

```sh
cd examples/shop
SHOP_BOT_BUILD=1.0 uv run --project ../.. convy run shop_bot -k 3
SHOP_BOT_BUILD=1.1 uv run --project ../.. convy run shop_bot -k 3
uv run --project ../.. convy compare <1.0 run> <1.1 run>
```

With fresh runs, open `results/index.html` for the runs workspace. The `compare` command prints
the two-run verdict in the terminal.

## Make the demo again

From the repository's root:

```sh
just demo
```

It asks first, then checks that `uv`, [vhs](https://github.com/charmbracelet/vhs#installation),
`ttyd`, `ffmpeg` and `.env` are there. It plays build 1.0, records build 1.1 with `demo.tape`,
records the comparison with `compare.tape`, and joins them into `docs/assets/demo.gif`. Then it
builds the workspace and run reports. When publishing new recordings, update links to the
historical demo alongside the runs, pages and GIF. The steps are in `demo.py`.
