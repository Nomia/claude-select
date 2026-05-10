from __future__ import annotations

import pytest

from claude_select.exceptions import AccountExistsError, AccountSelectionError, AuthExpiredError
from claude_select.manager import AuthManager


def test_capture_and_list_accounts(registry, fake_auth_backend):
    manager = AuthManager(registry=registry, auth_backend=fake_auth_backend)

    captured = manager.capture_current_account("work")
    accounts = manager.list_accounts()

    assert captured["alias"] == "work"
    assert accounts[0]["email"] == "work@example.com"


def test_select_account_writes_snapshot(registry, fake_auth_backend):
    manager = AuthManager(registry=registry, auth_backend=fake_auth_backend)
    manager.capture_current_account("work")

    selected = manager.select_account("work")

    assert selected["alias"] == "work"
    assert fake_auth_backend.written_snapshot is not None
    assert fake_auth_backend.written_snapshot.oauth_account["emailAddress"] == "work@example.com"


def test_build_sdk_env(registry, fake_auth_backend):
    manager = AuthManager(registry=registry, auth_backend=fake_auth_backend)
    manager.capture_current_account("work")

    env = manager.build_sdk_env("work", base_env={"PATH": "/bin", "ANTHROPIC_API_KEY": "x"})

    assert env["PATH"] == "/bin"
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "access-1"
    assert env["CLAUDE_CODE_OAUTH_SCOPES"] == "user:profile"
    assert "CLAUDE_CODE_OAUTH_REFRESH_TOKEN" not in env
    assert "ANTHROPIC_API_KEY" not in env


def test_expired_account_rejected(registry, fake_auth_backend):
    fake_auth_backend.snapshot.credentials["claudeAiOauth"]["expiresAt"] = 1
    manager = AuthManager(registry=registry, auth_backend=fake_auth_backend)
    manager.capture_current_account("work")

    with pytest.raises(AuthExpiredError):
        manager.select_account("work")


def test_remove_account(registry, fake_auth_backend):
    manager = AuthManager(registry=registry, auth_backend=fake_auth_backend)
    manager.capture_current_account("work")
    manager.remove_account("work")

    assert manager.list_accounts() == []


def test_relogin_and_export_sdk_auth(registry, fake_auth_backend):
    manager = AuthManager(registry=registry, auth_backend=fake_auth_backend)
    manager.capture_current_account("work")
    fake_auth_backend.snapshot.oauth_account["emailAddress"] = "next@example.com"

    updated = manager.relogin_account("work")
    exported = manager.export_sdk_auth("work")

    assert updated["email"] == "next@example.com"
    assert exported["email"] == "next@example.com"
    assert exported["credentials"]["claudeAiOauth"]["accessToken"] == "access-1"


def test_capture_without_overwrite_rejected(registry, fake_auth_backend):
    manager = AuthManager(registry=registry, auth_backend=fake_auth_backend)
    manager.capture_current_account("work")

    with pytest.raises(AccountExistsError):
        manager.capture_current_account("work", overwrite=False)


def test_render_table_and_current_alias(registry, fake_auth_backend):
    manager = AuthManager(registry=registry, auth_backend=fake_auth_backend)

    assert manager.current_alias() is None
    assert manager.render_table() == "No accounts have been captured yet."

    manager.capture_current_account("work")
    manager.select_account("work")

    rendered = manager.render_table()
    assert "work@example.com" in rendered
    assert manager.current_alias() == "work"


def test_choose_alias_interactively(registry, fake_auth_backend, monkeypatch):
    manager = AuthManager(registry=registry, auth_backend=fake_auth_backend)
    manager.capture_current_account("work")
    monkeypatch.setattr("builtins.input", lambda _prompt="": "work")

    assert manager.choose_alias_interactively() == "work"


def test_invalid_alias_rejected(registry, fake_auth_backend):
    manager = AuthManager(registry=registry, auth_backend=fake_auth_backend)

    with pytest.raises(AccountSelectionError):
        manager.capture_current_account("bad alias")
