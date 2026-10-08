# Changelog

Notable changes to this project. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[semantic versioning](https://semver.org/spec/v2.0.0.html). While the version is `0.x` the public API
may change in a minor release.

This file is built from fragments in `changelog.d/` when a release is made; see
[CONTRIBUTING.md](CONTRIBUTING.md#changelog). Do not edit it by hand.

<!-- towncrier release notes start -->

## [0.2.0] - 2026-10-08

### Added

- Scenarios are found in folders under `scenarios/` at any depth, not only in `scenarios/` itself. Ids stay unique across all folders.
- The judge decides each claim of a scenario on its own, with a reason, and the report shows which claim failed. An attempt in which the agent failed is `Failed` rather than judged.
- `convy compare <before> <after>` writes a page that puts two runs side by side: each tile before and after with its change, the scenarios grouped as worse, better, same or not compared, and both dialogues of a scenario next to each other.
- `convy resume <run>` continues a run stopped by Ctrl+C with exactly the settings it started with, and refuses when the agent or the models changed. An interrupted run exits with code 130.

### Changed

- Each run is a folder, `results/<agent>/<run id>/`, with a copy of the scenarios it played, its settings and its status. Results of convy 0.1 are not read; run the agents again. In Python, `RunJournal` and `RunSpec` replace `JsonlJournal` and `RunHeader`, and `Outcome` no longer holds the claims.
- Every run has its own report in its folder: five tiles (pass rate with the count, stable scenarios, answer time, tokens, errors), each scenario as Failing, Flaky, Passing or No verdict, and a window with the judge's decision per claim and the dialogue; `results/index.html` lists every run. In Python, `Report` takes one run, and `Comparison` and `Index` are new.


## [0.1.0] - 2026-10-07

### Added

- The first release: connect an agent with `JsonAgent` or two small classes, play YAML scenarios with a simulated user and a judge, and compare pass rate, tokens and response time in a static HTML report — from the `convy` command or from Python.
