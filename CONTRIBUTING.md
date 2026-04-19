# Contributing

## Development Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e ".[dev]"
```

## Local Checks

Run all checks before opening a pull request:

```bash
ruff check .
ruff format --check .
mypy
python3 -m pytest
python3 -m build
python3 -m twine check dist/*
```

## Scope

- Keep the CLI thin and push behavior into testable library code.
- Prefer explicit data models over loose dict mutation in public-facing flows.
- Do not weaken token handling or file permission behavior without discussion.

## Testing

- Add or update unit tests for any user-visible behavior change.
- Preserve coverage at or above the configured threshold.
- When fixing a bug, add a regression test first where practical.

## Pull Requests

- Keep changes focused.
- Update `README.md` when behavior or public APIs change.
- Add a `CHANGELOG.md` entry under `Unreleased` for notable user-facing changes.

