# claude-select 🔐

[![PyPI version](https://img.shields.io/pypi/v/claude-select)](https://pypi.org/project/claude-select/)
[![Python versions](https://img.shields.io/pypi/pyversions/claude-select)](https://pypi.org/project/claude-select/)
[![CI](https://github.com/Nomia/claude-select/actions/workflows/ci.yml/badge.svg)](https://github.com/Nomia/claude-select/actions/workflows/ci.yml)

[中文说明](./README.zh-CN.md)

`claude-select` is a local Claude auth registry and selector for people who use multiple Claude accounts on one machine.

It captures the current Claude CLI login state, stores each account as a snapshot in a local SQLite registry, shows expiry status in a table, and lets you:

- select one stored account back into Claude's live auth state for CLI use
- read one stored account from Python and build `env` for Claude Agent SDK use

It does **not** auto-refresh OAuth tokens. It trusts the captured `expiresAt` value and asks the user to log in again when an account is near expiry or expired.

## Install 🚀

```bash
pip install claude-select
```

## How Users Get Started 👇

### 1. Capture your accounts

Run the guided bootstrap:

```bash
claude-select init
```

By default, `claude-select` launches `claude` in the current terminal for each account capture.

For each account:

1. choose an alias such as `work` or `personal`
2. `claude-select` launches `claude`
3. inside the `claude` CLI session, run `/login` and finish authorization
4. exit `claude` and return to `claude-select`
5. press Enter so `claude-select` can capture the current login snapshot

You can add another account later:

```bash
claude-select add work
claude-select add personal
```

If you do not want `claude-select` to launch `claude` for you, use:

```bash
claude-select add work --no-launch
```

In that mode, `claude-select` will print guidance and wait while you run `claude` and `/login` yourself.

### 2. See what is stored

```bash
claude-select list
claude-select watch
```

Example table:

```text
Alias     Email             Status          Expires In  Last Selected
--------  ----------------  --------------  ----------  -------------
personal  a@example.com     healthy         18h 12m     2h ago
work      b@company.com     expiring_soon   1h 05m      -
team-a    c@company.com     expired         expired     3d ago
```

### 3. Select an account for Claude CLI

```bash
claude-select select work
```

This reads the stored snapshot from the local registry and writes it back into Claude's current live auth backend:

- macOS: Keychain + Claude config
- Linux / Windows: Claude credentials file + Claude config

### 4. Use an account in Python

```python
from claude_select import AuthManager
from claude_code_sdk import ClaudeAgentOptions, query

manager = AuthManager()
env = manager.build_sdk_env("work")

options = ClaudeAgentOptions(env=env)

async for message in query(prompt="analyze this repo", options=options):
    print(message)
```

The Python side reads from the same local registry, but it does **not** mutate Claude's live auth state.

## CLI Commands 🧰

```bash
claude-select init
claude-select add <alias>
claude-select relogin <alias>
claude-select list
claude-select watch
claude-select select [alias]
claude-select remove <alias>
claude-select export-env <alias> --json
claude-select current
```

Command behavior:

- `init`: guided multi-account bootstrap
- `add`: launch `claude` in the current terminal by default, then capture the current login into the registry
- `relogin`: launch `claude` in the current terminal by default, then overwrite one stored alias after the user logs in again
- `list`: show the current registry table
- `watch`: keep refreshing the table in the terminal
- `select`: write one stored snapshot back into Claude's live auth state
- `remove`: delete one stored account
- `export-env`: print SDK env vars for one alias
- `current`: show the last alias selected for CLI use

## Python API 🐍

Minimal usage:

```python
from claude_select import AuthManager

manager = AuthManager()

accounts = manager.list_accounts()
details = manager.get_account("work")
env = manager.build_sdk_env("work")
auth_payload = manager.export_sdk_auth("work")
```

Current public surface:

```python
class AuthManager:
    def list_accounts(self) -> list[dict]: ...
    def get_account(self, alias: str): ...
    def capture_current_account(self, alias: str, overwrite: bool = True) -> dict: ...
    def relogin_account(self, alias: str) -> dict: ...
    def remove_account(self, alias: str) -> None: ...
    def select_account(self, alias: str) -> dict: ...
    def build_sdk_env(self, alias: str, base_env: dict[str, str] | None = None) -> dict[str, str]: ...
    def export_sdk_auth(self, alias: str) -> dict: ...
    def current_alias(self) -> str | None: ...
    def render_table(self) -> str: ...
```

Top-level helper:

```python
from claude_select import build_sdk_env

env = build_sdk_env("work")
```

## How Expiry Works ⏳

`claude-select` does not refresh tokens automatically.

It only reads the stored `expiresAt` timestamp and derives status from it:

- `healthy`: more than 6 hours remain
- `expiring_soon`: 6 hours or less remain
- `expired`: already expired
- `unknown`: no `expiresAt` value was captured

When an account is expired:

- `select` fails
- `build_sdk_env()` fails
- the user should log in again and run:

```bash
claude-select relogin <alias>
```

## Storage Model 🗃️

The registry is stored locally in SQLite:

- macOS / Linux default:
  - `~/.config/claude-select/registry.db`
- custom XDG config root:
  - `$XDG_CONFIG_HOME/claude-select/registry.db`

Each stored account contains:

- alias
- email
- organization name / id
- account uuid
- captured time
- expiry time
- last selected time
- stored Claude `oauthAccount`
- stored Claude `claudeAiOauth` credentials payload

Claude's own live state remains separate:

- global Claude config
- Claude credentials file or macOS Keychain

The registry is the source of truth. `select` copies one stored snapshot back into Claude's live state.

## Current Limitations ⚠️

- This project currently centers on captured Claude OAuth snapshots.
- It does not auto-refresh tokens.
- It relies on the structure of Claude's current local auth state.
- Expiry monitoring is local-only; it does not call a remote validation API.
- Selecting an account updates the local machine's active Claude login state.

## Development 🛠️

Install dev dependencies:

```bash
pip install -e .[dev]
```

Run checks:

```bash
ruff check .
ruff format --check .
mypy
pytest
python -m build
python -m twine check dist/*
```

## License 📄

MIT
