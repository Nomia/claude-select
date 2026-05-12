from __future__ import annotations

import json
import urllib.error

import pytest

from claude_select.exceptions import (
    AccountExistsError,
    AccountKindError,
    AccountSelectionError,
    AuthExpiredError,
)
from claude_select.manager import AuthManager, build_sdk_env_auto
from claude_select.models import AuthSnapshot


def test_capture_and_list_accounts(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )

    captured = manager.capture_current_account("work")
    accounts = manager.list_accounts()

    assert captured["alias"] == "work"
    assert accounts[0]["email"] == "work@example.com"


def test_select_account_writes_snapshot(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")

    selected = manager.select_account("work")

    assert selected["alias"] == "work"
    assert fake_auth_backend.written_snapshot is not None
    assert fake_auth_backend.written_snapshot.oauth_account["emailAddress"] == "work@example.com"


def test_build_sdk_env(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")

    env = manager.build_sdk_env("work", base_env={"PATH": "/bin", "ANTHROPIC_API_KEY": "x"})

    assert env["PATH"] == "/bin"
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "access-1"
    assert env["CLAUDE_CODE_OAUTH_SCOPES"] == "user:profile"
    assert "CLAUDE_CODE_OAUTH_REFRESH_TOKEN" not in env
    assert "ANTHROPIC_API_KEY" not in env


def test_add_token_account_and_build_sdk_env(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )

    captured = manager.add_token_account(
        "work-sdk",
        "long-lived-token",
        email="sdk@example.com",
        organization_name="SDK Org",
    )
    env = manager.build_sdk_env("work-sdk", base_env={"PATH": "/bin"})

    assert captured["auth_kind"] == "token"
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "long-lived-token"
    assert env["PATH"] == "/bin"


def test_resolve_token_metadata(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
        token_metadata_fetcher=lambda _token: {
            "emailAddress": "sdk@example.com",
            "organizationName": "SDK Org",
            "organizationUuid": "org-sdk",
            "accountUuid": "acct-sdk",
        },
    )

    metadata = manager.resolve_token_metadata("long-lived-token")

    assert metadata == {
        "email": "sdk@example.com",
        "organization_name": "SDK Org",
        "organization_id": "org-sdk",
        "account_uuid": "acct-sdk",
    }


def test_resolve_token_metadata_rejects_empty_token(
    registry, fake_auth_backend, fake_usage_provider
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )

    with pytest.raises(AccountSelectionError):
        manager.resolve_token_metadata("   ")


def test_resolve_token_metadata_falls_back_on_fetch_error(
    registry, fake_auth_backend, fake_usage_provider
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
        token_metadata_fetcher=lambda _token: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    metadata = manager.resolve_token_metadata("long-lived-token")

    assert metadata == {}


def test_probe_token_success(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
        token_metadata_fetcher=lambda _token: {
            "emailAddress": "sdk@example.com",
            "organizationName": "SDK Org",
        },
    )

    payload = manager.probe_token("long-lived-token")

    assert payload["valid"] is True
    assert payload["metadata"]["email"] == "sdk@example.com"
    assert payload["error"] is None


def test_probe_token_failure(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
        token_metadata_fetcher=lambda _token: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    payload = manager.probe_token("long-lived-token")

    assert payload["valid"] is False
    assert payload["metadata"] == {}
    assert payload["error"] == "boom"


def test_fetch_token_metadata_and_normalize_nested_payload(
    registry, fake_auth_backend, fake_usage_provider, monkeypatch
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {
                    "email": "sdk@example.com",
                    "organization": {"name": "SDK Org", "uuid": "org-sdk"},
                    "id": "acct-sdk",
                }
            ).encode("utf-8")

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout=10.0: FakeResponse(),
    )

    metadata = manager.resolve_token_metadata("long-lived-token")

    assert metadata == {
        "email": "sdk@example.com",
        "organization_name": "SDK Org",
        "organization_id": "org-sdk",
        "account_uuid": "acct-sdk",
    }


def test_fetch_token_metadata_tries_multiple_urls(
    registry, fake_auth_backend, fake_usage_provider, monkeypatch
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    calls: list[str] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return b'{"emailAddress":"sdk@example.com"}'

    def fake_urlopen(request, timeout=10.0):
        calls.append(request.full_url)
        if len(calls) == 1:
            raise urllib.error.URLError("boom")
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    metadata = manager.resolve_token_metadata("long-lived-token")

    assert metadata["email"] == "sdk@example.com"
    assert len(calls) == 2


class AliasUsageProvider:
    def __init__(self, by_alias: dict[str, dict[str, float]]):
        self.by_alias = by_alias

    def get_usage(self, snapshot: AuthSnapshot, cache_key: str):
        payload = self.by_alias[cache_key]
        return {
            "five_hour": {
                "used_percentage": payload["five_hour"],
                "resets_at": "2099-01-01T05:00:00Z",
            },
            "seven_day": {
                "used_percentage": payload["seven_day"],
                "resets_at": "2099-01-07T00:00:00Z",
            },
            "seven_day_opus": None,
            "extra_usage": None,
            "fetched_at": "2099-01-01T00:00:00Z",
            "stale": False,
            "error": None,
        }


def test_add_token_account_validates_inputs(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.add_token_account("work-sdk", "long-lived-token", email="sdk@example.com")

    with pytest.raises(AccountExistsError):
        manager.add_token_account(
            "work-sdk",
            "another-token",
            email="sdk@example.com",
            overwrite=False,
        )

    with pytest.raises(AccountSelectionError):
        manager.add_token_account("bad-sdk", "token", email="   ")


def test_pick_sdk_account_and_build_sdk_env_auto(registry, fake_auth_backend):
    usage_provider = AliasUsageProvider(
        {
            "alias:work-sdk-a": {"five_hour": 100.0, "seven_day": 40.0},
            "alias:work-sdk-b": {"five_hour": 25.0, "seven_day": 30.0},
        }
    )
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=usage_provider,
    )
    manager.add_token_account("work-sdk-a", "token-a", email="a@example.com")
    manager.add_token_account("work-sdk-b", "token-b", email="b@example.com")

    selected = manager.pick_sdk_account()
    env = manager.build_sdk_env_auto(base_env={"PATH": "/bin"})

    assert selected["alias"] == "work-sdk-b"
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "token-b"
    assert env["CLAUDE_SELECT_ALIAS"] == "work-sdk-b"
    assert env["PATH"] == "/bin"


def test_pick_sdk_account_prefers_requested_alias_when_available(registry, fake_auth_backend):
    usage_provider = AliasUsageProvider(
        {
            "alias:work-sdk-a": {"five_hour": 10.0, "seven_day": 20.0},
            "alias:work-sdk-b": {"five_hour": 5.0, "seven_day": 10.0},
        }
    )
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=usage_provider,
    )
    manager.add_token_account("work-sdk-a", "token-a", email="a@example.com")
    manager.add_token_account("work-sdk-b", "token-b", email="b@example.com")

    selected = manager.pick_sdk_account(preferred_alias="work-sdk-a")

    assert selected["alias"] == "work-sdk-a"


def test_pick_sdk_account_fails_without_available_tokens(registry, fake_auth_backend):
    usage_provider = AliasUsageProvider(
        {
            "alias:work-sdk-a": {"five_hour": 100.0, "seven_day": 100.0},
        }
    )
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=usage_provider,
    )
    manager.add_token_account("work-sdk-a", "token-a", email="a@example.com")

    with pytest.raises(AccountSelectionError):
        manager.pick_sdk_account()


def test_build_sdk_env_auto_helper_uses_registry(registry, fake_auth_backend, monkeypatch):
    usage_provider = AliasUsageProvider(
        {
            "alias:work-sdk-a": {"five_hour": 25.0, "seven_day": 25.0},
        }
    )
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=usage_provider,
    )
    manager.add_token_account("work-sdk-a", "token-a", email="a@example.com")
    monkeypatch.setattr("claude_select.manager.AuthManager", lambda: manager)

    env = build_sdk_env_auto()

    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "token-a"
    assert env["CLAUDE_SELECT_ALIAS"] == "work-sdk-a"


def test_expired_account_rejected(registry, fake_auth_backend, fake_usage_provider):
    fake_auth_backend.snapshot.credentials["claudeAiOauth"]["expiresAt"] = 1
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")

    with pytest.raises(AuthExpiredError):
        manager.select_account("work")


def test_expired_account_export_rejected(registry, fake_auth_backend, fake_usage_provider):
    fake_auth_backend.snapshot.credentials["claudeAiOauth"]["expiresAt"] = 1
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")

    with pytest.raises(AuthExpiredError):
        manager.export_sdk_auth("work")


def test_remove_account(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    manager.remove_account("work")

    assert manager.list_accounts() == []


def test_select_token_account_rejected(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.add_token_account("work-sdk", "long-lived-token", email="sdk@example.com")

    with pytest.raises(AccountKindError):
        manager.select_account("work-sdk")


def test_relogin_and_export_sdk_auth(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    fake_auth_backend.snapshot.oauth_account["emailAddress"] = "next@example.com"

    updated = manager.relogin_account("work")
    exported = manager.export_sdk_auth("work")

    assert updated["email"] == "next@example.com"
    assert exported["email"] == "next@example.com"
    assert exported["credentials"]["claudeAiOauth"]["accessToken"] == "access-1"


def test_relogin_token_account_rejected(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.add_token_account("work-sdk", "long-lived-token", email="sdk@example.com")

    with pytest.raises(AccountKindError):
        manager.relogin_account("work-sdk")


def test_capture_without_overwrite_rejected(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")

    with pytest.raises(AccountExistsError):
        manager.capture_current_account("work", overwrite=False)


def test_render_table_and_current_alias(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )

    assert manager.current_alias() is None
    assert manager.render_table() == "No accounts have been captured yet."

    manager.capture_current_account("work")
    manager.select_account("work")

    rendered = manager.render_table(include_usage=True)
    assert "Kind" in rendered
    assert "work@example.com" in rendered
    assert "76.0%" in rendered
    assert manager.current_alias() == "work"


def test_current_live_account_and_render(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")

    payload = manager.current_live_account()
    rendered = manager.render_current_live_account()

    assert payload["matched_alias"] == "work"
    assert payload["organization_name"] == "Example Org"
    assert payload["quota_5h_left"] == "76.0%"
    assert "Current Claude live account" in rendered
    assert "matched alias: work" in rendered
    assert "organization: Example Org" in rendered
    assert "5h quota left: 76.0%" in rendered


def test_list_accounts_with_usage(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")

    rows = manager.list_accounts(include_usage=True)

    assert rows[0]["quota_5h_left"] == "76.0%"
    assert rows[0]["quota_7d_left"] == "59.0%"
    assert rows[0]["auth_kind"] == "cli_snapshot"


def test_get_live_quota(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")

    quota = manager.get_live_quota()

    assert quota["alias"] == "work"
    assert quota["available"] is True
    assert quota["quota_5h_left"] == "76.0%"
    assert quota["quota_7d_left"] == "59.0%"
    assert quota["five_hour"]["used_percentage"] == 24.0


def test_get_account_quota(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")

    quota = manager.get_account_quota("work")

    assert quota["alias"] == "work"
    assert quota["email"] == "work@example.com"
    assert quota["organization_name"] == "Example Org"
    assert quota["quota_5h_reset"] != "unknown"


def test_list_account_quotas(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    fake_auth_backend.snapshot.oauth_account["emailAddress"] = "personal@example.com"
    manager.capture_current_account("personal")

    rows = manager.list_account_quotas()

    assert [row["alias"] for row in rows] == ["personal", "work"]
    assert all(row["available"] is True for row in rows)


def test_sync_current_account_updates_registry(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    fake_auth_backend.snapshot.credentials["claudeAiOauth"]["accessToken"] = "access-2"
    fake_auth_backend.snapshot.credentials["claudeAiOauth"]["expiresAt"] = 4102448400000

    payload = manager.sync_current_account()
    refreshed = manager.get_account("work")

    assert payload["status"] == "synced"
    assert payload["matched_alias"] == "work"
    assert payload["updated"] is True
    assert refreshed.snapshot.credentials["claudeAiOauth"]["accessToken"] == "access-2"
    assert refreshed.record.expires_at == 4102448400000


def test_sync_current_account_unchanged(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")

    payload = manager.sync_current_account()

    assert payload["status"] == "unchanged"
    assert payload["matched_alias"] == "work"
    assert payload["updated"] is False


def test_sync_current_account_unregistered(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )

    payload = manager.sync_current_account()

    assert payload["status"] == "unregistered"
    assert payload["matched_alias"] is None
    assert payload["updated"] is False


def test_sync_current_account_ambiguous(
    registry, sample_snapshot, fake_auth_backend, fake_usage_provider
):
    registry.upsert_account(
        alias="work-a",
        auth_kind="cli_snapshot",
        email="work@example.com",
        organization_name="Example Org",
        organization_id="org-123",
        account_uuid="",
        captured_at="2026-05-10T00:00:00Z",
        expires_at=4102444800000,
        last_selected_at=None,
        source="claude_cli",
        snapshot=sample_snapshot,
    )
    registry.upsert_account(
        alias="work-b",
        auth_kind="cli_snapshot",
        email="work@example.com",
        organization_name="Example Org",
        organization_id="org-123",
        account_uuid="",
        captured_at="2026-05-10T00:00:00Z",
        expires_at=4102444800000,
        last_selected_at=None,
        source="claude_cli",
        snapshot=sample_snapshot,
    )
    fake_auth_backend.snapshot.oauth_account["accountUuid"] = ""
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )

    payload = manager.sync_current_account()

    assert payload["status"] == "ambiguous"
    assert set(payload["candidates"]) == {"work-a", "work-b"}


def test_choose_alias_interactively(registry, fake_auth_backend, fake_usage_provider, monkeypatch):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    monkeypatch.setattr("builtins.input", lambda _prompt="": "work")

    assert manager.choose_alias_interactively() == "work"


def test_invalid_alias_rejected(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )

    with pytest.raises(AccountSelectionError):
        manager.capture_current_account("bad alias")
