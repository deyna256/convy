# 3. One package: a library and a command

**Status:** Accepted

## Context

Agent files import convy's classes, so convy has to be installed where they run. Connecting an agent
and running scenarios should still be one command.

## Decision

Publish one package, `convy`, with the library and the `convy` command (`init`, `run`, `report`). The
command is a thin shell over the library. A user keeps agents, scenarios, the models convy uses and results in
a project of their own; `convy init` creates one from a template. A team can instead add convy as a
development dependency of its agent's repository and run it in CI.

## Alternatives

- **A command only, through `uvx`.** Agent files could not import convy.
- **A repository to clone.** Users would edit a copy of convy and lose updates.
- **Two packages, library and command.** Two releases to keep in step for no gain.

## Consequences

- Same model as pytest: a tool installed into the project it works on.
- Scenario files live in `scenarios/`, not `tests/`, so they are not confused with a project's tests.
