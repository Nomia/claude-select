# claude-select 🚀

[English](./README.md) | [简体中文](./README.zh-CN.md)

[![PyPI version](https://img.shields.io/pypi/v/claude-select.svg)](https://pypi.org/project/claude-select/)
[![Python versions](https://img.shields.io/pypi/pyversions/claude-select.svg)](https://pypi.org/project/claude-select/)
[![CI](https://img.shields.io/github/actions/workflow/status/Nomia/claude-select/ci.yml?branch=main)](https://github.com/Nomia/claude-select/actions/workflows/ci.yml)

`claude-select` is a local SDK and CLI design for managing multiple Claude authentication profiles across:

- the global Claude Code CLI login state
- Python programs using the Claude Agent SDK

This repository now contains a working first implementation of the design described below:

- file-backed profile storage
- CLI profile capture, switch, sync, inspect, remove, and default SDK selection
- Python `build_sdk_env()` support for direct `ClaudeAgentOptions(env=...)` usage
- OAuth refresh handling for stored profiles

The README still documents the intended architecture so the implementation can evolve without losing the original design constraints.

## Status ✅

Current implementation status:

- `ProfileManager` and top-level `build_sdk_env()` are implemented
- CLI commands are implemented for local single-user usage
- OAuth refresh is implemented for stored profiles
- unit tests are in place
- lint, type-check, build, and CI configuration are included

## How Users Get Started ✨

Recommended first-run flow:

1. Log in with Claude's official CLI flow.

```bash
claude
```

Then complete `/login`.

2. Capture the current account into a named profile.

```bash
claude-select capture work
```

3. Log in with another account if needed, then capture again.

```bash
claude-select capture personal
```

4. Switch the global CLI account when needed.

```bash
claude-select use personal
```

5. Use a chosen profile from Python.

```python
from claude_select import ProfileManager
from claude_code_sdk import ClaudeAgentOptions

manager = ProfileManager()
env = manager.build_sdk_env("work")
options = ClaudeAgentOptions(env=env)
```

## Goals 🎯

- Let a user capture multiple Claude accounts/profiles on one machine.
- Let the global Claude Code CLI switch between stored profiles.
- Let Python programs select a profile explicitly for each Claude Agent SDK call.
- Share one profile store between CLI switching and Python SDK usage.
- Avoid coupling Python SDK requests to the current global CLI account.

## Core Model

The design separates three concepts:

1. `profiles`
   Stored account/auth profiles shared by CLI and Python SDK usage.
2. `current_cli_profile`
   The profile currently written into Claude Code's live login state.
3. `default_sdk_profile`
   The fallback profile used by Python helpers when the caller does not explicitly choose one.

This separation is intentional:

- CLI switching is global and mutates Claude's live state.
- Agent SDK switching is per-call and should be isolated through `env`.

## Authentication Model 🔐

### CLI

For the Claude Code CLI, switching works by reading and writing Claude's live login state:

- `~/.claude.json` or `~/.claude/.config.json`
- `~/.claude/.credentials.json`
- platform-specific secure storage where applicable
- `CLAUDE_CONFIG_DIR` when set

The SDK captures the current live state into a reusable profile, then later writes a chosen profile back into the live Claude files when the user switches.

### Python Agent SDK

For Python, the preferred model is explicit per-call environment injection:

```python
env = manager.build_sdk_env("work")
options = ClaudeAgentOptions(env=env)
```

This avoids:

- mutating global `os.environ`
- leaking one profile into another concurrent request
- forcing Python usage to follow whatever the CLI currently uses

## Shared Store Design

The SDK owns a profile store separate from Claude's live runtime files.

Recommended structure:

```text
~/.config/claude-select/
  state.json
  secrets/
    work.json
    personal.json
```

### `state.json`

Holds non-sensitive metadata and pointers:

```json
{
  "version": 1,
  "current_cli_profile": "personal",
  "default_sdk_profile": "work",
  "profiles": {
    "work": {
      "id": "work",
      "kind": "oauth",
      "label": "work",
      "email": "user@example.com",
      "organization_id": "org_xxx",
      "organization_name": "Example Org",
      "auth_state": "ok",
      "expires_at": 1760000000000,
      "secret_ref": "work",
      "updated_at": "2026-04-19T00:00:00Z"
    }
  }
}
```

### `secrets/<profile>.json`

Holds sensitive auth material:

```json
{
  "oauthAccount": {
    "emailAddress": "user@example.com"
  },
  "credentials": {
    "claudeAiOauth": {
      "accessToken": "...",
      "refreshToken": "...",
      "expiresAt": 1760000000000,
      "scopes": ["user:profile"]
    }
  }
}
```

Future versions may replace file-based secret storage with platform keychains while keeping the same `secret_ref` abstraction.

## OAuth Expiry Strategy

When using OAuth-backed profiles:

- Access token near expiry: refresh automatically if `refreshToken` exists.
- Refresh succeeds: update the profile store before returning.
- Refresh fails: mark the profile as `reauth_required`.

For CLI switching:

- switching should still be allowed
- the tool should clearly report that the selected profile now requires `claude` `/login`
- after re-login, the user runs `capture` or `sync` to update the stored profile

For Python SDK usage:

- `build_sdk_env(profile)` should attempt refresh first
- if refresh fails, raise a clear exception such as `ProfileReauthRequired`

## CLI Design 🖥️

Planned commands:

```bash
claude-select capture <profile>
claude-select sync [<profile>]
claude-select list
claude-select current
claude-select use <profile>
claude-select remove <profile>
claude-select set-default-sdk <profile>
```

### Command behavior

- `capture <profile>`
  Reads Claude's current live login state and stores it as a named profile.
- `sync [<profile>]`
  Updates an existing stored profile from the current live login state.
- `list`
  Shows all stored profiles and auth state.
- `current`
  Shows the current CLI profile and default SDK profile.
- `use <profile>`
  Switches Claude's global live login state to the chosen profile.
- `remove <profile>`
  Removes a stored profile from the SDK store.
- `set-default-sdk <profile>`
  Updates `default_sdk_profile`.

## Python SDK Design 🐍

Planned primary interface:

```python
from claude_select import ProfileManager

manager = ProfileManager()
env = manager.build_sdk_env("work")
```

Planned convenience function:

```python
from claude_select import build_sdk_env

env = build_sdk_env("work")
```

### Intended `ProfileManager` surface

```python
class ProfileManager:
    def list_profiles(self) -> list[str]: ...
    def capture_cli_profile(self, name: str) -> None: ...
    def sync_cli_profile(self, name: str | None = None) -> None: ...
    def switch_cli(self, name: str) -> None: ...
    def set_default_sdk_profile(self, name: str) -> None: ...
    def get_default_sdk_profile(self) -> str | None: ...
    def inspect_profile(self, name: str) -> dict: ...
    def build_sdk_env(self, name: str | None = None) -> dict[str, str]: ...
```

## Agent SDK Environment Injection

The direct usage style for Python is the intended default:

```python
from claude_select import ProfileManager
from claude_code_sdk import ClaudeAgentOptions, query

manager = ProfileManager()

env = manager.build_sdk_env("work")
options = ClaudeAgentOptions(env=env)

async for message in query(
    prompt="Analyze this repository",
    options=options,
):
    print(message)
```

### Why this is the default

- explicit per-call behavior
- works with async and concurrent tasks
- no hidden global mutation
- lets one process use multiple profiles safely

## Environment Variables by Profile Type

`build_sdk_env()` will return a clean environment map for exactly one auth mode.

### OAuth profile

Expected output:

```python
{
    "CLAUDE_CODE_OAUTH_TOKEN": "...",
    "CLAUDE_CODE_OAUTH_REFRESH_TOKEN": "..."
}
```

### API key profile

Expected output:

```python
{
    "ANTHROPIC_API_KEY": "..."
}
```

### Important rule

Conflicting auth env vars should be removed from the returned environment. For example, an OAuth profile should not leave these active:

- `ANTHROPIC_API_KEY`
- `ANTHROPIC_AUTH_TOKEN`
- `CLAUDE_CODE_USE_BEDROCK`
- `CLAUDE_CODE_USE_VERTEX`
- `CLAUDE_CODE_USE_FOUNDRY`

## Development 🛠️

Set up a local environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e ".[dev]"
```

Run the full local quality suite:

```bash
ruff check .
ruff format --check .
mypy
python3 -m pytest
python3 -m build
python3 -m twine check dist/*
```

You can also run the CLI as:

```bash
python3 -m claude_select --help
```

## Runtime Relationship

The intended data flow is:

- CLI capture: Claude live state -> SDK profile store
- CLI switch: SDK profile store -> Claude live state
- Python SDK usage: SDK profile store -> `env`

The Python SDK should not depend on the current global CLI account unless the caller explicitly chooses the same profile.

## Safety and Concurrency

Implementation should include:

- file locking during capture, sync, switch, and refresh
- atomic writes for state and secret files
- backups before mutating Claude live files
- detection of running Claude CLI / IDE instances
- clear messaging when restart or re-login is required

Current status:

- file locking is implemented for the SDK profile store
- atomic file writes are implemented for profile and live-state file writes
- live-state backups are implemented before Claude auth mutation
- full Claude process detection is not implemented yet

## Status Values

Each profile should expose a simple auth status:

- `ok`
- `expiring_soon`
- `refreshable`
- `reauth_required`
- `invalid`

These statuses should be visible in `list` and `inspect_profile`.

## Scope of First Implementation

The first implementation should prioritize:

1. file-based profile store
2. OAuth profile capture from Claude CLI live state
3. CLI switching between stored OAuth profiles
4. `build_sdk_env(profile)` for Python Agent SDK usage
5. token refresh for OAuth-backed profiles

The first implementation should not prioritize:

- hosted sync
- multi-user remote storage
- GUI
- deep plugin integrations

## Current Limitations ⚠️

- The primary supported profile type today is OAuth captured from Claude CLI live state.
- macOS keychain reading and writing is implemented, but broader secure-store coverage is still incomplete.
- Full pre-switch detection of running Claude sessions and IDE integrations is not implemented yet.
- This project is designed for local single-user machines, not shared multi-user hosts.

## Release Checklist 📦

Before publishing a release:

1. Run the full local quality suite.
2. Verify `claude-select capture`, `claude-select use`, and `build_sdk_env()` against a real local Claude setup.
3. Update `CHANGELOG.md`.
4. Create a version tag and publish artifacts built from CI-verified sources.

## References

This design is informed by the following projects:

- [Leuconoe/ClaudeCodeMultiAccounts](https://github.com/Leuconoe/ClaudeCodeMultiAccounts)
- [realiti4/claude-swap](https://github.com/realiti4/claude-swap)

## Current State

The repository contains a tested first implementation aimed at local single-user usage. Future work can harden:

- platform keychain integration beyond the current file-backed path and macOS keychain support
- richer process detection before CLI switching
- broader profile kinds beyond OAuth-backed profiles
