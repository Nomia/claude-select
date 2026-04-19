from __future__ import annotations

import json

import pytest

from claude_switch.exceptions import ConfigError
from claude_switch.live_state import (
    ClaudeLiveStateBackend,
    FileCredentialStore,
    MacOSKeychainCredentialStore,
)
from claude_switch.models import LiveState


def test_file_credential_store_round_trip(tmp_path):
    path = tmp_path / ".claude" / ".credentials.json"
    store = FileCredentialStore(path)
    payload = {"claudeAiOauth": {"accessToken": "token"}}

    store.write(payload)
    loaded = store.read()

    assert loaded == payload

    backup_dir = tmp_path / "backups"
    store.backup(backup_dir)
    assert (backup_dir / ".credentials.json").exists()


def test_live_state_backend_read_write_round_trip(tmp_path):
    config_path = tmp_path / ".claude.json"
    credentials_path = tmp_path / ".claude" / ".credentials.json"
    config_path.write_text(
        json.dumps({"oauthAccount": {"emailAddress": "user@example.com"}, "theme": "dark"}),
        encoding="utf-8",
    )
    FileCredentialStore(credentials_path).write(
        {"claudeAiOauth": {"accessToken": "token", "refreshToken": "refresh"}}
    )

    backend = ClaudeLiveStateBackend(
        config_path=config_path,
        credential_store=FileCredentialStore(credentials_path),
        backup_dir=tmp_path / "backups",
    )
    live_state = backend.read()
    assert live_state.config["theme"] == "dark"

    next_state = LiveState(
        config={"oauthAccount": {"emailAddress": "next@example.com"}, "theme": "light"},
        credentials={"claudeAiOauth": {"accessToken": "next-token"}},
    )
    backend.write(next_state)

    assert backend.read().config["oauthAccount"]["emailAddress"] == "next@example.com"
    assert (tmp_path / "backups" / ".claude.json").exists()


def test_live_state_backend_raises_on_invalid_config(tmp_path):
    config_path = tmp_path / ".claude.json"
    credentials_path = tmp_path / ".claude" / ".credentials.json"
    config_path.write_text(json.dumps({"notOAuth": True}), encoding="utf-8")
    FileCredentialStore(credentials_path).write({"claudeAiOauth": {"accessToken": "token"}})

    backend = ClaudeLiveStateBackend(
        config_path=config_path,
        credential_store=FileCredentialStore(credentials_path),
    )

    with pytest.raises(ConfigError):
        backend.read()


def test_macos_keychain_store(monkeypatch, tmp_path):
    calls = []

    def fake_run(args, check=False, capture_output=False, text=False):
        calls.append(args)

        class Result:
            returncode = 0
            stdout = json.dumps({"claudeAiOauth": {"accessToken": "token"}})
            stderr = ""

        if check and args[:2] == ["security", "find-generic-password"]:
            return Result()
        return Result()

    monkeypatch.setattr("claude_switch.live_state.subprocess.run", fake_run)

    store = MacOSKeychainCredentialStore(account_name="tester")
    loaded = store.read()
    store.write({"claudeAiOauth": {"accessToken": "next"}})
    store.backup(tmp_path / "backup")

    assert loaded["claudeAiOauth"]["accessToken"] == "token"
    assert calls[0][:2] == ["security", "find-generic-password"]
    assert calls[1][:2] == ["security", "add-generic-password"]
    assert (tmp_path / "backup" / "keychain-credentials.json").exists()
