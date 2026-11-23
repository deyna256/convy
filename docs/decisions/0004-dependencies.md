# 4. Runtime dependencies

**Status:** Accepted

## Decision

- **[httpx2](https://pydantic.dev/docs/httpx2/)** sends async HTTP requests. Its httpx-style
  API includes `MockTransport` for testing requests without a server.
- **[msgspec](https://msgspec.dev)** provides frozen records, validates scenario data and reads
  and writes run journals. Tagged records distinguish results such as `Verdict`, `Failed` and
  `NoVerdict` when decoding JSON.
- **[yamlrocks](https://pypi.org/project/yamlrocks/)** reads scenario YAML. Under YAML 1.2 an
  unquoted `no` stays a string. Only the scenario loader uses the parser. While it is in alpha,
  the [dependency range](../../pyproject.toml) excludes untested minor releases.
- **[pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)** reads
  typed settings from environment variables, `.env` files and CLI arguments. Key fields use
  `SecretStr` to mask their values in settings output.

## Alternatives

- Keeping httpx raised maintenance concerns when we chose the client. aiohttp and niquests
  would have required changes to both the client and its test setup.
- Dataclasses and attrs would need separate validation and JSON handling. Using Pydantic for
  domain records would require extra configuration for fields typed as protocols.
- PyYAML uses YAML 1.1 rules. We preferred yamlrocks to ruamel.yaml for its simpler API.
- Reading settings with python-dotenv and `os.environ` would leave type checks and missing-value
  errors to convy. The msgspec-based settings libraries we considered were still in alpha or beta.
