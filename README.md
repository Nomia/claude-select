# claude-select 🔐

[![PyPI version](https://img.shields.io/pypi/v/claude-select)](https://pypi.org/project/claude-select/)
[![Python versions](https://img.shields.io/pypi/pyversions/claude-select)](https://pypi.org/project/claude-select/)
[![CI](https://github.com/Nomia/claude-select/actions/workflows/ci.yml/badge.svg)](https://github.com/Nomia/claude-select/actions/workflows/ci.yml)

[中文说明](./README.zh-CN.md)

![claude-select overview](https://raw.githubusercontent.com/Nomia/claude-select/main/docs/images/claude-select-overview.png)

`claude-select` is a local Claude auth registry and selector for people who use multiple Claude accounts on one machine.

It captures the current Claude CLI login state, stores each account as a snapshot in a local SQLite registry, shows expiry status in a table, and lets you:

- select one stored account back into Claude's live auth state for CLI use
- store long-lived tokens for SDK/program use
- read one stored entry from Python and build `env` for Claude Agent SDK use

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
6. look for a success block that confirms the account was saved and shows the current registry

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

After CLI account capture, `init` can also walk you through `claude setup-token` so you can add a long-lived token for SDK/program usage.

### What `init` looks like

```bash
$ claude-select init
Claude account bootstrap
Add accounts one by one. Complete /login for each account before capture.

Alias (blank to finish): work
Launching `claude` in this terminal.
Inside Claude, run `/login` and finish account authorization.
When login is complete, exit Claude to return here.
Press Enter after login is complete...
Captured work <a@company.com> [Team A].
Status: healthy
Expires in: 7h 57m

Current registry:
Alias  Kind  Email            Organization  Status   Expires In  Last Selected
-----  ----  ---------------  ------------  -------  ----------  -------------
work   cli   a@company.com    Team A        healthy  7h 57m      -
Add another account? [Y/n] y

Alias (blank to finish): personal
Launching `claude` in this terminal.
Inside Claude, run `/login` and finish account authorization.
When login is complete, exit Claude to return here.
Press Enter after login is complete...
Captured personal <b@gmail.com> [Personal].
Status: healthy
Expires in: 7h 59m

Current registry:
Alias     Kind  Email            Organization  Status   Expires In  Last Selected
--------  ----  ---------------  ------------  -------  ----------  -------------
personal  cli   b@gmail.com      Personal      healthy  7h 59m      -
work      cli   a@company.com    Team A        healthy  7h 57m      -
Add another account? [Y/n] n
```

### What `add` looks like

```bash
$ claude-select add work
Launching `claude` in this terminal.
Inside Claude, run `/login` and finish account authorization.
When login is complete, exit Claude to return here.
Press Enter after login is complete...
Captured work <a@company.com> [Team A].
Status: healthy
Expires in: 7h 57m

Current registry:
Alias  Kind  Email            Organization  Status   Expires In  Last Selected
-----  ----  ---------------  ------------  -------  ----------  -------------
work   cli   a@company.com    Team A        healthy  7h 57m      -
```

### What `add-token` looks like

```bash
$ claude-select add-token work-sdk
Launching `claude setup-token` in this terminal.
Complete authorization. When the token is printed, copy it and return here.
Detected the long-lived token from setup-token output.
Validated token successfully.
Detected account metadata:
  email: a@company.com
  organization: Team A
Captured [token] work-sdk <a@company.com> [Team A].
Status: healthy
Expires in: 8759h 59m

Current registry:
Alias     Kind   Email            Organization  Status   Expires In   Last Selected
--------  -----  ---------------  ------------  -------  -----------  -------------
work-sdk  token  a@company.com    Team A        healthy  8759h 59m    -
```

### 2. See what is stored

```bash
claude-select list
claude-select list --usage
claude-select whoami
claude-select watch
```

Example table:

```text
Alias     Kind   Email             Organization    Status          Expires In  Last Selected
--------  -----  ----------------  --------------  --------------  ----------  -------------
personal  cli    a@example.com     Personal        healthy         18h 12m     2h ago
work      cli    b@company.com     Team A          expiring_soon   1h 05m      -
work-sdk  token  b@company.com     Team A          healthy         8759h 59m   -
```

### 3. Select an account for Claude CLI

```bash
claude-select select work
```

This reads the stored snapshot from the local registry and writes it back into Claude's current live auth backend:

- macOS: Keychain + Claude config
- Linux / Windows: Claude credentials file + Claude config

Example:

```bash
$ claude-select select work
Selected work <a@company.com> [Team A].
Updated Claude live auth state:
  - config: /Users/you/.claude.json
  - credentials store: macOS Keychain
Current CLI alias: work

$ claude-select whoami
Current Claude live account
  matched alias: work
  email: a@company.com
  organization: Team A
  expires in: 7h 54m
  5h quota left: 76.0%
  5h resets in: 3h 12m
  7d quota left: 59.0%
  7d resets in: 2d 4h
```

### 4. Use an account in Python

```python
from claude_select import AuthManager
from claude_code_sdk import ClaudeAgentOptions, query

manager = AuthManager()
env = manager.build_sdk_env("work")
auto_env = manager.build_sdk_env_auto()

options = ClaudeAgentOptions(env=env)

async for message in query(prompt="analyze this repo", options=options):
    print(message)
```

The Python side reads from the same local registry, but it does **not** mutate Claude's live auth state.

If you store multiple long-lived token entries with `add-token`, you can let `claude-select` auto-pick the best SDK token before each call:

```python
from claude_select import AuthManager

manager = AuthManager()
env = manager.build_sdk_env_auto()
```

`build_sdk_env_auto()` only considers `token` entries, checks their cached 5h / 7d quota state, and chooses the best available token before returning an env mapping.

The automatic switch happens when your program asks `claude-select` to build the SDK env. In practice, that means the decision is made immediately before each Claude Agent SDK call that uses `build_sdk_env_auto()`. It does not run as a background daemon, and it does not switch tokens in the middle of an already-running Claude request.

Current rules:

- only `token` entries participate
- any token already at `100%` on its 5h or 7d window is skipped
- among the remaining tokens, the one with the most 5h quota left wins first, then the most 7d quota left
- usage data is cached for 60 seconds, so repeated SDK calls reuse recent quota state instead of fetching it every time

Minimal pattern:

```python
from claude_select import AuthManager
from claude_code_sdk import ClaudeAgentOptions, query

manager = AuthManager()
env = manager.build_sdk_env_auto()
options = ClaudeAgentOptions(env=env)

async for message in query(prompt="summarize this repository", options=options):
    print(message)
```

Full Python SDK guide:

- [Python SDK Guide](./docs/python-sdk.md)

## CLI Commands 🧰

```bash
claude-select init
claude-select add <alias>
claude-select add-token <alias>
claude-select relogin <alias>
claude-select list
claude-select watch
claude-select select [alias]
claude-select sync-current
claude-select remove <alias>
claude-select export-env <alias> --json
claude-select current
claude-select whoami
```

Command behavior:

- `init`: guided multi-account bootstrap
- `add`: launch `claude` in the current terminal by default, then capture the current login into the registry
- `add-token`: launch `claude setup-token` in the current terminal by default, then store a long-lived token for SDK/program use
- `relogin`: launch `claude` in the current terminal by default, then overwrite one stored alias after the user logs in again
- `list`: show the current registry table and do a light sync of the current live account first
- `list --usage`: fetch and display 5h / 7d quota information for each stored alias
- `watch`: keep a live Rich-powered view of the current Claude live account plus the local registry and quota data, with periodic live-state sync
- `select`: write one stored snapshot back into Claude's live auth state
- `sync-current`: read Claude's current live auth state and sync any refreshed token data back into the matching registry entry
- `remove`: delete one stored account
- `export-env`: print SDK env vars for one alias
- `current`: show the last alias selected for CLI use
- `whoami`: show Claude's current live auth state, matched alias, and current quota summary after a light sync

## Python API 🐍

Minimal usage:

```python
from claude_select import AuthManager

manager = AuthManager()

accounts = manager.list_accounts()
accounts_with_usage = manager.list_accounts(include_usage=True)
details = manager.get_account("work")
env = manager.build_sdk_env("work")
sdk_env = manager.build_sdk_env("work-sdk")
auto_env = manager.build_sdk_env_auto()
auth_payload = manager.export_sdk_auth("work")
live_quota = manager.get_live_quota()
account_quota = manager.get_account_quota("work")
all_quotas = manager.list_account_quotas()
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
    def pick_sdk_account(self, preferred_alias: str | None = None) -> dict: ...
    def build_sdk_env_auto(self, preferred_alias: str | None = None, base_env: dict[str, str] | None = None) -> dict[str, str]: ...
    def export_sdk_auth(self, alias: str) -> dict: ...
    def get_live_quota(self) -> dict: ...
    def get_account_quota(self, alias: str) -> dict: ...
    def list_account_quotas(self) -> list[dict]: ...
    def current_alias(self) -> str | None: ...
    def render_table(self) -> str: ...
```

Top-level helper:

```python
from claude_select import build_sdk_env

env = build_sdk_env("work")
```

Top-level auto-selection helper:

```python
from claude_select import build_sdk_env_auto

env = build_sdk_env_auto()
```

Quota responses are cached locally for 60 seconds. `watch`, `whoami`, and repeated SDK calls reuse that cache instead of hitting the remote usage endpoint on every refresh.

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
