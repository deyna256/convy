# Run the test suite.
test:
    uv run pytest

# Run the test suite and report which lines of src/convy it did not reach.
cov:
    uv run pytest --cov=convy --cov-report=term-missing

# Check formatting, style and import order. Changes nothing; this is what CI runs.
lint:
    uv run ruff format --check .
    uv run ruff check .

# Fix what can be fixed: formatting first, then the style fixes ruff makes on its own.
format:
    uv run ruff format .
    uv run ruff check --fix .

# Check types in the library and the tests.
type:
    uv run ty check

# Build the wheel and source distribution into dist/.
build:
    uv build

# Show the changelog entry the next release will get, from the fragments in changelog.d/.
changelog:
    uv run towncrier build --draft --version "$(uv version --short)"

# Move the fragments into CHANGELOG.md under the version in pyproject.toml. Run before a release.
release-notes:
    uv run towncrier build --yes --version "$(uv version --short)"
