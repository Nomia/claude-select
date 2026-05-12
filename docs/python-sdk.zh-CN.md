# Python SDK 指南

`claude-select` 的 Python 接口刻意保持很小。SDK 这一层主要做两件事：

- 按 alias 读取本地 registry 里的某条记录
- 把它转换成 Claude Agent SDK 可直接使用的 `env`

本地 registry 里有两类条目：

- `cli` 条目：来自 Claude CLI `/login` 抓取；支持 quota、watch、select、sync 这些完整能力
- `token` 条目：来自 `claude setup-token`；只作为简单的长期 SDK 凭证保存

长期 `token` 条目**不参与** quota 自动选择、quota 监控或 CLI 切换。

## 安装

```bash
pip install claude-select
```

## 前置条件

Python 要使用某个 alias 之前，这个 alias 必须已经存在于本地 registry 中。

典型初始化方式：

```bash
claude-select init
```

也可以单独录入：

```bash
claude-select add work
claude-select add-token work-sdk
```

`add-token` 会启动 `claude setup-token`，尽量从终端输出里自动抓取 token，然后把它保存成一个简单的 SDK / 程序凭证。由于官方长期 token 是 inference-only，profile metadata 探测只是 best-effort，失败时会回退到人工输入。

## 最小用法

```python
from claude_select import AuthManager
from claude_code_sdk import ClaudeAgentOptions, query

manager = AuthManager()
env = manager.build_sdk_env("work")

options = ClaudeAgentOptions(env=env)

async for message in query(prompt="summarize this repository", options=options):
    print(message)
```

如果你要显式使用长期 token 条目：

```python
from claude_select import AuthManager

manager = AuthManager()
env = manager.build_sdk_env("work-sdk")
```

## `build_sdk_env()` 会返回什么

对于 `cli` 和 `token` 两类条目，`build_sdk_env(alias)` 都会返回一份干净的环境变量映射，通常包含：

- `CLAUDE_CODE_OAUTH_TOKEN`
- 如果 scopes 存在，还会带上 `CLAUDE_CODE_OAUTH_SCOPES`

同时它会移除冲突认证变量，例如：

- `ANTHROPIC_API_KEY`
- `ANTHROPIC_AUTH_TOKEN`
- `CLAUDE_CODE_USE_BEDROCK`
- `CLAUDE_CODE_USE_VERTEX`
- `CLAUDE_CODE_USE_FOUNDRY`

这样可以保证一次 Python 调用只绑定一条明确的本地认证记录。

## 常见用法

### 1. 查看所有条目

```python
from claude_select import AuthManager

manager = AuthManager()

for account in manager.list_accounts():
    print(account["alias"], account["auth_kind"], account["email"], account["status"])
```

### 2. 读取某个条目的元数据

```python
details = manager.get_account("work")
print(details.record.email)
print(details.record.expires_at)
```

### 3. 导出原始认证数据

```python
payload = manager.export_sdk_auth("work")
print(payload["credentials"])
```

### 4. 读取当前 live CLI 账号的 quota

```python
quota = manager.get_live_quota()
print(quota["alias"])
print(quota["quota_5h_left"], quota["quota_5h_reset"])
print(quota["quota_7d_left"], quota["quota_7d_reset"])
```

### 5. 读取某个已保存 CLI 账号的 quota

```python
quota = manager.get_account_quota("work")
print(quota["available"])
print(quota["five_hour"])
print(quota["seven_day"])
```

对于通过 `add-token` 创建的 `token` 条目，quota 不可用，返回里会是 `available=False`，并带 `n/a` 的 quota 字段。

### 6. 读取所有条目的 quota 视图

```python
for quota in manager.list_account_quotas():
    print(quota["alias"], quota["quota_5h_left"], quota["quota_7d_left"])
```

quota 数据会在本地缓存 60 秒。这样 `watch` 和重复的 SDK 读取不会在每次渲染时都重新请求远端 usage 接口。

## 不再支持自动选择

`build_sdk_env_auto()` 和 `pick_sdk_account()` 仍然保留导出，用于兼容旧版本，但现在会直接抛出 `AccountSelectionError`。

原因是：`claude setup-token` 生成的长期 token 是 inference-only，拿不到做可靠 quota 轮换所需的 profile / quota 数据。

现在请显式指定 alias：

```python
env = manager.build_sdk_env("work")
env = manager.build_sdk_env("work-sdk")
```

## 过期行为

SDK 这一层不会自动 refresh token。

如果某个 `cli` 条目已经过期：

- `build_sdk_env()` 会抛错
- `export_sdk_auth()` 会抛错

恢复方式：

```bash
claude-select relogin work
```

长期 `token` 条目不参与 `relogin`；如果你想替换它，就重新执行一次 `add-token`。

## 推荐心智模型

建议这样理解 `claude-select`：

- CLI 用户：`claude-select select work`
- Python 用户如果用登录快照：`AuthManager().build_sdk_env("work")`
- Python 用户如果用长期 token：`AuthManager().build_sdk_env("work-sdk")`

两边共享同一份本地 registry，但只有 CLI 的 `select` 会改动 Claude 当前活跃的 live auth state。
