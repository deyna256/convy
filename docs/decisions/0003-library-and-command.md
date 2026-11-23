# 3. Ship the library and command in one package

**Status:** Accepted

## Decision

Install `convy` in the project that defines the agents. The command uses the same library that
agent files import. `convy init` copies the project template. A team can also use convy as a
development dependency in an existing repository.

## Alternatives and consequences

An isolated CLI installation would leave the agent's environment without the library.
Asking users to clone and edit convy would make upgrades harder. Separate CLI and library
packages would require coordinating two releases.

The project's evaluation scenarios live in `scenarios/`, separate from its own test suite.
