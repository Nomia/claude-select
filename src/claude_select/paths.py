"""Path helpers for claude-select and Claude auth files."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path


def get_claude_config_home(env: Mapping[str, str] | None = None) -> Path:
    """Return Claude's config directory, honoring CLAUDE_CONFIG_DIR."""
    resolved_env = env if env is not None else os.environ
    value = resolved_env.get("CLAUDE_CONFIG_DIR")
    if value:
        return Path(value).expanduser()
    return Path.home() / ".claude"


def get_global_config_path(env: Mapping[str, str] | None = None) -> Path:
    """Return Claude's global config path."""
    claude_home = get_claude_config_home(env)
    legacy = claude_home / ".config.json"
    if legacy.exists():
        return legacy
    resolved_env = env if env is not None else os.environ
    config_root = (
        Path(resolved_env["CLAUDE_CONFIG_DIR"]).expanduser()
        if resolved_env.get("CLAUDE_CONFIG_DIR")
        else Path.home()
    )
    return config_root / ".claude.json"


def get_credentials_path(env: Mapping[str, str] | None = None) -> Path:
    """Return Claude's file-backed credentials path."""
    return get_claude_config_home(env) / ".credentials.json"


def get_default_store_root(env: Mapping[str, str] | None = None) -> Path:
    """Return the claude-select storage root."""
    resolved_env = env if env is not None else os.environ
    xdg_config_home = resolved_env.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home).expanduser() / "claude-select"
    return Path.home() / ".config" / "claude-select"


def get_registry_db_path(env: Mapping[str, str] | None = None) -> Path:
    """Return the SQLite registry path."""
    return get_default_store_root(env) / "registry.db"

