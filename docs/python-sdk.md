# Python SDK Guide

`claude-select` exposes a small Python surface on purpose. The SDK side is meant to do one job well:

- read one stored Claude auth snapshot from the local registry
- convert it into an `env` mapping for Claude Agent SDK usage

It does not mutate Claude's active CLI login state unless you explicitly call CLI-side selection.

## Install

```bash
pip install claude-select
```

## Prerequisite

Before Python can use an account, that account must already exist in the local registry.

Typical bootstrap:

```bash
claude-select init
```

or:

```bash
claude-select add work
claude-select add-token work-sdk
```

## Minimal usage

```python
from claude_select import AuthManager
from claude_code_sdk import ClaudeAgentOptions, query

manager = AuthManager()
env = manager.build_sdk_env("work")
auto_env = manager.build_sdk_env_auto()

options = ClaudeAgentOptions(env=env)

async for message in query(prompt="summarize this repository", options=options):
    print(message)
```

## What `build_sdk_env()` returns

For an OAuth-backed account, `build_sdk_env(alias)` returns a clean environment mapping that includes:

- `CLAUDE_CODE_OAUTH_TOKEN`
- `CLAUDE_CODE_OAUTH_SCOPES` when scopes are present

It also removes conflicting auth variables such as:

- `ANTHROPIC_API_KEY`
- `ANTHROPIC_AUTH_TOKEN`
- `CLAUDE_CODE_USE_BEDROCK`
- `CLAUDE_CODE_USE_VERTEX`
- `CLAUDE_CODE_USE_FOUNDRY`

This keeps one Python call bound to one stored account snapshot.

For long-lived token entries captured through `claude-select add-token`, the same method returns `CLAUDE_CODE_OAUTH_TOKEN`, but the underlying entry is a one-year token intended for SDK/program use rather than CLI account switching.

## Common patterns

### 1. Inspect available accounts

```python
from claude_select import AuthManager

manager = AuthManager()

for account in manager.list_accounts():
    print(account["alias"], account["email"], account["status"])
```

### 2. Get one account's metadata

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

### 4. Read quota for the current live account

```python
quota = manager.get_live_quota()
print(quota["alias"])
print(quota["quota_5h_left"], quota["quota_5h_reset"])
print(quota["quota_7d_left"], quota["quota_7d_reset"])
```

### 5. Read quota for one stored account

```python
quota = manager.get_account_quota("work")
print(quota["available"])
print(quota["five_hour"])
print(quota["seven_day"])
```

### 6. Read quota for every stored account

```python
for quota in manager.list_account_quotas():
    print(quota["alias"], quota["quota_5h_left"], quota["quota_7d_left"])
```

Quota data is cached locally for 60 seconds. This keeps `watch` and repeated SDK reads from hitting the remote usage endpoint on every render.

### 7. Auto-pick the best long-lived token

```python
env = manager.build_sdk_env_auto()
```

This only considers `token` entries. It checks cached 5h / 7d usage and picks the best available long-lived token before returning an env mapping.

## Expiry behavior

The SDK side does not refresh tokens automatically.

If an account is expired:

- `build_sdk_env()` raises an error
- `export_sdk_auth()` raises an error

Recovery flow:

```bash
claude-select relogin work
```

Then call `build_sdk_env("work")` again.

## Recommended usage model

Use `claude-select` like this:

- CLI users: `claude-select select work`
- Python users: `AuthManager().build_sdk_env("work")`

Both flows share the same local registry, but only CLI selection mutates Claude's active live auth state.
