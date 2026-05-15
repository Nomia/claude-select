# claude-select 🔐

[![PyPI version](https://img.shields.io/pypi/v/claude-select)](https://pypi.org/project/claude-select/)
[![Python versions](https://img.shields.io/pypi/pyversions/claude-select)](https://pypi.org/project/claude-select/)
[![CI](https://github.com/Nomia/claude-select/actions/workflows/ci.yml/badge.svg)](https://github.com/Nomia/claude-select/actions/workflows/ci.yml)

[English README](./README.md)

![claude-select overview](https://raw.githubusercontent.com/Nomia/claude-select/main/docs/images/claude-select-overview.png)

`claude-select` 是一个本地 Claude 多账号认证库和选择器，适合一台机器上同时使用多个 Claude 账号的人。

它会保存两类条目：

- `cli` 条目：来自 Claude CLI `auth login` 抓取；支持 `watch`、`list --usage`、`whoami`、`select`、`sync-current`、`refresh`、`relogin`
- `token` 条目：来自 `claude setup-token`；只作为简单的长期 SDK 凭证保存，给 Python / 程序显式使用

长期 `token` 条目**不参与** quota 监控、按 quota 自动选择或 CLI 切换。

## 安装 🚀

```bash
pip install claude-select
```

## 快速开始 👇

### 1. 先录入 CLI 账号

执行初始化向导：

```bash
claude-select init
```

默认情况下，`claude-select` 会在当前终端里直接启动 `claude auth login`，然后逐个录入账号。

每个账号的流程是：

1. 给账号起一个别名，比如 `work`、`personal`
2. `claude-select` 启动 `claude auth login`
3. 完成授权
4. 回到 `claude-select`
5. 按回车，让 `claude-select` 读取当前 Claude 登录态
6. 确认 `claude-select` 展示的当前 `claude auth status`
7. 让 `claude-select` 把当前登录态采集进本地数据库
8. 看到一段成功反馈，确认账号已写入数据库，并展示当前账号表

后续也可以单独新增 CLI 账号：

```bash
claude-select add work
claude-select add personal
```

如果你不想让 `claude-select` 自动启动 `claude`，可以这样用：

```bash
claude-select add work --no-launch
```

### `init` 实际交互示例

```bash
$ claude-select init
Claude account bootstrap
Add accounts one by one. Complete `claude auth login` for each account before capture.

Alias (blank to finish): work
Launching `claude auth login` in this terminal.
`claude auth login` 会在当前终端里启动。
登录完成后回到这里继续。
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

### 2. 查看当前存储内容

```bash
claude-select list
claude-select list --usage
claude-select usage work
claude-select whoami
claude-select watch
claude-select watch --usage
claude-select watch --auto-refresh
```

`list --usage` 示例：

```bash
$ claude-select list --usage
Alias        Kind       Email                      Organization   Status         Expires In  Last Selected  Last Synced  5h Left  5h Reset  7d Left  7d Reset
-----------  ---------  -------------------------  -------------  -------------  ----------  -------------  -----------  -------  --------  -------  --------
team-am      cli        alice.lee@example.com      Automizely     expiring_soon  13m         11h ago        42m ago      44.0%    3h 5m     80.0%    6d 6h
team-as      cli        alice.lee@example.com      AfterShip      expiring_soon  13m         1d ago         just now     44.0%    3h 5m     80.0%    6d 6h
consulting   cli        bob.chen@example.com       Studio North   healthy        6h 7m       11h ago        1h ago       41.0%    3h 5m     81.0%    4d 12h
sdk-bot      token      sdk.bot@example.com        Automation     healthy        364d        -              just now     n/a      n/a       n/a      n/a
```

`whoami` 示例：

```bash
$ claude-select whoami
Current Claude live account
  matched alias: team-as
  email: alice.lee@example.com
  organization: AfterShip
  expires in: 13m
  auth method: claude.ai
  subscription: team
  5h quota left: 44.0%
  5h resets in: 3h 5m
  7d quota left: 80.0%
  7d resets in: 6d 6h
  target: config: /Users/you/.claude.json
  target: credentials store: macOS Keychain (Claude Code-credentials/you)
```

`watch --usage` 示例：

```text
Current Claude live account
  matched alias: team-as
  email: alice.lee@example.com
  organization: AfterShip
  expires in: 13m
  auth method: claude.ai
  subscription: team

Local account registry
Alias        Kind  Email                  Organization  Status         Expires In  Last Selected  Last Synced  5h Left  5h Reset  7d Left  7d Reset
-----------  ----  ---------------------  ------------  -------------  ----------  -------------  -----------  -------  --------  -------  --------
team-am      cli   alice.lee@example.com  Automizely    expiring_soon  13m         11h ago        42m ago      44.0%    3h 5m     80.0%    6d 6h
team-as      cli   alice.lee@example.com  AfterShip     expiring_soon  13m         1d ago         just now     44.0%    3h 5m     80.0%    6d 6h
consulting   cli   bob.chen@example.com   Studio North  healthy        6h 7m       11h ago        1h ago       41.0%    3h 5m     81.0%    4d 12h

Heads up
  Some CLI accounts are close to expiry.
  No manual refresh is needed yet.

  Tip: run `claude-select watch --auto-refresh` to let watch try refresh right around expiry.
```

加上 `--usage` 之后，`cli` 条目会显示 5h / 7d quota；`token` 条目会显示 `n/a`，因为 inference-only token 拿不到 quota/profile 接口。如果某个值后面带 `~`，表示这次显示的是本地旧缓存，最新 usage 拉取失败或被限流了。

### 3. 给 Claude CLI 切换当前账号

```bash
claude-select select work
```

这个命令会从本地数据库读取 `work` 的认证快照，再写回 Claude 当前的 live auth backend：

- macOS：Keychain + Claude config
- Linux / Windows：Claude credentials file + Claude config

示例：

```bash
$ claude-select select work
Selected work <a@company.com> [Team A].
Updated Claude live auth state:
  - config: /Users/you/.claude.json
  - credentials store: macOS Keychain
Current CLI alias: work
```

如果被 `select` 的 CLI alias 已经过期，`select` 仍然会把它写回当前 Claude live auth state，方便你紧接着走快速恢复路径。命令会给出警告，并推荐：

```bash
claude-select refresh <alias>
```

### 4. 在 Python 里使用某个条目

```python
from claude_select import AuthManager
from claude_code_sdk import ClaudeAgentOptions, query

manager = AuthManager()
env = manager.build_sdk_env("work")
# 或显式使用长期 token 条目：
# env = manager.build_sdk_env("work-sdk")

options = ClaudeAgentOptions(env=env)

async for message in query(prompt="analyze this repo", options=options):
    print(message)
```

Python 这边和 CLI 共用同一份本地 registry，但它不会改写 Claude 当前登录态。

完整 Python SDK 指南：

- [Python SDK Guide](./docs/python-sdk.md)
- [Python SDK 中文指南](./docs/python-sdk.zh-CN.md)

## 可选：录入长期 SDK Token

如果你只是想给 Python 或 SDK 显式使用一个长期 `claude setup-token`，可以在后面再补：

```bash
claude-select add-token work
```

如果 alias 已经是一个 CLI 账号，`add-token` 会把长期 token 挂到这个 alias 上，表格里会显示成 `cli+token`。

`add-token` 会启动 `claude setup-token`，尽量从终端输出里自动抓取 token，然后把它保存成一个简单的 SDK 凭证。由于这类官方长期 token 是 inference-only，profile metadata 探测只是 best-effort，失败时会回退到人工输入。

## CLI 命令 🧰

```bash
claude-select init
claude-select add <alias>
claude-select add-token <alias>
claude-select refresh [alias]
claude-select relogin <alias>
claude-select list
claude-select list --usage
claude-select usage <alias>
claude-select watch
claude-select select [alias]
claude-select sync-current
claude-select rename <old-alias> <new-alias>
claude-select remove <alias>
claude-select export-env <alias> --json
claude-select current
claude-select whoami
```

各命令含义：

- `init`：首次引导录入多个 CLI 账号，结束后可选进入 token 录入阶段
- `add`：默认先在当前终端启动 `claude auth login`，展示当前 `claude auth status` 让你确认后，再把当前登录态录进 registry
- `add-token`：默认先在当前终端启动 `claude setup-token`，然后把长期 token 存进 registry，供 SDK / 程序显式使用；如果 alias 已存在为 CLI 账号，就把 token 挂到该 alias 上
- `refresh`：对一个 CLI alias 或所有已过期的 CLI alias 走轻量恢复路径：`select -> claude -p "ping" -> sync-current`；手动 refresh 只有在 token 真正到期时才有意义
- `relogin`：默认先在当前终端启动 `claude auth login`，展示当前 `claude auth status` 让你确认后，再用新的登录态覆盖某个已保存的 `cli` 条目
- `list`：查看当前 registry，并先对当前 live account 做一次轻量同步
- `list --usage`：拉取并显示 `cli` 条目的 5h / 7d quota；`token` 条目显示 `n/a`
- `usage`：单独查看一个 alias 的 5h / 7d quota；如果最新拉取失败，会附带 stale / error 诊断信息
- `watch`：用 Rich live view 持续显示当前 Claude live account 和本地 registry，并定期同步当前 live state
- `watch --usage`：在 live registry 表格中额外显示 5h / 7d quota 列
- `watch --auto-refresh`：显式开启自动 `refresh`，只会在过期前约 5 秒到过期后约 10 秒的临界窗口里尝试恢复
- `watch` 运行时可按 `q` 或 `Esc` 干净退出
- `select`：把某个已保存的 `cli` 快照写回当前 Claude CLI 登录态
- `sync-current`：读取当前 Claude live auth state，把已经被 Claude 自动刷新的 token 同步回匹配的 `cli` 记录
- `rename`：只改 alias 名称，不改底层账号快照或挂载的 token
- `remove`：删除某个条目
- `export-env`：输出给 Claude Agent SDK 使用的环境变量
- `current`：显示最近一次给 CLI 选中的账号别名
- `whoami`：先做一次轻量同步，再显示 Claude 当前 live auth state、匹配到的 alias、auth method、subscription 和 quota 摘要

## Python API 🐍

最基本的用法：

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

当前公开接口：

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

也可以直接用顶层 helper：

```python
from claude_select import build_sdk_env

env = build_sdk_env("work")
```

`auto_refresh=True` 是显式参数。对 `cli` 类型 alias 来说，它会在返回数据前，先尝试跑一遍和 `claude-select refresh <alias>` 相同的轻量恢复流程：

- 先把该 alias 写回 Claude 当前 live auth state
- 执行一次 `claude -p "ping"`
- 再把刷新后的 live state 同步回本地 registry

这对 Python 调用方很有用：如果你希望程序在读取 env / quota 前尽量自动恢复一次，而不是要求用户先手动跑 CLI 维护命令，就可以打开这个参数。

兼容性说明：

- `build_sdk_env_auto()` 和 `pick_sdk_account()` 仍然保留导出，用于兼容旧版本，但现在会直接抛出 `AccountSelectionError`。
- 原因是：`claude setup-token` 生成的长期 token 是 inference-only，拿不到做可靠 quota 轮换所需的 profile / quota 数据。

quota 数据会在本地缓存 60 秒。`watch`、`whoami` 和重复的 CLI quota 读取都会复用这份缓存，而不是每次刷新都重新请求远端 usage 接口。

## 过期机制 ⏳

`claude-select` 不会自动 refresh token。

它只读取保存时记录下来的 `expiresAt`，然后推导状态：

- `healthy`：距离过期超过 1 小时
- `expiring_soon`：距离过期不超过 1 小时
- `expired`：已经过期
- `unknown`：没有记录到 `expiresAt`

如果某个 `cli` 账号已经过期：

- `select` 会失败
- `build_sdk_env()` 对该 alias 会失败
- 先尝试执行 `claude-select refresh <alias>`
- 如果 refresh 成功，Claude 会刷新 live session，而 `claude-select` 会把新状态同步回 registry
- 如果 refresh 失败，再执行 `claude-select relogin <alias>`

长期 `token` 条目不参与 `relogin`；如果你想替换它，就重新执行一次 `add-token`。

## 存储结构 🗃️

本地 registry 是一个 SQLite 数据库：

- macOS / Linux 默认位置：
  - `~/.config/claude-select/registry.db`
- 如果设置了 XDG：
  - `$XDG_CONFIG_HOME/claude-select/registry.db`

每个条目会保存：

- alias
- kind（`cli_snapshot` 或 `token`）
- email
- organization name / id
- account uuid
- captured time
- expiresAt
- last selected time
- `oauthAccount`
- `claudeAiOauth` credential payload

而 Claude 自己当前的 live state 依然是独立的：

- Claude 全局配置
- Claude credentials 文件或 macOS Keychain

本地 registry 是 source of truth。`select` 的作用就是把数据库里的某份 `cli` 快照再写回 Claude 当前 live state。

## 当前限制 ⚠️

- 只有 `cli` 条目支持 quota 监控、`watch`、`select`、`sync-current`、`refresh` 和 `relogin`。
- `token` 条目只是简单的 SDK 凭证。
- 工具不会自动 refresh OAuth token。
- 当前实现依赖 Claude 当前本地认证布局没有发生大改。
- 过期监测基于本地 `expiresAt`，不会对每条记录都主动发起远端认证探测。

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
