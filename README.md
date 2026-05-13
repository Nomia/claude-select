# claude-select 🔐

[![PyPI version](https://img.shields.io/pypi/v/claude-select)](https://pypi.org/project/claude-select/)
[![Python versions](https://img.shields.io/pypi/pyversions/claude-select)](https://pypi.org/project/claude-select/)
[![CI](https://github.com/Nomia/claude-select/actions/workflows/ci.yml/badge.svg)](https://github.com/Nomia/claude-select/actions/workflows/ci.yml)

[中文说明](./README.zh-CN.md)

![claude-select overview](https://raw.githubusercontent.com/Nomia/claude-select/main/docs/images/claude-select-overview.png)

`claude-select` is a local Claude auth registry and selector for people who use multiple Claude accounts on one machine.

It stores two entry kinds:

- `cli` entries: captured from Claude CLI `auth login`; these support `watch`, `list --usage`, `whoami`, `select`, `sync-current`, `refresh`, and `relogin`
- `token` entries: captured from `claude setup-token`; these are simple long-lived SDK credentials for Python/program use

Long-lived `token` entries do **not** participate in quota monitoring, quota-aware auto-selection, or CLI account switching.

## Install 🚀

```bash
pip install claude-select
```

## How Users Get Started 👇

### 1. Capture your CLI accounts

Run the guided bootstrap:

```bash
claude-select init
```

By default, `claude-select` launches `claude auth login` in the current terminal for each account capture.

For each account:

1. choose an alias such as `work` or `personal`
2. `claude-select` launches `claude auth login`
3. finish authorization
4. return to `claude-select`
5. press Enter so `claude-select` can read the current Claude auth state
6. confirm the current `claude auth status` shown by `claude-select`
7. let `claude-select` capture the current login snapshot
8. look for a success block that confirms the account was saved and shows the current registry

You can add another CLI account later:

```bash
claude-select add work
claude-select add personal
```

If you do not want `claude-select` to launch `claude` for you, use:

```bash
claude-select add work --no-launch
```

### What `init` looks like

```bash
$ claude-select init
Claude account bootstrap
Add accounts one by one. Complete `claude auth login` for each account before capture.

Alias (blank to finish): work
Launching `claude auth login` in this terminal.
`claude auth login` will be launched in this terminal.
When login is complete, return here.
Press Enter after login is complete...
Current Claude auth status:
  email: a@company.com
  organization: Team A
  auth method: claude.ai
Use this identity for alias `work` and continue with capture? [Y/n]
Captured work <a@company.com> [Team A].
Status: healthy
Expires in: 7h 57m

Current registry:
Alias  Kind  Email            Organization  Status   Expires In  Last Selected  Last Synced
-----  ----  ---------------  ------------  -------  ----------  -------------  -----------
work   cli   a@company.com    Team A        healthy  7h 57m      -              just now
Add another account? [Y/n] y
```

### 2. Optionally add a long-lived SDK token

You can store a `claude setup-token` token for explicit Python usage. If the alias
already exists as a CLI account, the token is attached to that alias and the row
will appear as `cli+token` in the registry:

```bash
claude-select add-token work
```

`add-token` launches `claude setup-token`, tries to detect the token from terminal output, then stores it as a simple SDK credential. Because these official long-lived tokens are inference-only, profile metadata detection is best-effort and may fall back to manual prompts.

### What `add-token` looks like

```bash
$ claude-select add-token work
Launching `claude setup-token` in this terminal.
Complete authorization. When the token is printed, copy it and return here.
Detected the long-lived token from setup-token output.
Validated token for SDK/program use.
Profile metadata is unavailable for this token scope.
Email: a@company.com
Organization (optional): Team A
Captured work <a@company.com> [Team A].
Status: healthy
Expires in: 364d

Current registry:
Alias  Kind       Email            Organization  Status   Expires In  Last Selected  Last Synced
-----  ---------  ---------------  ------------  -------  ----------  -------------  -----------
work   cli+token  a@company.com    Team A        healthy  7h 57m      -              just now
```

### 3. See what is stored

```bash
claude-select list
claude-select list --usage
claude-select whoami
claude-select watch
claude-select watch --usage
claude-select watch --auto-refresh
```

Example table:

```text
Alias     Kind   Email             Organization    Status          Expires In  Last Selected  Last Synced
--------  -----  ----------------  --------------  --------------  ----------  -------------  -----------
personal  cli    a@example.com     Personal        healthy         18h 12m     2h ago         15m ago
work      cli    b@company.com     Team A          expiring_soon   1h 05m      -              6m ago
work-sdk  token  b@company.com     Team A          healthy         364d        -              just now
```

With `--usage`, `cli` entries show 5h/7d quota data and `token` entries show `n/a` because inference-only tokens do not expose quota/profile endpoints.

### 4. Select an account for Claude CLI

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
```

If the selected CLI alias is already expired, `select` still writes it back into Claude's live auth state so you can try a fast recovery path next. The command prints a warning and recommends:

```bash
claude-select refresh <alias>
```

### 5. Use an entry in Python

```python
from claude_select import AuthManager
from claude_code_sdk import ClaudeAgentOptions, query

manager = AuthManager()
env = manager.build_sdk_env("work")
# or explicitly use a long-lived SDK token entry:
# env = manager.build_sdk_env("work-sdk")

options = ClaudeAgentOptions(env=env)

async for message in query(prompt="analyze this repo", options=options):
    print(message)
```

The Python side reads from the same local registry, but it does **not** mutate Claude's live auth state.

Full Python SDK guide:

- [Python SDK Guide](./docs/python-sdk.md)

## CLI Commands 🧰

```bash
claude-select init
claude-select add <alias>
claude-select add-token <alias>
claude-select refresh [alias]
claude-select relogin <alias>
claude-select list
claude-select list --usage
claude-select watch
claude-select select [alias]
claude-select sync-current
claude-select remove <alias>
claude-select export-env <alias> --json
claude-select current
claude-select whoami
```

Command behavior:

- `init`: guided multi-account bootstrap for CLI accounts, then optional token capture phase
- `add`: launch `claude auth login` in the current terminal by default, show the current `claude auth status`, then capture the confirmed login into the registry
- `add-token`: launch `claude setup-token` in the current terminal by default, then store a long-lived token for explicit SDK/program use; if the alias already exists as a CLI account, the token is attached to that alias
- `refresh`: try the lightweight recovery path for one CLI alias or all expired/expiring aliases by doing `select -> claude -p "ping" -> sync-current`
- `relogin`: launch `claude auth login` in the current terminal by default, show the current `claude auth status`, then overwrite one stored CLI alias after the user logs in again
- `list`: show the current registry table and do a light sync of the current live account first
- `list --usage`: fetch and display 5h / 7d quota information for `cli` entries; `token` entries show `n/a`
- `watch`: keep a live Rich-powered view of the current Claude live account plus the local registry, with periodic live-state sync
- `watch --usage`: include 5h / 7d quota columns in the live registry table
- `watch --auto-refresh`: opt in to automatic `refresh` attempts for expired or expiring CLI accounts while the watch loop is running
- while `watch` is running, press `q` or `Esc` to exit cleanly
- `select`: write one stored `cli` snapshot back into Claude's live auth state
- `sync-current`: read Claude's current live auth state and sync any refreshed token data back into the matching `cli` registry entry
- `remove`: delete one stored entry
- `export-env`: print SDK env vars for one alias
- `current`: show the last alias selected for CLI use
- `whoami`: show Claude's current live auth state, matched alias, auth method, subscription, and current quota summary after a light sync

## Python API 🐍

Minimal usage:

```python
from claude_select import AuthManager

manager = AuthManager()

accounts = manager.list_accounts()
accounts_with_usage = manager.list_accounts(include_usage=True)
cli_accounts = manager.list_cli_accounts(include_usage=True)
token_accounts = manager.list_token_accounts()
details = manager.get_account("work")
summary = manager.get_account_summary("work", include_usage=True)
available = manager.list_available_accounts(include_usage=True, auto_refresh=True)
picked = manager.pick_available_account(include_usage=True, auto_refresh=True)
env = manager.build_sdk_env("work", auto_refresh=True)
sdk_env = manager.build_sdk_env("work-sdk")
auth_payload = manager.export_sdk_auth("work", auto_refresh=True)
live_quota = manager.get_live_quota()
account_quota = manager.get_account_quota("work", auto_refresh=True)
all_quotas = manager.list_account_quotas(auto_refresh=True)
```

Current public surface:

```python
class AuthManager:
    def list_accounts(self, include_usage: bool = False, *, auto_refresh: bool = False) -> list[dict]: ...
    def list_cli_accounts(self, include_usage: bool = False, *, auto_refresh: bool = False) -> list[dict]: ...
    def list_token_accounts(self, include_usage: bool = False) -> list[dict]: ...
    def list_available_accounts(self, *, include_usage: bool = True, auto_refresh: bool = False, require_quota: bool = True) -> list[dict]: ...
    def pick_available_account(self, *, include_usage: bool = True, auto_refresh: bool = False, require_quota: bool = True, prefer_current: bool = True) -> dict: ...
    def get_account(self, alias: str, *, auto_refresh: bool = False): ...
    def get_account_summary(self, alias: str, *, include_usage: bool = False, auto_refresh: bool = False) -> dict: ...
    def get_current_account_summary(self, *, include_usage: bool = True) -> dict: ...
    def capture_current_account(self, alias: str, overwrite: bool = True) -> dict: ...
    def add_token_account(self, alias: str, token: str, *, email: str, organization_name: str = "", organization_id: str = "", account_uuid: str = "", overwrite: bool = True) -> dict: ...
    def relogin_account(self, alias: str) -> dict: ...
    def refresh_account(self, alias: str, *, prompt: str = "ping") -> dict: ...
    def remove_account(self, alias: str) -> None: ...
    def select_account(self, alias: str, *, auto_refresh: bool = False) -> dict: ...
    def build_sdk_env(self, alias: str, base_env: dict[str, str] | None = None, *, auto_refresh: bool = False) -> dict[str, str]: ...
    def export_sdk_auth(self, alias: str, *, auto_refresh: bool = False) -> dict: ...
    def get_live_quota(self) -> dict: ...
    def get_account_quota(self, alias: str, *, auto_refresh: bool = False) -> dict: ...
    def list_account_quotas(self, *, auto_refresh: bool = False) -> list[dict]: ...
    def current_alias(self) -> str | None: ...
    def render_table(self) -> str: ...
```

Top-level helper:

```python
from claude_select import build_sdk_env

env = build_sdk_env("work")
```

`auto_refresh=True` is explicit on purpose. For CLI-backed aliases it will try the same lightweight recovery path as `claude-select refresh <alias>` before returning data:

- select that alias into Claude's live auth state
- run `claude -p "ping"`
- sync the refreshed live state back into the registry

This is useful for Python callers that want a best-effort recovery path without forcing a separate CLI maintenance step first.

Compatibility note:

- `build_sdk_env_auto()` and `pick_sdk_account()` remain importable for older integrations, but they now raise `AccountSelectionError`.
- Reason: long-lived `claude setup-token` tokens are inference-only and do not expose the profile/quota data required for reliable quota-aware rotation.

Quota responses are cached locally for 60 seconds. `watch`, `whoami`, and repeated CLI quota reads reuse that cache instead of hitting the remote usage endpoint on every refresh.

## How Expiry Works ⏳

`claude-select` does not refresh tokens automatically.

It reads the stored `expiresAt` timestamp and derives status from it:

- `healthy`: more than 1 hour remains
- `expiring_soon`: 1 hour or less remains
- `expired`: already expired
- `unknown`: no `expiresAt` was captured

If a `cli` account is expired:

- `select` fails
- `build_sdk_env()` fails for that alias
- first try `claude-select refresh <alias>`
- if refresh works, Claude refreshes the live session and `claude-select` syncs the new state back into the registry
- if refresh fails, run `claude-select relogin <alias>`

Long-lived `token` entries do not participate in `relogin`; replace them by running `add-token` again.

## Storage Layout 🗃️

The local registry is a SQLite database:

- macOS / Linux default:
  - `~/.config/claude-select/registry.db`
- if XDG is set:
  - `$XDG_CONFIG_HOME/claude-select/registry.db`

Each entry stores:

- alias
- kind (`cli_snapshot` or `token`)
- email
- organization name / id
- account uuid
- captured time
- expiresAt
- last selected time
- `oauthAccount`
- `claudeAiOauth` credential payload

Claude's own live state remains separate:

- Claude global config
- Claude credentials file or macOS Keychain

The registry is the source of truth. `select` writes one stored `cli` snapshot back into Claude's current live state.

## Current Limitations ⚠️

- `cli` entries are the only entries that support quota monitoring, `watch`, `select`, `sync-current`, `refresh`, and `relogin`.
- `token` entries are simple SDK credentials only.
- The tool does not auto-refresh OAuth tokens.
- The implementation depends on Claude's current local auth layout.
- Expiry monitoring is based on stored `expiresAt`; it does not proactively validate every entry with a remote auth probe.

## Development 🛠️

Install development dependencies:

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
