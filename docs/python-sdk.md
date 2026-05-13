# Python SDK Guide

`claude-select` exposes a small Python surface on purpose. The SDK side does two jobs:

- read one stored registry entry by alias
- convert it into an `env` mapping for Claude Agent SDK usage

There are two registry entry kinds:

- `cli` entries: captured from Claude CLI `auth login`; these support quota, watch, select, and sync flows
- `token` entries: captured from `claude setup-token`; these are simple long-lived SDK credentials only

Long-lived `token` entries are **not** used for quota-aware auto-selection, quota monitoring, or CLI account switching.

## Install

```bash
pip install claude-select
```

## Prerequisite

Before Python can use an alias, that alias must already exist in the local registry.

Typical bootstrap:

```bash
claude-select init
```

Or capture things one by one:

```bash
claude-select add work
claude-select add-token work
```

`add-token` launches `claude setup-token`, tries to detect the token from the terminal output, and stores it as a simple SDK/program credential. If the alias already exists as a CLI account, the token is attached to that alias instead of replacing the CLI snapshot. Because official long-lived tokens are inference-only, profile metadata detection is best-effort and may fall back to manual prompts.

## Minimal usage

```python
from claude_select import AuthManager
from claude_code_sdk import ClaudeAgentOptions, query

manager = AuthManager()
env = manager.build_sdk_env("work")

options = ClaudeAgentOptions(env=env)

async for message in query(prompt="summarize this repository", options=options):
    print(message)
```

If a CLI alias has an attached long-lived token, `build_sdk_env("work")` will prefer
that token automatically. You can also keep standalone token-only aliases if you want:

```python
from claude_select import AuthManager

manager = AuthManager()
env = manager.build_sdk_env("work")
```

## What `build_sdk_env()` returns

For both `cli` and `token` entries, `build_sdk_env(alias)` returns a clean environment mapping that includes:

- `CLAUDE_CODE_OAUTH_TOKEN`
- `CLAUDE_CODE_OAUTH_SCOPES` when scopes are present

It also removes conflicting auth variables such as:

- `ANTHROPIC_API_KEY`
- `ANTHROPIC_AUTH_TOKEN`
- `CLAUDE_CODE_USE_BEDROCK`
- `CLAUDE_CODE_USE_VERTEX`
- `CLAUDE_CODE_USE_FOUNDRY`

This keeps one Python call bound to one stored account entry. When an alias has both a
CLI snapshot and an attached token, the token is used for SDK env export and the CLI
snapshot remains available for quota, watch, select, and sync flows.

## Common patterns

### 1. Inspect available entries

```python
from claude_select import AuthManager

manager = AuthManager()

for account in manager.list_accounts():
    print(account["alias"], account["auth_kind"], account["email"], account["status"])

for account in manager.list_accounts(include_usage=True, auto_refresh=True):
    print(account["alias"], account["quota_5h_left"], account["quota_7d_left"])
```

### 2. Get one entry's metadata

```python
details = manager.get_account("work", auto_refresh=True)
print(details.record.email)
print(details.record.expires_at)

summary = manager.get_account_summary("work", include_usage=True, auto_refresh=True)
print(summary["quota_5h_left"], summary["quota_7d_left"])
```

### 3. Export raw auth payload

```python
payload = manager.export_sdk_auth("work", auto_refresh=True)
print(payload["credentials"])
```

### 4. Read quota for the current live CLI account

```python
quota = manager.get_live_quota()
print(quota["alias"])
print(quota["quota_5h_left"], quota["quota_5h_reset"])
print(quota["quota_7d_left"], quota["quota_7d_reset"])
```

### 5. Read quota for one stored CLI account

```python
quota = manager.get_account_quota("work", auto_refresh=True)
print(quota["available"])
print(quota["five_hour"])
print(quota["seven_day"])
```

For `token` entries created through `add-token`, quota is not available and the response will report `available=False` plus `n/a` quota fields.

### 6. Read quota for every stored entry

```python
for quota in manager.list_account_quotas():
    print(quota["alias"], quota["quota_5h_left"], quota["quota_7d_left"])
```

### 7. Get only currently available accounts

```python
available = manager.list_available_accounts(include_usage=True, auto_refresh=True)
for account in available:
    print(account["alias"], account["status"], account["quota_5h_left"])

picked = manager.pick_available_account(include_usage=True, auto_refresh=True)
print("selected", picked["alias"])
```

When `require_quota=True` (the default), this only returns CLI-backed aliases with:

- non-expired status
- readable, non-stale quota data
- remaining quota in both the 5h and 7d windows

Quota data is cached locally for 60 seconds. This keeps `watch` and repeated SDK reads from hitting the remote usage endpoint on every render.

## Auto refresh for Python callers

Some public methods accept `auto_refresh=True`, including:

- `list_accounts()`
- `list_cli_accounts()`
- `get_account()`
- `get_account_summary()`
- `build_sdk_env()`
- `export_sdk_auth()`
- `get_account_quota()`
- `list_account_quotas()`
- `list_available_accounts()`
- `pick_available_account()`

For CLI-backed aliases, `auto_refresh=True` means:

1. If the alias is expired or expiring soon, try the lightweight refresh path first.
2. That path is equivalent to:
   - select the alias into Claude's live auth state
   - run `claude -p "ping"`
   - sync the refreshed live state back into the registry
3. If refresh still fails, the original method raises the same error it normally would.

This is opt-in because it mutates Claude's live auth state and triggers a real Claude request.

## Unsupported auto-selection

`build_sdk_env_auto()` and `pick_sdk_account()` remain importable for compatibility with older releases, but they now raise `AccountSelectionError`.

Why: long-lived `claude setup-token` tokens are inference-only and do not expose the profile/quota data needed for reliable quota-aware token rotation.

Use explicit aliases instead:

```python
env = manager.build_sdk_env("work")
env = manager.build_sdk_env("work-sdk")
```

## Expiry behavior

The SDK side does not refresh tokens automatically.

If a `cli` entry is expired:

- `build_sdk_env()` raises an error
- `export_sdk_auth()` raises an error

Recovery flow:

```bash
claude-select refresh work
# If refresh fails:
claude-select relogin work
```

A long-lived `token` entry does not participate in `relogin`; record a new one with `add-token` if you want to rotate it manually.

## Recommended usage model

Use `claude-select` like this:

- CLI users: `claude-select select work`
- Python users with login snapshots: `AuthManager().build_sdk_env("work")`
- Python users with a long-lived token attached to a CLI alias: `AuthManager().build_sdk_env("work")`

Both flows share the same local registry, but only CLI selection mutates Claude's active live auth state.
