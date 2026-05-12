from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_select.exceptions import ConfigError
from claude_select.live_state import (
    ClaudeAuthBackend,
    FileCredentialStore,
    MacOSKeychainCredentialStore,
    create_default_credential_store,
)
from claude_select.models import AuthSnapshot


def test_file_credential_store_round_trip(tmp_path):
    path = tmp_path / ".claude" / ".credentials.json"
    store = FileCredentialStore(path)
    payload = {"claudeAiOauth": {"accessToken": "token"}}

    store.write(payload)

    assert store.read() == payload


def test_file_credential_store_missing_file(tmp_path):
    store = FileCredentialStore(tmp_path / "missing.json")

    with pytest.raises(ConfigError):
        store.read()


def test_auth_backend_read_snapshot(tmp_path):
    config_path = tmp_path / ".claude.json"
    credentials_path = tmp_path / ".claude" / ".credentials.json"
    config_path.write_text(
        json.dumps({"oauthAccount": {"emailAddress": "user@example.com"}}),
        encoding="utf-8",
    )
    FileCredentialStore(credentials_path).write(
        {"claudeAiOauth": {"accessToken": "token", "expiresAt": 4102444800000}}
    )

    backend = ClaudeAuthBackend(
        config_path=config_path,
        credential_store=FileCredentialStore(credentials_path),
        backup_dir=tmp_path / "backups",
    )

    snapshot = backend.read_snapshot()

    assert snapshot.oauth_account["emailAddress"] == "user@example.com"


def test_auth_backend_write_snapshot(tmp_path):
    config_path = tmp_path / ".claude.json"
    credentials_path = tmp_path / ".claude" / ".credentials.json"
    config_path.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
    store = FileCredentialStore(credentials_path)
    store.write({"claudeAiOauth": {"accessToken": "old"}})
    backend = ClaudeAuthBackend(
        config_path=config_path,
        credential_store=store,
        backup_dir=tmp_path / "backups",
    )
    snapshot = AuthSnapshot(
        oauth_account={"emailAddress": "next@example.com"},
        credentials={"claudeAiOauth": {"accessToken": "next"}},
    )

    backend.write_snapshot(snapshot)

    assert backend.read_snapshot().oauth_account["emailAddress"] == "next@example.com"
    assert json.loads(config_path.read_text(encoding="utf-8"))["theme"] == "dark"
    assert (tmp_path / "backups" / ".claude.json").exists()
    targets = backend.describe_targets()
    assert str(config_path) in targets[0]
    assert str(credentials_path) in targets[1]


def test_auth_backend_rejects_invalid_config(tmp_path):
    config_path = tmp_path / ".claude.json"
    credentials_path = tmp_path / ".claude" / ".credentials.json"
    config_path.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
    FileCredentialStore(credentials_path).write({"claudeAiOauth": {"accessToken": "token"}})
    backend = ClaudeAuthBackend(
        config_path=config_path,
        credential_store=FileCredentialStore(credentials_path),
    )

    with pytest.raises(ConfigError):
        backend.read_snapshot()


def test_auth_backend_rejects_invalid_credentials(tmp_path):
    config_path = tmp_path / ".claude.json"
    credentials_path = tmp_path / ".claude" / ".credentials.json"
    config_path.write_text(
        json.dumps({"oauthAccount": {"emailAddress": "user@example.com"}}),
        encoding="utf-8",
    )
    FileCredentialStore(credentials_path).write({"notOauth": True})
    backend = ClaudeAuthBackend(
        config_path=config_path,
        credential_store=FileCredentialStore(credentials_path),
    )

    with pytest.raises(ConfigError):
        backend.read_snapshot()


def test_create_default_credential_store_file_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / ".claude"))
    monkeypatch.setattr("platform.system", lambda: "Linux")

    store = create_default_credential_store()

    assert isinstance(store, FileCredentialStore)


def test_macos_keychain_store(monkeypatch):
    calls: list[list[str]] = []

    class Result:
        def __init__(self, *, stdout: str = "", stderr: str = "", returncode: int = 0):
            self.stdout = stdout
            self.stderr = stderr
            self.returncode = returncode

    def fake_run(command, **_kwargs):
        calls.append(command)
        if command[:2] == ["security", "find-generic-password"]:
            return Result(stdout='{"claudeAiOauth":{"accessToken":"token"}}')
        return Result(returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)
    store = MacOSKeychainCredentialStore(account_name="tester")

    assert store.read()["claudeAiOauth"]["accessToken"] == "token"
    store.write({"claudeAiOauth": {"accessToken": "next"}})

    assert calls[0][:2] == ["security", "find-generic-password"]
    assert calls[1][:2] == ["security", "add-generic-password"]


def test_auth_backend_describe_targets_keychain():
    backend = ClaudeAuthBackend(
        config_path=Path("/tmp/.claude.json"),
        credential_store=MacOSKeychainCredentialStore(account_name="tester"),
    )

    targets = backend.describe_targets()

    assert targets[0] == "config: /tmp/.claude.json"
    assert "macOS Keychain" in targets[1]


def test_auth_backend_run_auth_login(monkeypatch):
    calls: list[list[str]] = []

    class Result:
        returncode = 0

    monkeypatch.setattr("shutil.which", lambda _name: "/usr/local/bin/claude")
    monkeypatch.setattr(
        "subprocess.run",
        lambda command, **_kwargs: calls.append(command) or Result(),
    )

    backend = ClaudeAuthBackend()

    assert backend.run_auth_login() is True
    assert calls == [["/usr/local/bin/claude", "auth", "login"]]


def test_auth_backend_read_auth_status(monkeypatch):
    class Result:
        stdout = json.dumps({"loggedIn": True, "authMethod": "claude.ai"})

    monkeypatch.setattr("shutil.which", lambda _name: "/usr/local/bin/claude")
    monkeypatch.setattr("subprocess.run", lambda *_args, **_kwargs: Result())

    backend = ClaudeAuthBackend()

    assert backend.read_auth_status() == {
        "loggedIn": True,
        "authMethod": "claude.ai",
    }


def test_auth_backend_read_auth_status_falls_back(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)

    backend = ClaudeAuthBackend()

    assert backend.read_auth_status() is None


def test_auth_backend_run_print_prompt(monkeypatch):
    class Result:
        returncode = 0
        stdout = "pong\n"
        stderr = ""

    monkeypatch.setattr("shutil.which", lambda _name: "/usr/local/bin/claude")
    monkeypatch.setattr("subprocess.run", lambda *_args, **_kwargs: Result())

    backend = ClaudeAuthBackend()

    ok, output = backend.run_print_prompt("ping")

    assert ok is True
    assert output == "pong"


def test_auth_backend_run_print_prompt_failure(monkeypatch):
    class Result:
        returncode = 1
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr("shutil.which", lambda _name: "/usr/local/bin/claude")
    monkeypatch.setattr("subprocess.run", lambda *_args, **_kwargs: Result())

    backend = ClaudeAuthBackend()

    ok, output = backend.run_print_prompt("ping")

    assert ok is False
    assert output == "boom"
