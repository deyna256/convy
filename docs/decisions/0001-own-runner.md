# 1. Run scenarios with convy's own test runner

**Status:** Accepted

## Context

The original test bench used [Inspect AI](https://inspect.aisi.org.uk/), Docker sandboxes and
Inspect's model bridge. It needed custom code to recover dialogues from sample metadata and agent
usage from model events. One agent timeout counted as a success, while one failed judge call
could stop the run. Connecting a custom model gateway also required several provider settings.

## Decision

convy runs the dialogue, records the agent's time and tokens, and asks a judge to evaluate the
result. The agent's owner supplies the [connection to the agent](0002-agent-interface.md).
An agent can already be running as a service.

## Alternatives and consequences

Keeping Inspect would tie those workarounds to its release cycle. Supporting Docker as a second
way to run agents would also require container setup and a model proxy to count tokens.

convy builds its own report. It provides no sandbox or file attachments for messages.
