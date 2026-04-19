# claude-select 🚀

[English](./README.md) | [简体中文](./README.zh-CN.md)

`claude-select` 是一个本地 SDK + CLI 工具，用来管理多个 Claude 认证 profile，覆盖两类场景：

- 全局 Claude Code CLI 登录态切换
- Python 程序中 Claude Agent SDK 的按调用切换

## 功能概览 ✨

- 支持捕获当前 Claude CLI 登录态并保存为 profile
- 支持在多个本地 profile 之间切换全局 CLI 账号
- 支持在 Python 里通过 `build_sdk_env()` 为单次 Agent SDK 调用注入认证环境
- 支持 OAuth token 过期检测与 refresh
- 支持默认 SDK profile
- 提供测试、lint、type-check、CI 和发布配置

## 适合什么场景 🎯

- 你有多个 Claude 账号，想在本机 CLI 间快速切换
- 你写了基于 Claude Agent SDK 的 Python 工具，希望显式指定“这次调用用哪个账号”
- 你不想让 Python 代码依赖当前全局 CLI 登录账号

## 核心设计 🧠

项目把状态拆成三层：

1. `profiles`
   所有共享的认证档案，CLI 和 Python 共用
2. `current_cli_profile`
   当前写入 Claude live state 的全局 CLI profile
3. `default_sdk_profile`
   Python 调用方未显式指定 profile 时使用的默认值

这意味着：

- CLI 切换是全局行为
- Python Agent SDK 切换是“单次调用级别”的行为

## 安装 📦

```bash
pip install claude-select
```

也可以从源码安装：

```bash
git clone https://github.com/Nomia/claude-select.git
cd claude-select
python3 -m pip install -e ".[dev]"
```

## 快速开始 ⚡

### 1. 先安装 `claude-select`

```bash
pip install claude-select
```

如果你已经安装过，可以直接跳到下一步。

### 2. 先用 Claude 官方方式登录

```bash
claude
```

然后在 Claude 中执行 `/login`。

### 3. 把当前账号保存成 profile

```bash
claude-select capture work
```

如果你再登录另一个账号，也可以继续保存：

```bash
claude-select capture personal
```

### 4. 切换全局 CLI 账号

```bash
claude-select use work
claude-select use personal
claude-select list
claude-select current
```

### 5. 在 Python Agent SDK 中使用某个 profile

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

## CLI 命令 🖥️

当前已实现：

```bash
claude-select capture <profile>
claude-select sync [<profile>]
claude-select list
claude-select current
claude-select use <profile>
claude-select inspect <profile>
claude-select remove <profile>
claude-select set-default-sdk <profile>
```

这些命令分别用于：

- `capture`: 捕获当前 Claude CLI live state
- `sync`: 用当前 live state 更新一个已有 profile
- `list`: 列出所有本地 profile
- `current`: 查看当前 CLI profile 和默认 SDK profile
- `use`: 切换全局 CLI 账号
- `inspect`: 查看某个 profile 详情
- `remove`: 删除本地 profile
- `set-default-sdk`: 设置默认 SDK profile

## Python API 🐍

最常用的是这两个入口：

```python
from claude_select import ProfileManager, build_sdk_env
```

示例：

```python
from claude_select import build_sdk_env
from claude_code_sdk import ClaudeAgentOptions

env = build_sdk_env("work")
options = ClaudeAgentOptions(env=env)
```

### 为什么推荐这种方式

- 显式
- 不污染全局环境变量
- 适合并发任务
- 一个进程里可以安全使用多个 profile

## 存储结构 💾

默认本地存储结构类似：

```text
~/.config/claude-select/
  state.json
  secrets/
    work.json
    personal.json
```

- `state.json` 存非敏感元数据和当前指针
- `secrets/*.json` 存 OAuth 凭证等敏感信息

Claude 自己的 live state 仍然在它原本的位置，例如：

- `~/.claude.json` 或 `~/.claude/.config.json`
- `~/.claude/.credentials.json`
- 某些平台上的系统安全存储

## Token 过期怎么处理 🔄

对 OAuth profile：

- access token 快过期时，优先尝试 refresh
- refresh 成功后，更新本地 store
- refresh 失败后，将 profile 标记为 `reauth_required`

对 CLI：

- 允许切换
- 但会提示你重新 `/login`
- 登录后再执行 `capture` 或 `sync`

对 Python SDK：

- `build_sdk_env()` 会先尝试 refresh
- 如果失败，会抛出明确异常

## 当前限制 ⚠️

- 当前主路径主要支持 OAuth profile
- 这是一个面向本地单用户机器的工具
- 完整的 Claude 运行进程检测还没有实现
- 更广泛的系统 keyring 支持还可以继续增强

## 开发与质量 🛠️

本项目包含：

- `pytest`
- `ruff`
- `mypy`
- GitHub Actions CI
- 打包与 `twine check`

本地开发：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e ".[dev]"
```

运行完整检查：

```bash
ruff check .
ruff format --check .
mypy
python3 -m pytest
python3 -m build
python3 -m twine check dist/*
```

## 项目状态 ✅

当前版本已经：

- 发布到 GitHub
- 支持 PyPI Trusted Publishing
- 通过测试、类型检查和打包校验

如果你更关心实现细节、数据模型和发布流程，可以继续看英文版 README，它保留了更完整的设计说明。
