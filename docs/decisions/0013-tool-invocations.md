# 13. Count tool calls from complete traces

**Status:** Accepted

## Context

An agent can call the same tool several times, retry a failed call, or call only a model.
A call name or a token count cannot reliably distinguish a model from a tool. An empty list
of steps could mean the agent made no calls or that it reported none.

## Decision

Every `Call` declares `kind="model"` or `kind="tool"`. The answer sets `steps_complete=True`
when it records every call. The flag defaults to false. See [Agent steps](../agents.md#steps).

The journal and export store these fields. The report counts tool calls only for tasks with
at least one recorded answer and complete traces for every answer. A complete trace with no
tool calls counts as zero. Partial traces remain available for inspection. Before judging, convy removes the trace and clears the
completeness flag, as described in [decision 10](0010-answer-steps.md). See [tool coverage](../report.md#tool-invocations).

## Alternatives and consequences

Inferring tools from names or tokens would misclassify calls. Counting partial traces would
make agents that report fewer steps appear more efficient. Restricting the count to successful
tasks would hide work spent on failures.

The measurement relies on the agent's account of work during each answer. It excludes work
when opening or closing a conversation. The change added a required kind to the Python
`Call` constructor and introduced [run format 9](0005-runs.md).
