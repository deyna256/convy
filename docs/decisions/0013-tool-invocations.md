# 13. Count tool invocations only from complete call traces

**Status:** Accepted

## Context

A task can call the same tool repeatedly, retry a failed call, or call only a model. A trace's
names and token usage cannot reliably distinguish these cases. Steps are optional, so an empty
trace does not establish that no tools were called, and a partial trace would undercount them.

## Decision

Require each `Call` to declare `kind="model"` or `kind="tool"`. Keep completeness on the answer
as `steps_complete`, false by default: the agent explicitly asserts that it reported every call.
The [agent contract](../agents.md#steps) defines how to report these facts.

Derive tool counts in the report, following its [population and coverage rules](../report.md#tool-invocations).
Store and export only call kinds and completeness, not redundant totals. Partial traces remain
useful for inspection, but cannot supply a complete measurement. Strip both steps and completeness
before passing an answer to a judge, as [decision 10](0010-answer-steps.md) requires.

## Alternatives and consequences

- **Infer tools from names or token use.** Convenient, but model calls and tools can share either.
- **Treat unreported steps as zero, or total partial traces.** This rewards missing instrumentation.
- **Use only successful tasks.** This hides tool work spent on failures and ties resource metrics
  to the judge's result.

The Python `Call` constructor changes, and format 9 rejects older runs under
[decision 5](0005-runs.md). Completeness is the agent's assertion; convy cannot verify that its
trace covers all internal work. Work while opening or closing a conversation is outside an
answer's trace and this measurement.
