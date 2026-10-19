"""What every test shares: a clean environment, whatever the shell running the tests has set."""

import os

import pytest


@pytest.fixture(autouse=True)
def no_convy_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove the `CONVY_*` variables of the shell, which set the limits of a run."""
    for name in [name for name in os.environ if name.upper().startswith("CONVY_")]:
        monkeypatch.delenv(name)
