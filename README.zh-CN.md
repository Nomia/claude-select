# claude-select 🔐

[![PyPI version](https://img.shields.io/pypi/v/claude-select)](https://pypi.org/project/claude-select/)
[![Python versions](https://img.shields.io/pypi/pyversions/claude-select)](https://pypi.org/project/claude-select/)
[![CI](https://github.com/Nomia/claude-select/actions/workflows/ci.yml/badge.svg)](https://github.com/Nomia/claude-select/actions/workflows/ci.yml)

[English README](./README.md)

![claude-select overview](https://raw.githubusercontent.com/Nomia/claude-select/main/docs/images/claude-select-overview.png)

`claude-select` 是一个本地 Claude 多账号认证库和选择器，适合一台机器上同时使用多个 Claude 账号的人。

它会读取当前 Claude CLI 的登录态，把每个账号保存成一份本地快照，存进 SQLite 数据库里，并提供：

- 一个命令行工具，用来查看账号表、监控过期状态、把某个账号切回当前 Claude CLI
- 一个命令行入口，用来保存长期 token，给 SDK / 程序调用使用
- 一个 Python SDK，用来从数据库读取指定账号，并返回给 Claude Agent SDK 使用

它**不会**自动 refresh token。它只根据已捕获的 `expiresAt` 判断是否快过期或已过期，并在需要时要求用户重新登录。

## 安装 🚀

```bash
pip install claude-select
```

## 快速开始 👇

### 1. 先把账号录进去

执行初始化向导：

```bash
claude-select init
```

默认情况下，`claude-select` 会在当前终端里直接启动 `claude`，然后逐个录入账号。

每个账号的流程是：

1. 给账号起一个别名，比如 `work`、`personal`
2. `claude-select` 启动 `claude`
3. 在 `claude` CLI 会话里执行 `/login` 并完成授权
4. 退出 `claude`，回到 `claude-select`
5. 按回车，让 `claude-select` 把当前登录态采集进本地数据库
6. 看到一段成功反馈，确认账号已写入数据库，并展示当前账号表

后续也可以单独新增：

```bash
claude-select add work
claude-select add personal
```

如果你不想让 `claude-select` 自动启动 `claude`，可以这样用：

```bash
claude-select add work --no-launch
```

这时它会打印文字指导，等待你自己去运行 `claude` 并完成 `/login`。

CLI 账号录入完成后，`init` 还可以继续引导你执行 `claude setup-token`，把长期 token 一起录进数据库，专门给 SDK / 程序使用。

### `init` 实际交互示例

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

### `add` 实际交互示例

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

### `add-token` 实际交互示例

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

### 2. 看当前数据库里有哪些账号

```bash
claude-select list
claude-select list --usage
claude-select whoami
claude-select watch
```

展示效果大致如下：

```text
Alias     Kind   Email             Organization    Status          Expires In  Last Selected
--------  -----  ----------------  --------------  --------------  ----------  -------------
personal  cli    a@example.com     Personal        healthy         18h 12m     2h ago
work      cli    b@company.com     Team A          expiring_soon   1h 05m      -
work-sdk  token  b@company.com     Team A          healthy         8759h 59m   -
```

### 3. 给 Claude CLI 切换当前账号

```bash
claude-select select work
```

这个命令会从本地数据库读取 `work` 的认证快照，再写回 Claude 当前 live auth backend：

- macOS：Keychain + Claude 配置
- Linux / Windows：Claude credentials 文件 + Claude 配置

示例：

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

### 4. 在 Python 里使用某个账号

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

Python 这边和 CLI 共用同一份本地数据库，但它不会改写 Claude 当前登录态。

如果你已经用 `add-token` 录入了多个长期 token，也可以让 `claude-select` 在每次 SDK 调用前自动选择一个当前 quota 最合适的 token：

```python
from claude_select import AuthManager

manager = AuthManager()
env = manager.build_sdk_env_auto()
```

`build_sdk_env_auto()` 只会在 `token` 条目里挑选，依据缓存的 5h / 7d quota 状态选择当前最合适的 token，然后返回 env。

这个自动切换发生在你的程序向 `claude-select` 请求 SDK env 的那一刻。也就是说，实际决策点是在每次调用 Claude Agent SDK 之前，而不是后台常驻切换，也不会在一个已经跑起来的 Claude 请求中途切 token。

当前规则是：

- 只在 `token` 条目里挑选
- 任何 5h 或 7d 窗口已经到 `100%` 的 token 都会被跳过
- 在剩下的 token 里，优先选择 5h 剩余额度更多的；如果接近，再比较 7d 剩余额度
- usage 数据本地缓存 60 秒，所以重复的 SDK 调用会复用最近一次 quota 结果，而不是每次都重新请求

最小用法：

```python
from claude_select import AuthManager
from claude_code_sdk import ClaudeAgentOptions, query

manager = AuthManager()
env = manager.build_sdk_env_auto()
options = ClaudeAgentOptions(env=env)

async for message in query(prompt="summarize this repository", options=options):
    print(message)
```

完整 Python SDK 指南：

- [Python SDK Guide](./docs/python-sdk.md)
- [Python SDK 中文指南](./docs/python-sdk.zh-CN.md)

## CLI 命令 🧰

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

各命令含义：

- `init`：首次引导录入多个账号
- `add`：默认先在当前终端启动 `claude`，然后把当前 Claude 登录态录进数据库
- `add-token`：默认先在当前终端启动 `claude setup-token`，然后把长期 token 存进数据库，给 SDK / 程序使用
- `relogin`：默认先在当前终端启动 `claude`，然后让新的登录态覆盖某个已存在账号
- `list`：查看当前账号表，并先对当前 live account 做一次轻量同步
- `list --usage`：额外拉取并显示每个账号的 5h / 7d quota 信息
- `watch`：用 Rich live view 持续显示当前 Claude live account、本地账号库和 quota 信息，并定期同步当前 live state
- `select`：把某个已保存账号写回当前 Claude CLI 登录态
- `sync-current`：读取当前 Claude live auth state，把已经被 Claude 自动刷新的 token 同步回匹配的数据库记录
- `remove`：删除某个账号
- `export-env`：输出给 Claude Agent SDK 使用的环境变量
- `current`：显示最近一次给 CLI 选中的账号别名
- `whoami`：先做一次轻量同步，再显示 Claude 当前 live auth state、匹配到的 alias 和 quota 摘要

## Python API 🐍

最基本的用法：

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

当前公开接口：

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

也可以直接用顶层 helper：

```python
from claude_select import build_sdk_env

env = build_sdk_env("work")
```

也可以直接用自动选择 helper：

```python
from claude_select import build_sdk_env_auto

env = build_sdk_env_auto()
```

quota 数据会在本地缓存 60 秒。`watch`、`whoami` 和重复的 SDK 调用都会复用这份缓存，而不是每次刷新都重新请求远端 usage 接口。

## 过期机制 ⏳

`claude-select` 不会自动 refresh token。

它只读取保存时记录下来的 `expiresAt`，然后推导出 4 种状态：

- `healthy`：距离过期超过 6 小时
- `expiring_soon`：距离过期不超过 6 小时
- `expired`：已经过期
- `unknown`：没有记录到 `expiresAt`

如果账号已经过期：

- `select` 会失败
- `build_sdk_env()` 会失败
- 用户需要重新登录，再执行：

```bash
claude-select relogin <alias>
```

## 存储结构 🗃️

本地数据库默认是一个 SQLite 文件：

- macOS / Linux 默认位置：
  - `~/.config/claude-select/registry.db`
- 如果设置了 XDG：
  - `$XDG_CONFIG_HOME/claude-select/registry.db`

每个账号会保存这些信息：

- alias
- email
- organization name / id
- account uuid
- captured time
- expiresAt
- last selected time
- Claude 的 `oauthAccount`
- Claude 的 `claudeAiOauth` credentials payload

而 Claude 自己当前的 live state 依然是独立的：

- Claude 全局配置
- Claude credentials 文件或 macOS Keychain

本地数据库是 source of truth。`select` 的作用就是把数据库里的某份快照再写回 Claude 当前 live state。

## 当前限制 ⚠️

- 当前主要围绕 Claude OAuth 登录快照工作。
- 不做自动 refresh。
- 依赖 Claude 当前本地认证结构没有发生大改。
- 过期监测只基于本地 `expiresAt`，不会主动请求远端校验。
- `select` 会直接改掉当前机器上的 Claude 活跃登录态。

## 开发 🛠️

安装开发依赖：

```bash
pip install -e .[dev]
```

运行检查：

```bash
ruff check .
ruff format --check .
mypy
pytest
python -m build
python -m twine check dist/*
```

## 许可证 📄

MIT
