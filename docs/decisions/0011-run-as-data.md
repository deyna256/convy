# 11. Export run data as tables

**Status:** Accepted

## Context

The report reads a `Run` with its specification, status, attempts, dialogues and decisions.
Users also need those observations in pandas, polars, DuckDB and spreadsheets. Without a
documented counting rule, two users can compute different pass rates from the same run.

## Decision

Keep the run folder as the source for reports and exports. Export seven tables, one each for
runs, scenarios, claims, attempts, decisions, answers and steps. Each row represents one
observation or definition. Users can calculate statistics from these rows using the
[report's counting rules](../report.md#tiles).

This follows [tidy data](https://vita.had.co.nz/papers/tidy-data.pdf) and
[Kimball's guidance](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/grain/)
to define what one row represents. [Inspect](https://inspect.aisi.org.uk/dataframe.html) also
provides table views of saved evaluations.

Write both CSV and JSON Lines to `results/export/`. JSON Lines preserves field types and
distinguishes empty strings from missing values. CSV is convenient for spreadsheets, where a
reader may treat both values as blank.

## Alternatives and consequences

- Exporting only report totals would discard the observations needed for other analyses.
  Exporting the page's internal data would tie consumers to the current layout.
- Returning native dataframes would add a runtime dependency. Python callers can pass the
  table records directly to their chosen library.
- A fixed output directory makes exports easy to locate. Both formats are inexpensive to
  generate, so the command needs no format selector.
- Consumers can rely on the documented columns. Adding a column is compatible; removing or
  renaming one requires a breaking-change notice. See [Results](../results.md).
