# Python SDK 指南

`claude-select` 的 Python 接口刻意保持很小。SDK 这一层主要只做一件事：

- 从本地认证库读取某个账号快照
- 转成 Claude Agent SDK 可直接使用的 `env`

除非你显式执行 CLI 侧的选择动作，否则它不会改动当前 Claude CLI 的活跃登录态。

## 安装

```bash
pip install claude-select
```

## 前置条件

Python 里要使用某个账号之前，这个账号必须已经被录入本地数据库。

典型初始化方式：

```bash
claude-select init
```

或者：

```bash
claude-select add work
claude-select add-token work-sdk
```

`add-token` 会先启动 `claude setup-token`，尽量从终端输出里自动抓取 token，
再验证它，并自动解析这个 token 对应的 email 和 organization。只有自动探测失败时，
才会回退到人工输入。

## 最小用法

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

## `build_sdk_env()` 会返回什么

对于 OAuth 账号，`build_sdk_env(alias)` 会返回一份干净的环境变量映射，通常包含：

- `CLAUDE_CODE_OAUTH_TOKEN`
- 如果 scopes 存在，还会带上 `CLAUDE_CODE_OAUTH_SCOPES`

同时它会移除冲突认证变量，例如：

- `ANTHROPIC_API_KEY`
- `ANTHROPIC_AUTH_TOKEN`
- `CLAUDE_CODE_USE_BEDROCK`
- `CLAUDE_CODE_USE_VERTEX`
- `CLAUDE_CODE_USE_FOUNDRY`

这样可以保证一次 Python 调用只绑定一个账号快照。

如果这个 alias 是通过 `claude-select add-token` 录入的长期 token，`build_sdk_env(alias)` 返回的仍然是 `CLAUDE_CODE_OAUTH_TOKEN`，但它背后是一个更适合 SDK / 程序调用的一年期 token，而不是 CLI 登录快照。

## 常见用法

### 1. 查看所有可用账号

```python
from claude_select import AuthManager

manager = AuthManager()

for account in manager.list_accounts():
    print(account["alias"], account["email"], account["status"])
```

### 2. 读取某个账号的元数据

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

### 4. 读取当前 live account 的 quota

```python
quota = manager.get_live_quota()
print(quota["alias"])
print(quota["quota_5h_left"], quota["quota_5h_reset"])
print(quota["quota_7d_left"], quota["quota_7d_reset"])
```

### 5. 读取某个已保存账号的 quota

```python
quota = manager.get_account_quota("work")
print(quota["available"])
print(quota["five_hour"])
print(quota["seven_day"])
```

### 6. 读取所有账号的 quota

```python
for quota in manager.list_account_quotas():
    print(quota["alias"], quota["quota_5h_left"], quota["quota_7d_left"])
```

quota 数据会在本地缓存 60 秒。这样 `watch` 和重复的 SDK 读取不会在每次渲染时都重新请求远端 usage 接口。

### 7. 自动挑选当前最合适的长期 token

```python
env = manager.build_sdk_env_auto()
```

这个方法只会在 `token` 条目里挑选。它会检查缓存的 5h / 7d usage，然后选出当前最合适的长期 token，再返回 env。

这个决策发生在你的程序请求 env 的那一刻，所以实际触发点就是“每次调用 Claude Agent SDK 之前”。它不是后台常驻调度器，也不会在一个已经运行中的请求中途切 token。

当前规则：

- 只在 `token` 条目里挑选
- 任何 5h 或 7d 窗口已经到 `100%` 的 token 都会被跳过
- 在剩下的 token 里，优先选 5h 剩余额度更多的；如果接近，再比较 7d 剩余额度
- usage 结果会本地缓存 60 秒

常见用法：

```python
from claude_select import AuthManager
from claude_code_sdk import ClaudeAgentOptions, query

manager = AuthManager()
env = manager.build_sdk_env_auto()
options = ClaudeAgentOptions(env=env)

async for message in query(prompt="summarize this repository", options=options):
    print(message)
```

## 过期行为

SDK 这一层不会自动 refresh token。

如果账号已经过期：

- `build_sdk_env()` 会抛错
- `export_sdk_auth()` 会抛错

恢复方式：

```bash
claude-select relogin work
```

然后再重新调用 `build_sdk_env("work")`。

## 推荐心智模型

建议这样理解 `claude-select`：

- CLI 用户：`claude-select select work`
- Python 用户：`AuthManager().build_sdk_env("work")`

两边共享同一份本地认证库，但只有 CLI 的 `select` 会改动 Claude 当前活跃的 live auth state。
