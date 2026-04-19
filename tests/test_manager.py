from __future__ import annotations

import pytest

from claude_switch.exceptions import ProfileReauthRequired
from claude_switch.manager import ProfileManager


def test_capture_and_switch_updates_live_state(store, fake_live_backend):
    manager = ProfileManager(store=store, live_state_backend=fake_live_backend)

    captured = manager.capture_cli_profile("work")
    switched = manager.switch_cli("work")

    assert captured["id"] == "work"
    assert switched["id"] == "work"
    assert fake_live_backend.written_state is not None
    assert (
        fake_live_backend.written_state.config["oauthAccount"]["emailAddress"] == "work@example.com"
    )
    assert manager.get_current_cli_profile() == "work"


def test_build_sdk_env_removes_conflicting_auth_vars(store, fake_live_backend):
    manager = ProfileManager(store=store, live_state_backend=fake_live_backend)
    manager.capture_cli_profile("work")

    env = manager.build_sdk_env(
        "work",
        base_env={
            "PATH": "/bin",
            "ANTHROPIC_API_KEY": "should-go-away",
            "CLAUDE_CODE_USE_BEDROCK": "1",
        },
    )

    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "access-1"
    assert env["CLAUDE_CODE_OAUTH_REFRESH_TOKEN"] == "refresh-1"
    assert env["PATH"] == "/bin"
    assert "ANTHROPIC_API_KEY" not in env
    assert "CLAUDE_CODE_USE_BEDROCK" not in env


def test_build_sdk_env_refreshes_expired_token(store, fake_live_backend):
    fake_live_backend._live_state.credentials["claudeAiOauth"]["expiresAt"] = 1
    manager = ProfileManager(
        store=store,
        live_state_backend=fake_live_backend,
        refresh_request=lambda refresh_token: {
            "access_token": f"fresh-{refresh_token}",
            "refresh_token": "fresh-refresh",
            "expires_in": 3600,
            "scope": "user:profile",
        },
    )
    manager.capture_cli_profile("work")

    env = manager.build_sdk_env("work", base_env={})

    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "fresh-refresh-1"
    inspected = manager.inspect_profile("work")
    assert inspected["last_refresh_at"] is not None
    assert inspected["auth_state"] in {"ok", "expiring_soon"}


def test_build_sdk_env_raises_when_refresh_fails(store, fake_live_backend):
    fake_live_backend._live_state.credentials["claudeAiOauth"]["expiresAt"] = 1
    manager = ProfileManager(
        store=store,
        live_state_backend=fake_live_backend,
        refresh_request=lambda _refresh_token: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    manager.capture_cli_profile("work")

    with pytest.raises(ProfileReauthRequired):
        manager.build_sdk_env("work", base_env={})

    inspected = manager.inspect_profile("work")
    assert inspected["auth_state"] == "reauth_required"


def test_sync_set_default_and_remove_profile(store, fake_live_backend):
    manager = ProfileManager(store=store, live_state_backend=fake_live_backend)
    manager.capture_cli_profile("work")

    fake_live_backend._live_state.config["oauthAccount"]["organizationName"] = "Updated Org"
    synced = manager.sync_cli_profile("work")
    manager.set_default_sdk_profile("work")

    assert synced["organization_name"] == "Updated Org"
    assert manager.get_default_sdk_profile() == "work"

    manager.remove_profile("work")

    assert manager.list_profiles() == []
