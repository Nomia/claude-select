# claude-select 🔐

[![PyPI version](https://img.shields.io/pypi/v/claude-select)](https://pypi.org/project/claude-select/)
[![Python versions](https://img.shields.io/pypi/pyversions/claude-select)](https://pypi.org/project/claude-select/)
[![CI](https://github.com/Nomia/claude-select/actions/workflows/ci.yml/badge.svg)](https://github.com/Nomia/claude-select/actions/workflows/ci.yml)

[English README](./README.md)

`claude-select` 是一个本地 Claude 多账号认证库和选择器，适合一台机器上同时使用多个 Claude 账号的人。

它会读取当前 Claude CLI 的登录态，把每个账号保存成一份本地快照，存进 SQLite 数据库里，并提供：

- 一个命令行工具，用来查看账号表、监控过期状态、把某个账号切回当前 Claude CLI
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

每个账号的流程是：

1. 给账号起一个别名，比如 `work`、`personal`
2. 在 Claude Code 里完成 `/login`
3. 回到向导，让 `claude-select` 把当前登录态采集进本地数据库

后续也可以单独新增：

```bash
claude-select add work
claude-select add personal
```

### 2. 看当前数据库里有哪些账号

```bash
claude-select list
claude-select watch
```

展示效果大致如下：

```text
Alias     Email             Status          Expires In  Last Selected
--------  ----------------  --------------  ----------  -------------
personal  a@example.com     healthy         18h 12m     2h ago
work      b@company.com     expiring_soon   1h 05m      -
team-a    c@company.com     expired         expired     3d ago
```

### 3. 给 Claude CLI 切换当前账号

```bash
claude-select select work
```

这个命令会从本地数据库读取 `work` 的认证快照，再写回 Claude 当前 live auth backend：

- macOS：Keychain + Claude 配置
- Linux / Windows：Claude credentials 文件 + Claude 配置

### 4. 在 Python 里使用某个账号

```python
from claude_select import AuthManager
from claude_code_sdk import ClaudeAgentOptions, query

manager = AuthManager()
env = manager.build_sdk_env("work")

options = ClaudeAgentOptions(env=env)

async for message in query(prompt="analyze this repo", options=options):
    print(message)
```

Python 这边和 CLI 共用同一份本地数据库，但它不会改写 Claude 当前登录态。

## CLI 命令 🧰

```bash
claude-select init
claude-select add <alias>
claude-select relogin <alias>
claude-select list
claude-select watch
claude-select select [alias]
claude-select remove <alias>
claude-select export-env <alias> --json
claude-select current
```

各命令含义：

- `init`：首次引导录入多个账号
- `add`：把当前 Claude 登录态录进数据库
- `relogin`：让用户重新登录后，用新的登录态覆盖某个已存在账号
- `list`：查看当前账号表
- `watch`：持续刷新账号表
- `select`：把某个已保存账号写回当前 Claude CLI 登录态
- `remove`：删除某个账号
- `export-env`：输出给 Claude Agent SDK 使用的环境变量
- `current`：显示最近一次给 CLI 选中的账号别名

## Python API 🐍

最基本的用法：

```python
from claude_select import AuthManager

manager = AuthManager()

accounts = manager.list_accounts()
details = manager.get_account("work")
env = manager.build_sdk_env("work")
auth_payload = manager.export_sdk_auth("work")
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
    def export_sdk_auth(self, alias: str) -> dict: ...
    def current_alias(self) -> str | None: ...
    def render_table(self) -> str: ...
```

也可以直接用顶层 helper：

```python
from claude_select import build_sdk_env

env = build_sdk_env("work")
```

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
