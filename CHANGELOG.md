# Changelog

Notable changes to this project. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[semantic versioning](https://semver.org/spec/v2.0.0.html). While the version is `0.x` the public API
may change in a minor release.

This file is built from fragments in `changelog.d/` when a release is made; see
[CONTRIBUTING.md](CONTRIBUTING.md#changelog). Do not edit it by hand.

<!-- towncrier release notes start -->

## [0.5.0] - 2026-10-20

### Added

- `convy compare --fail-on-regression` exits with 3 when the pass rate got worse and the change is not chance, so CI can fail the build. ([#33](https://github.com/deyna256/convy/issues/33))
- An agent can give the steps behind an answer: its thoughts and the calls it made, with when each call started, how long it took, its tokens and what it sent and received. The report shows them folded under the answer, the calls on a time line. ([#45](https://github.com/deyna256/convy/issues/45))

### Changed

- `Answer` takes `steps` instead of `thinking`: give the agent's thinking as a `Thought` among them. Runs are written in format 5; older runs still open in the report, with their thinking as a thought, but cannot be resumed. ([#45](https://github.com/deyna256/convy/issues/45))

### Removed

- `reviews_agent_thinking` is gone from `ChatJudge` and from the judge interface: a judge sees only what the user and the agent said. Remove the setting from `models.py` and from judges of your own. `Thinking` and `NoThinking` are gone too. ([#45](https://github.com/deyna256/convy/issues/45))


## [0.4.0] - 2026-10-20

### Added

- The agent, the simulated user and the judge each have their own limit on work at once, and each agent can have its own. Set them under `[tool.convy]` in `pyproject.toml`, or with `CONVY_AGENT_PARALLEL` and the like for one run. The judge no longer holds a conversation's place, `convy resume` can go on with other limits, and `convy compare` says when two runs had different agent limits. ([#38](https://github.com/deyna256/convy/issues/38))
- An agent, model or judge of one's own raises `Busy` when its service refuses a request because it is busy, and convy waits for it as for `JsonAgent` and `OpenAiModel`. `Bench` takes a `Patience`; OpenAI's `retry-after-ms` is read. ([#40](https://github.com/deyna256/convy/issues/40))
- The agent, the simulated user and the judge can each keep to a limit of requests per minute: `agent_per_minute`, `user_per_minute` and `judge_per_minute` under `[tool.convy]`, or `per_minute` in an agent's own table. convy spaces their requests evenly, so a known limit meets almost no 429; `convy compare` and `convy resume` say when the agent's limit per minute changed. ([#42](https://github.com/deyna256/convy/issues/42))

### Changed

- `RunSpec` and `Limits` take their fields by name only, so a call written for an older order fails instead of mixing them up. `FakeModel` and `FakeJudge` take a `delay` and count in `peak` the most calls under way at once, as `FakeAgent` does. ([#38](https://github.com/deyna256/convy/issues/38))

### Removed

- `--parallel` is gone: set `agent_parallel` under `[tool.convy]` in `pyproject.toml` instead. `Bench` and `RunSpec` take `limits=Limits(...)` instead of `parallel`, and runs are written in format 4; older runs are still read and resumed. ([#38](https://github.com/deyna256/convy/issues/38))
- `JsonEndpoint` no longer takes `pauses` and repeats nothing itself; `Retry-After` is no longer cut to 60 seconds. A service that cannot be reached now fails at once instead of being tried again. `Scenario.outcome` takes the agent's `Places`. ([#40](https://github.com/deyna256/convy/issues/40))

### Fixed

- Reports distinguish time per answer from total answer time, and pass-rate changes show their percentage-point unit. ([#7](https://github.com/deyna256/convy/issues/7))
- convy waits for a busy service up to 2 minutes, at least as long as it asks, with a random delay, and sends it fewer requests at once until it answers again. An agent whose service stays busy has no verdict and no longer lowers the pass rate; waiting is not counted in the time per answer. ([#40](https://github.com/deyna256/convy/issues/40))
- A pass-rate change under 10 percentage points shows one decimal, as times do: `1.5`, not `2`.


## [0.3.0] - 2026-10-12

### Added

- An agent can give its thinking apart from its answer: `Answer(text, usage, Thinking(...))`, and `Usage(input, output, thinking)` for the part of the output spent on thinking. The simulated user never sees the thinking, a judge sees it only if it reviews it, and the report shows it folded next to the answer. ([#1](https://github.com/deyna256/convy/issues/1))
- `convy run --fail-under 0.9` exits with 3 when an agent's pass rate is below 90%, so a CI job can fail a build whose results are not good enough. Errors still exit with 1. ([#9](https://github.com/deyna256/convy/issues/9))
- A judge can say how sure it is of each decision, and you can bring your own judge. `convy run --trust 0.8` leaves out the verdicts the judge is less sure of, and the report says how many were left out. ([#17](https://github.com/deyna256/convy/issues/17))
- A claim can be graded on its own grades, such as `[none, partial, full]` or `[1, 2, 3, 4, 5]`, with the worst grade that still passes. The report shows each grade, and the comparison shows when a claim got a step better or worse. ([#18](https://github.com/deyna256/convy/issues/18))
- The report pages have an icon, so a tab with a report is easy to find.

### Changed

- In Python, `RunSpec.changes` is now two methods: `code_changes(files, convy)` compares the files and the convy version, and `label_changes(version, user, judge)` compares the agent's version and the model names. ([#12](https://github.com/deyna256/convy/issues/12))
- The judge in `models.py` is now written `judge=ChatJudge(OpenAiModel(...))`, not `judge=OpenAiModel(...)`. Change that one line; convy stops with an error that says so until you do. ([#17](https://github.com/deyna256/convy/issues/17))
- A claim's reason is `Reason(text)` or `NoReason()`: write `Claim(True, Reason("ok"))`, or `Claim(True)` for none. `Reason` and `Thinking` refuse empty text. Run folders are written in format 3; runs written before are read as they were. ([#29](https://github.com/deyna256/convy/issues/29))
- convy prints paths relative to the folder it runs in, such as `results/index.html`, not from the root of the disk.

### Fixed

- New projects created by `convy init` install the same convy version as the command that created them, rather than the old 0.1 release. ([#3](https://github.com/deyna256/convy/issues/3))
- The compare page calls a change of pass rate real only when the attempts support it: an exact test that weighs each scenario by its attempts, so few scenarios, or scenarios that all changed alike, no longer count as real by themselves. ([#6](https://github.com/deyna256/convy/issues/6))
- Numbered lists in a dialogue show the numbers as written, also when text splits the list or a number is skipped or repeated. Numbers up to nine digits stay inside the bubble; longer numbers show as plain text. ([#8](https://github.com/deyna256/convy/issues/8))
- `convy resume` refuses a run that another version of convy started, and `convy compare` says when two runs were made by different versions of convy. ([#12](https://github.com/deyna256/convy/issues/12))
- `convy resume` refuses a run that another process is still playing, so the two no longer play the same attempts at once; a run whose process died resumes as before. ([#13](https://github.com/deyna256/convy/issues/13))
- convy's output is UTF-8 on Windows too, so `✓` and other characters no longer stop a run whose output goes to a pipe or a file. ([#16](https://github.com/deyna256/convy/issues/16))
- A run made from Python records the convy version that made it, as `convy run` already did; `RunSpec` fills it in. ([#24](https://github.com/deyna256/convy/issues/24))
- When the judge's model gives a null, missing or empty reason, the report says no reason was given instead of showing "None". A reply in the wrong shape now names the field that is wrong. ([#28](https://github.com/deyna256/convy/issues/28))


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
