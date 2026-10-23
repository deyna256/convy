# 11. A run is the result; tables are its flat form

**Status:** Accepted

## Context

The result of a benchmark is a `Run`: its specification, its status, and every attempt with its
dialogue, answers, tokens, steps and the judge's decisions. Only convy's report used it. pandas,
polars and DuckDB need flat tables, tools without Python could not read a run at all, and the rules
behind the report's numbers were not all written down, so a user's own number could differ from
convy's.

Others keep a run whole and give flat views of it. Inspect AI keeps an `EvalLog` and gives
dataframes as projections of it, one row per unit
([Inspect](https://inspect.aisi.org.uk/dataframe.html)). Kimball declares the grain of each table,
starts at the atomic grain and leaves ratios to the query
([Kimball](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/grain/)).
In tidy data each kind of observational unit forms a table
([Wickham](https://vita.had.co.nz/papers/tidy-data.pdf)). One domain can have several
presentations that know about it
([Fowler](https://martinfowler.com/bliki/PresentationDomainSeparation.html)). promptfoo, Braintrust
and hyperfine export CSV and JSON.

## Decision

- **The result of a benchmark is a `Run`**, and it stays as it is: it holds the data and computes
  nothing new. The report, comparisons, the index, the tables and the user's code are consumers of
  it.
- **Tables are its flat, complete form:** one table for each kind of object, one row for each
  object. They compute nothing and drop nothing. The rules of the report's numbers are written once,
  in [The report](../report.md#tiles), so anyone can compute them from the tables.
- **JSON Lines is the complete export; CSV is for spreadsheets.** CSV cannot keep `""` apart from a
  missing value for every reader, nor the type of a value.
- **Columns are kept.** A column may be added at any time. Renaming or removing one is a breaking
  change, said in the changelog.
- **No `--format` or `--to` yet.** Which format a tool needs cannot be guessed, and both are cheap.
  Files always in `results/export/` are where the docs and scripts look, and an export never
  replaces files elsewhere. Either flag can be added later without breaking anything.

## Alternatives

- **Tables of the report's numbers.** A second place that computes them, and not complete.
- **Making the pages' view records public.** They are page details and change with the pages.
- **Dataframes in convy.** A dependency for what a list of dicts gives pandas and polars.

## Consequences

- A run can be read from Python, pandas, polars, DuckDB or a spreadsheet, and its numbers computed
  as the report does.
- The tables' columns are a durable format, next to the run's folder ([0005](0005-runs.md)).
