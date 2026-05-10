from __future__ import annotations

from claude_select.paths import (
    get_claude_config_home,
    get_credentials_path,
    get_default_store_root,
    get_global_config_path,
    get_registry_db_path,
)


def test_paths_respect_env(tmp_path):
    env = {
        "CLAUDE_CONFIG_DIR": str(tmp_path / "claude-home"),
        "XDG_CONFIG_HOME": str(tmp_path / "xdg"),
    }

    assert get_claude_config_home(env) == tmp_path / "claude-home"
    assert get_credentials_path(env) == tmp_path / "claude-home" / ".credentials.json"
    assert get_global_config_path(env) == tmp_path / "claude-home" / ".claude.json"
    assert get_default_store_root(env) == tmp_path / "xdg" / "claude-select"
    assert get_registry_db_path(env) == tmp_path / "xdg" / "claude-select" / "registry.db"


def test_global_config_prefers_legacy_file(tmp_path):
    env = {"CLAUDE_CONFIG_DIR": str(tmp_path / "claude-home")}
    legacy = tmp_path / "claude-home" / ".config.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("{}", encoding="utf-8")

    assert get_global_config_path(env) == legacy
