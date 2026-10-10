# Contributing to convy

Use plain English in issues, commits, documentation and code comments. Follow
[ARCHITECTURE.md](ARCHITECTURE.md) for how the code is laid out and the rules it keeps, and the
[Code of Conduct](CODE_OF_CONDUCT.md) when working with others.

## No signatures

Do not add generated-by lines, tool attribution footers or similar signatures anywhere: not in commits,
pull requests, reviews, comments, issues, documentation or code.

## Issues

Check for an existing issue before opening one. Give each issue one clear outcome and a short title
that describes the problem or intended change.

Report a security vulnerability privately, as the [security policy](SECURITY.md) describes, not in an issue.

Use the [issue template](.github/ISSUE_TEMPLATE/issue.md), which has these sections:

- **Problem:** explain what happens today and what is missing or wrong. For a bug, include reproduction
  steps, expected and actual behaviour, and the versions of Python and `convy`, and the kind of agent
  and models in use.
- **Why it matters:** describe the effect on users or development. Explain why the work is useful
  without repeating the problem.
- **Done when:** list observable results that will make the task complete, including the tests or
  checks needed to verify them.

Keep the issue self-contained. Add examples, relevant links and scope limits when useful. Separate
agreed behaviour from proposals; do not invent implementation details to fill out the description.
Keep credentials and private dialogue text out of examples, journals and logs.

Give each issue one type label: `bug`, `feature`, `maintenance`, `docs` or `question`. Add `ci` for CI
and developer tooling, and `good first issue` for small, self-contained tasks. Close duplicates and
declined issues with the matching close reason instead of a label.

## Branches

For issue work, branch from `main` and use only the issue number as the branch name. For issue #1:

```sh
git switch main
git switch -c 1
```

Use `1`, not `issue-1`, `feature/1` or a descriptive suffix. Keep the branch focused on its issue.

Work without an issue — repository setup, a typo, a dependency bump — uses a short descriptive branch
name instead, such as `changelog-typo`.

## Commits

For issue work, use one line in this format:

```text
#<issue number>: <change>
```

Examples:

```text
#1: add the agent contract test
#1: test that a missing reply path fails the turn
```

Use a short English description that starts with an action, such as `add`, `fix` or `test`. Describe
the change, not the work session. Put longer explanations in the issue or pull request.

Work without an issue uses the same one line without the number:

```text
add the pull request template
```

Do not add a commit body, co-author lines, sign-off trailers or any other [signature](#no-signatures).
Git still records the normal author and committer metadata. Keep unrelated changes out of the commit and
inspect the staged diff before committing.

Add the [changelog fragment](#changelog) in the same commit as the change it describes.

## Checks

Use the commands in the [Justfile](Justfile):

| command | what it does |
|---|---|
| `just test` | runs the test suite |
| `just cov` | runs the test suite and reports the lines of `src/convy` it did not reach |
| `just lint` | checks formatting, style and import order, changing nothing |
| `just format` | formats the code and applies the fixes ruff can make on its own |
| `just type` | checks types |
| `just build` | builds the wheel and source distribution |
| `just changelog` | shows the next release's changelog entry, changing nothing |
| `just release-notes` | moves the fragments into CHANGELOG.md; the Release workflow runs it |

Run `just format` first and `just lint` after it. `just format` fixes what it can; whatever `just lint`
still reports needs a person.

Run the relevant checks before submitting changes. Documentation-only changes need link and formatting
checks, not tests.

The [CI workflow](.github/workflows/ci.yml) runs `just lint` and `just type` once and `just test` on
Python 3.12, 3.13 and 3.14, for pull requests to `main` and pushes to `main`. It fails when `uv.lock`
is out of date.

[Dependabot](.github/dependabot.yml) opens a pull request once a month with updated dependencies in
`uv.lock`, and another with new versions of the GitHub Actions; CI checks them like any other.

## Tests

- Tests live in `tests/` and must not call a real model or a real agent: use the fakes in
  `convy.fakes` and `httpx2.MockTransport`. To try convy on real models, use a project created with
  `convy init`.
- Test through the public interface. A test that needs a private attribute means the class has the
  wrong shape.
- `Agent`, `Model` and `Judge` each have a contract test that the real implementation and its fake
  both pass. A new implementation of one joins that test.
- Async tests need no marker (`asyncio_mode = "auto"`). A test that runs longer than 30 seconds fails
  (pytest-timeout).
- Use time-machine to set the current date and time. It leaves `time.monotonic` alone, so asyncio
  works as usual; durations in tests use short real waits.

## Changelog

[CHANGELOG.md](CHANGELOG.md) is built at release time by [towncrier](https://towncrier.readthedocs.io/)
from fragments in `changelog.d/`, so pull requests never conflict on it. Do not edit CHANGELOG.md by hand.

A change that users can notice adds one fragment: a file named `<issue>.<type>.md`, with one or two
sentences written for users. Types are `added`, `changed`, `deprecated`, `removed`, `fixed` and
`security`. For issue #12:

```sh
uv run towncrier create 12.fixed.md --content 'Respect `Retry-After` when it is a date.'
```

Work without an issue uses `+<name>.<type>.md`, for example `+docs-typo.fixed.md`. Changes users cannot
notice — tests, CI, refactoring — need no fragment. `just changelog` shows what the next release's
entry will look like.

## Releases

Releases are made by hand, from the Actions tab:

1. Raise the version with `uv version X.Y.Z` (it updates `pyproject.toml` and `uv.lock`) and merge
   that change to `main`.
2. Run the **Release** workflow on `main`. It runs the CI checks, moves the fragments from
   `changelog.d/` into [CHANGELOG.md](CHANGELOG.md) with `just release-notes` and commits that to
   `main`, then builds the packages from that commit, signs where they came from and creates a GitHub
   release whose text is the version's changelog entry. It refuses another branch, a version that is
   already released, and a release with no fragments in `changelog.d/`.
3. Run the **Publish** workflow with the release's tag, for example `v0.1.0`. It uploads the release's
   packages to PyPI unchanged. It uses PyPI trusted publishing, so no PyPI token is stored anywhere.

## Pull requests

Use the [pull request template](.github/pull_request_template.md) with these sections:

- **Problem:** explain what is missing or wrong and why the change is needed.
- **Changes:** describe the resulting behaviour and the decisions needed to review it.
- **Validation:** state which checks passed or could not run, and what behaviour the tests cover.

Keep each section short and avoid repeating the issue or listing every changed file. Add sections only
when needed, such as migration steps or breaking changes. Link the issue; use `Closes #<number>` when
the PR completes it. Update the description and affected documentation when the code changes. Do not
[sign](#no-signatures) the description.

Open the pull request as a draft while the work is in progress. When it is ready, mark it ready for review
and request a review from [@deyna256](https://github.com/deyna256) or another maintainer. Do this again after you address
the review's findings, so the reviewer knows the pull request is ready for another look.

## Reviews

Review the change as submitted, against the issue and the [review checklist](#review-checklist). State facts: what the code does, what follows
from it, and what you ran. Do not restate the diff or guess at intent; ask instead.

Put every code-anchored finding in an inline comment on the line it concerns and keep the review body
for the verdict and for anything that spans files. Mark a finding that is not blocking with one of
these prefixes:

- **Nit:** small or stylistic; the author may skip it.
- **Question:** you need an answer before you can judge the code.

Everything else blocks the merge until it is resolved.

Use these sections in the review body, and omit a section with nothing in it:

- **Summary:** one sentence on what the change does and whether it is ready.
- **Blocking:** one item per problem, each with `file:line`, the consequence and a concrete fix or check.
- **Non-blocking:** nits, questions and follow-ups worth recording.
- **Checked:** the commands you ran and anything you could not verify.

Request changes only when a finding is blocking. Approve when the rest are nits and say which ones you
expect to be handled. Take work outside the scope of the pull request to a separate issue and link it
instead of growing the review. Do not [sign](#no-signatures) the review or its comments.

### Review checklist

- The code keeps the [invariants](ARCHITECTURE.md#invariants), or the pull request explains why not.
- Every new public name is in `__all__`.
- Errors say what failed and where; no key or private text reaches output.
- New behaviour has a test; a new interface has a fake and, where a test can check its promises, a
  contract test.
- `just lint`, `just type` and `just test` pass.
- A change users can notice has a [changelog fragment](#changelog).

## Documentation

Keep shared documentation in Markdown. Distinguish planned behaviour from what the code implements.

| document | covers |
|---|---|
| [README](README.md) | what convy is and how to start; short, every link absolute so PyPI shows it |
| [docs/](docs/) | how to use convy: agents, scenarios, runs, the report, Python |
| [ARCHITECTURE.md](ARCHITECTURE.md) | how the code is laid out and the rules it keeps |
| [CONTRIBUTING.md](CONTRIBUTING.md) | how to propose, make and review a change |
| [docs/decisions/](docs/decisions/) | why the main choices were made |
| [CHANGELOG.md](CHANGELOG.md) | what changed in each release, built from `changelog.d/` |

Use short ADRs in `docs/decisions/` for significant decisions: status, context, decision, and
alternatives with consequences. Include sources when they explain the choice. This follows
[Nygard's ADR guidance](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).

New decisions are **Proposed** until agreed. **Accepted** does not mean implemented. Update decisions to
match the agreed design. Remove obsolete records and fix their references; do not maintain an archive of
superseded designs. Git retains the history. Do not renumber surviving ADRs to fill gaps.

Update affected docs and links in the same change. Give each rule one home; other docs and LLM
instructions should link there rather than copy it.

### Local working documents

Use `.local/` at the repository root for research, drafts and development plans; for example,
`.local/research/` and `.local/plans/`. Git ignores this directory. Do not commit it or force-add its
contents.

Move accepted decisions and their essential reasons into shared documentation. Local proposals do not
become requirements without agreement. Shared docs must not require or link to local notes: a fresh
clone must contain everything needed to understand and work on the project.
