# Python SDK Guide

`claude-select` exposes a small Python surface on purpose. The SDK side does two jobs:

- read one stored registry entry by alias
- convert it into an `env` mapping for Claude Agent SDK usage

There are two registry entry kinds:

- `cli` entries: captured from Claude CLI `/login`; these support quota, watch, select, and sync flows
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
claude-select add-token work-sdk
```

`add-token` launches `claude setup-token`, tries to detect the token from the terminal output, and stores it as a simple SDK/program credential. Because official long-lived tokens are inference-only, profile metadata detection is best-effort and may fall back to manual prompts.

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

To use a long-lived token entry explicitly:

```python
from claude_select import AuthManager

manager = AuthManager()
env = manager.build_sdk_env("work-sdk")
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

This keeps one Python call bound to one stored account or token entry.

## Common patterns

### 1. Inspect available entries

```python
from claude_select import AuthManager

manager = AuthManager()

for account in manager.list_accounts():
    print(account["alias"], account["auth_kind"], account["email"], account["status"])
```

### 2. Get one entry's metadata

```python
details = manager.get_account("work")
print(details.record.email)
print(details.record.expires_at)
```

### 3. Export raw auth payload

```python
payload = manager.export_sdk_auth("work")
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
quota = manager.get_account_quota("work")
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

Quota data is cached locally for 60 seconds. This keeps `watch` and repeated SDK reads from hitting the remote usage endpoint on every render.

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
claude-select relogin work
```

A long-lived `token` entry does not participate in `relogin`; record a new one with `add-token` if you want to rotate it manually.

## Recommended usage model

Use `claude-select` like this:

- CLI users: `claude-select select work`
- Python users with login snapshots: `AuthManager().build_sdk_env("work")`
- Python users with long-lived tokens: `AuthManager().build_sdk_env("work-sdk")`

Both flows share the same local registry, but only CLI selection mutates Claude's active live auth state.
