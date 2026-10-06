# 4. Runtime dependencies: httpx2, msgspec, yamlrocks, pydantic-settings

**Status:** Accepted

## Context

convy needs an async HTTP client, immutable typed classes, YAML parsing with validation, and typed
settings from the environment and the command line. Each dependency is a long-term cost.

## Decision

- **[httpx2](https://pydantic.dev/docs/httpx2/)** for HTTP. It is Pydantic's continuation of httpx with
  the same API, including `MockTransport` for tests. httpx itself has seen almost no maintenance since
  November 2024 and closed its issue tracker in February 2026; the OpenAI SDK has moved to httpx2.
- **[msgspec](https://msgspec.dev)** for every class: frozen `Struct`s, validation of scenarios with
  `msgspec.convert`, and the journal with `msgspec.json`. Tagged unions let `Usage | NoUsage` and
  `Verdict | NoVerdict` be written and read back without type checks in convy's code.
- **[yamlrocks](https://pypi.org/project/yamlrocks/)** for YAML. It implements YAML 1.2 (no `no` →
  `False` surprise), is safe by default and passes the official YAML test suite. It is alpha, so it is
  pinned to `>=0.6,<0.7` and called in one place.
- **[pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)** for the
  environment, `.env` and the command line. `SecretStr` keeps keys out of output.

## Alternatives

- **httpx**: unmaintained. **aiohttp**, **niquests**: a different API and no transport for tests.
- **dataclasses**, **attrs**: no built-in validation or JSON. **pydantic** everywhere: works, but
  classes holding `Protocol`-typed fields need `arbitrary_types_allowed`, and msgspec is lighter.
- **PyYAML**: YAML 1.1. **ruamel.yaml**: slow and awkward.
- **msgspec-based settings libraries** (msgspec-ext, msgspec-config, msgspec-settings): alpha or beta,
  one maintainer each. Settings are read once per run, so msgspec's speed does not matter there.
- **python-dotenv** with `os.environ`: untyped, and a missing variable is a bare `KeyError`.

## Consequences

- Two libraries describe data, with a clear split: pydantic at the edges (environment, command line),
  msgspec everywhere else.
- If yamlrocks fails us, replacing it is a one-line change in `Scenarios`.
