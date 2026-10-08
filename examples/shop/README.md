# The shop demo

A support bot for a made-up shop, in two builds. Build 1.1 cut the prompt to save tokens and lost
the shop's rules on the way. convy shows it got worse.

- [The 1.1 run's report](https://deyna256.github.io/convy/report.html)
- [1.0 and 1.1 compared](https://deyna256.github.io/convy/compare.html)

The runs in `results/` are real. CI builds the pages from them with `just demo-site`.

## Run it yourself

You need an OpenAI-compatible gateway. Copy `.env.example` to `.env` and fill it in.

```sh
cd examples/shop
SHOP_BOT_BUILD=1.0 uv run --project ../.. convy run shop_bot -k 3
SHOP_BOT_BUILD=1.1 uv run --project ../.. convy run shop_bot -k 3
uv run --project ../.. convy compare <1.0 run> <1.1 run>
```

## Make the demo again

From the repository's root:

```sh
just demo
```

It asks first, then checks that `uv`, [vhs](https://github.com/charmbracelet/vhs#installation),
`ttyd`, `ffmpeg` and `.env` are there. It plays build 1.0, records build 1.1 with `demo.tape`,
records the comparison with `compare.tape`, and joins them into `docs/assets/demo.gif`. Then it
builds the pages. Commit the new runs and the GIF; the README's links need no change. The steps
are in `demo.py`.
