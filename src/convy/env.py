"""Settings from `.env` and the environment."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Env(BaseSettings):
    """The base class for settings in a project's `models.py` and `agents/*.py`.

    It reads `.env` in the current directory and then the environment, ignores variables it does not
    declare, and cannot be changed after it is read. Its errors do not show the values read, since
    they may be keys.
    """

    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", frozen=True, hide_input_in_errors=True
    )
