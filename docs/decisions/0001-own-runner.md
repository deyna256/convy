# 1. Own runner instead of an evaluation framework and containers

**Status:** Accepted

## Context

convy grew out of a test bench built on [Inspect AI](https://inspect.aisi.org.uk/), Docker sandboxes and
Inspect's model bridge, with custom code on top. The goal is narrow: talk to an agent through a
simulated user, judge the dialogue, count the agent's tokens and time. Most of the framework went
unused, and parts of it worked against the goal:

- a `TimeoutError` in an agent was swallowed and the attempt counted as a success;
- one failed judge call cancelled the whole run until retries were configured;
- the simulated user and the judge needed a provider prefix and several flags to reach a custom gateway;
- the dialogue lived in sample metadata, and the agent's tokens had to be picked out of model events;
- the containers existed to give agents files and a model; corporate agents are already-running
  services that need neither.

## Decision

Write a small runner of our own, about a thousand lines, with no framework and no containers. The agent
is reached through an interface its owner implements (see [0002](0002-agent-interface.md)).

## Alternatives

- **Keep Inspect and work around it.** Every workaround above stays, and each Inspect release can break
  one.
- **Keep Docker agents next to service agents.** A second way to connect agents, a model proxy for
  counting their tokens, and container issues — for agents that can be run as services anyway.

## Consequences

- All behaviour is in code we own and can read in one sitting.
- No sandbox: scenarios that give the agent files wait for a file field on `Message`.
- No `inspect view`; convy's own report replaces it.
