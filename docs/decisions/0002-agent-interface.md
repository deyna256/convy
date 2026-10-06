# 2. The agent's owner implements the agent interface

**Status:** Accepted

## Context

Agents come with every kind of API: JSON over HTTP with or without memory, streaming, two-step logins,
custom protocols. convy must connect all of them without knowing their code or model.

## Decision

An agent is any object with `conversation()`, which opens an async context giving a `Conversation`
with `async answer(Message) -> Answer`. The agent's owner writes `agents/<name>.py` with an `agent` object.
For the common case — JSON over HTTP — the library ships `JsonAgent`, configured with a URL, a body
template and paths to the reply and token counts, so no code is needed. Anything else is two small
classes in the same file.

## Alternatives

- **A fixed HTTP contract** that agents must serve. One adapter in convy, but every team has to deploy
  a wrapper service before it can test.
- **A YAML mapping only.** No code for simple APIs, but streaming and logins do not fit, and a second
  mechanism is needed anyway.
- **A function `send(session, history, text)`.** Simple, but it leaves lifecycle (login, client
  reuse, cleanup) to globals; a conversation object holds that state where it belongs.

## Consequences

- One way to connect any agent; `JsonAgent` is just one implementation of it.
- Agent files are Python and run in convy's process: they are trusted code (see the
  [security policy](../../SECURITY.md)).
- The library ships fakes of the interface, so owners can test their own agent classes.
