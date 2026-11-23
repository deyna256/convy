# 2. Connect agents through a conversation interface

**Status:** Accepted

## Context

An agent might accept JSON over HTTP, stream responses, or require a multi-step login.
Teams need to test an existing service without deploying a wrapper for convy.

## Decision

The owner exports an `agent` object from `agents/<name>.py`. Its `conversation()` method opens an
async context manager. The conversation's `answer(message)` method takes a `Message` and returns
an `Answer` when awaited.

For a JSON API, configure `JsonAgent` with an endpoint, a request body template and paths to
the reply and token counts. For other protocols, implement the same interface. Opening and closing
the conversation gives the adapter a place to log in, reuse its client and release resources.

## Alternatives and consequences

A fixed HTTP contract would require changes to existing services. A YAML mapping could describe
simple requests but would still need an extension for streaming and logins. A single send
function would leave the caller responsible for session state and cleanup.

Agent files execute in convy's process and must come from a trusted source. convy also ships
working fakes for tests. See the [security policy](../../SECURITY.md).
