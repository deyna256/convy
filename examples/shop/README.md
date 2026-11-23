# The shop demo

Build 1.0 of a support bot follows the shop's refund, delivery and replacement policies.
Build 1.1 shortened the prompt and lost those instructions. The demo records both builds
answering the same scenarios.

- [Build 1.1 report](https://deyna256.github.io/convy/report.html)
- [Historical comparison of builds 1.0 and 1.1](https://deyna256.github.io/convy/compare.html)

The HTML in `results/` opens as saved. These recordings use an older journal format.
GitHub Pages publishes their existing reports. To see the current report layout, record new runs.

## Run it yourself

From the repository root, copy the example settings and fill in your OpenAI-compatible gateway
URL and key.

```sh
cd examples/shop
cp .env.example .env
```

After editing `.env`, run both builds:

```sh
SHOP_BOT_BUILD=1.0 uv run --project ../.. convy run shop_bot -k 3
SHOP_BOT_BUILD=1.1 uv run --project ../.. convy run shop_bot -k 3
```

Open `results/index.html` to compare the new runs. For a terminal verdict, use
`uv run --project ../.. convy compare BASELINE CANDIDATE` with the two run IDs printed above.

## Record the demo and GIF

From the repository root, run `just demo`. This needs `uv`,
[VHS](https://github.com/charmbracelet/vhs#installation), `ttyd`, `ffmpeg`, `ffprobe` and
`examples/shop/.env`. After confirmation it replaces the demo results, calls the gateway for
both builds, rebuilds the pages and writes `docs/assets/demo.gif`.

If the demo folder already contains exactly two current-format runs, `just demo-site` rebuilds
their pages without calling the gateway. If you publish new recordings, update the public links
above and in the repository README.
