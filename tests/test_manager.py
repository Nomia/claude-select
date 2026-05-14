from __future__ import annotations

import io
import json
import urllib.error

import pytest

from claude_select.exceptions import (
    AccountExistsError,
    AccountKindError,
    AccountSelectionError,
    AuthExpiredError,
    ConfigError,
)
from claude_select.manager import AuthManager, build_sdk_env, build_sdk_env_auto
from claude_select.models import AUTH_KIND_CLI_SNAPSHOT, AuthSnapshot


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


def test_refresh_account_uses_print_probe(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    details = manager.get_account("work")
    manager.registry.upsert_account(
        alias="work",
        auth_kind=details.record.auth_kind,
        email=details.record.email,
        organization_name=details.record.organization_name,
        organization_id=details.record.organization_id,
        account_uuid=details.record.account_uuid,
        captured_at=details.record.captured_at,
        expires_at=0,
        last_selected_at=details.record.last_selected_at,
        source=details.record.source,
        snapshot=details.snapshot,
        last_synced_at=details.record.last_synced_at,
    )

    payload = manager.refresh_account("work")

    assert payload["alias"] == "work"
    assert payload["probe_output"] == "pong"
    assert fake_auth_backend.print_prompts == ["ping"]


def test_refresh_account_emits_progress_events(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    events: list[str] = []

    payload = manager.refresh_account(
        "work",
        progress_callback=lambda stage, _payload: events.append(stage),
    )

    assert payload["alias"] == "work"
    assert events == [
        "start",
        "activating_target",
        "target_activated",
        "running_probe",
        "probe_succeeded",
        "syncing_current",
        "sync_succeeded",
        "restoring_original",
        "restore_complete",
    ]


def test_refresh_account_restores_previous_live_snapshot(
    registry, fake_auth_backend, fake_usage_provider
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("test1")
    manager.select_account("test1")

    fake_auth_backend.snapshot = AuthSnapshot(
        oauth_account={
            "emailAddress": "work@example.com",
            "organizationUuid": "org-456",
            "organizationName": "Other Org",
            "accountUuid": "acct-456",
        },
        credentials={
            "claudeAiOauth": {
                "accessToken": "access-2",
                "refreshToken": "refresh-2",
                "expiresAt": 4102444800000,
                "scopes": ["user:profile"],
            }
        },
    )
    manager.capture_current_account("test2")
    manager.select_account("test1")

    payload = manager.refresh_account("test2")

    assert payload["alias"] == "test2"
    assert manager.current_alias() == "test1"
    assert fake_auth_backend.snapshot.oauth_account["organizationName"] == "Example Org"


def test_refresh_candidates_filters_cli_accounts(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    manager.add_token_account(
        "sdk-only",
        "long-lived-token",
        email="sdk@example.com",
        organization_name="SDK Org",
    )
    details = manager.get_account("work")
    manager.registry.upsert_account(
        alias="work",
        auth_kind=details.record.auth_kind,
        email=details.record.email,
        organization_name=details.record.organization_name,
        organization_id=details.record.organization_id,
        account_uuid=details.record.account_uuid,
        captured_at=details.record.captured_at,
        expires_at=0,
        last_selected_at=details.record.last_selected_at,
        source=details.record.source,
        snapshot=details.snapshot,
        last_synced_at=details.record.last_synced_at,
    )

    assert manager.refresh_candidates() == ["work"]


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


def test_add_token_account_attaches_to_existing_cli_alias(
    registry, fake_auth_backend, fake_usage_provider
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")

    captured = manager.add_token_account(
        "work",
        "long-lived-token",
        email="work@example.com",
        organization_name="Example Org",
    )
    details = manager.get_account("work")
    env = manager.build_sdk_env("work", base_env={"PATH": "/bin"})

    assert captured["auth_kind"] == "cli_snapshot"
    assert captured["kind_label"] == "cli+token"
    assert details.record.auth_kind == "cli_snapshot"
    assert details.record.has_sdk_token is True
    assert details.sdk_token_snapshot is not None
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
    assert payload["warning"] is None


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
    assert payload["warning"] is None


def test_probe_token_scope_limited_but_valid(registry, fake_auth_backend, fake_usage_provider):
    message = (
        b'{"error":{"message":"OAuth token does not meet scope requirement '
        b'any_of(user:profile, user:office)"}}'
    )
    body = io.BytesIO(message)
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
        token_metadata_fetcher=lambda _token: (_ for _ in ()).throw(
            urllib.error.HTTPError(
                url="https://api.anthropic.com/api/oauth/profile",
                code=403,
                msg="Forbidden",
                hdrs=None,
                fp=body,
            )
        ),
    )

    payload = manager.probe_token("long-lived-token")

    assert payload["valid"] is True
    assert payload["metadata"] == {}
    assert payload["error"] is None
    assert payload["warning"] == "Profile metadata is unavailable for this token scope."


def test_probe_token_http_error_non_403(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
        token_metadata_fetcher=lambda _token: (_ for _ in ()).throw(
            urllib.error.HTTPError(
                url="https://api.anthropic.com/api/oauth/profile",
                code=401,
                msg="Unauthorized",
                hdrs=None,
                fp=io.BytesIO(b"unauthorized"),
            )
        ),
    )

    payload = manager.probe_token("long-lived-token")

    assert payload["valid"] is False
    assert payload["metadata"] == {}
    assert "401" in payload["error"]
    assert payload["warning"] is None


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


def test_normalize_token_metadata_with_invalid_shape(
    registry, fake_auth_backend, fake_usage_provider
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )

    assert manager._normalize_token_metadata([]) == {}


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


def test_sdk_auto_selection_is_not_supported(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.add_token_account("work-sdk", "token-a", email="a@example.com")

    with pytest.raises(AccountSelectionError):
        manager.pick_sdk_account()

    with pytest.raises(AccountSelectionError):
        manager.build_sdk_env_auto()


def test_build_sdk_env_auto_helper_is_not_supported(registry, fake_auth_backend, monkeypatch):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
    )
    manager.add_token_account("work-sdk", "token-a", email="a@example.com")
    monkeypatch.setattr("claude_select.manager.AuthManager", lambda: manager)

    with pytest.raises(AccountSelectionError):
        build_sdk_env_auto()


def test_expired_account_can_still_be_selected(registry, fake_auth_backend, fake_usage_provider):
    fake_auth_backend.snapshot.credentials["claudeAiOauth"]["expiresAt"] = 1
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    selected = manager.select_account("work")

    assert selected["alias"] == "work"
    assert selected["status"] == "expired"


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


def test_rename_account_updates_alias_and_current(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    manager.select_account("work")

    renamed = manager.rename_account("work", "personal")

    assert renamed["alias"] == "personal"
    assert manager.current_alias() == "personal"
    assert manager.get_account("personal").record.alias == "personal"


def test_rename_account_rejects_existing_alias(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    manager.capture_current_account("personal")

    with pytest.raises(AccountExistsError):
        manager.rename_account("work", "personal")


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
    assert "Last Synced" in rendered
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
    assert rows[0]["available"] is True
    assert rows[0]["stale"] is False
    assert rows[0]["error"] is None
    assert rows[0]["fetched_at"] == "2099-01-01T00:00:00Z"


def test_list_accounts_with_cache_only_usage(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    fake_usage_provider.cached_payload = {
        "five_hour": {
            "used_percentage": 60.0,
            "resets_at": "2099-01-01T05:00:00Z",
        },
        "seven_day": {
            "used_percentage": 5.0,
            "resets_at": "2099-01-07T00:00:00Z",
        },
        "seven_day_opus": None,
        "extra_usage": None,
        "fetched_at": "2099-01-01T00:00:00Z",
        "stale": False,
        "error": None,
    }

    rows = manager.list_accounts(
        include_usage=True,
        usage_mode="cache_only",
        usage_stale_after_seconds=300,
    )

    assert rows[0]["quota_5h_left"] == "40.0%"
    assert rows[0]["quota_7d_left"] == "95.0%"
    assert fake_usage_provider.calls == ["cached:alias:work"]


def test_list_cli_and_token_accounts(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    manager.add_token_account("work-sdk", "token-a", email="sdk@example.com")

    cli_rows = manager.list_cli_accounts(include_usage=True)
    token_rows = manager.list_token_accounts(include_usage=True)

    assert [row["alias"] for row in cli_rows] == ["work"]
    assert cli_rows[0]["quota_5h_left"] == "76.0%"
    assert [row["alias"] for row in token_rows] == ["work-sdk"]
    assert token_rows[0]["quota_5h_left"] == "n/a"


def test_token_entries_show_na_usage(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.add_token_account("work-sdk", "token-a", email="sdk@example.com")

    rows = manager.list_accounts(include_usage=True)
    quota = manager.get_account_quota("work-sdk")

    assert rows[0]["quota_5h_left"] == "n/a"
    assert rows[0]["quota_7d_reset"] == "n/a"
    assert rows[0]["available"] is False
    assert rows[0]["stale"] is False
    assert "unsupported" in rows[0]["error"]
    assert rows[0]["fetched_at"] is None
    assert quota["available"] is False
    assert quota["quota_5h_left"] == "n/a"
    assert "unsupported" in quota["error"]


def test_get_account_summary_and_current_account_summary(
    registry, fake_auth_backend, fake_usage_provider
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    manager.select_account("work")

    summary = manager.get_account_summary("work", include_usage=True)
    current = manager.get_current_account_summary(include_usage=True)

    assert summary["alias"] == "work"
    assert summary["quota_5h_left"] == "76.0%"
    assert current["alias"] == "work"
    assert current["auth_method"] == "claude.ai"
    assert current["quota_7d_left"] == "59.0%"


def test_current_account_summary_without_usage(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")

    current = manager.get_current_account_summary(include_usage=False)

    assert current["alias"] == "work"
    assert "usage" not in current
    assert "quota_5h_left" not in current


def test_cli_entry_with_sdk_token_keeps_cli_quota(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    manager.add_token_account("work", "token-a", email="work@example.com")

    rows = manager.list_accounts(include_usage=True)
    quota = manager.get_account_quota("work")

    assert rows[0]["kind_label"] == "cli+token"
    assert rows[0]["quota_5h_left"] == "76.0%"
    assert rows[0]["last_synced_at"] is not None
    assert quota["available"] is True
    assert quota["quota_5h_left"] == "76.0%"


def test_display_auth_kind_unknown_passthrough():
    assert AuthManager._display_auth_kind("custom") == "custom"


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


def test_list_account_quotas_auto_refresh_calls_best_effort(
    registry, fake_auth_backend, fake_usage_provider, monkeypatch
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    calls: list[str] = []
    monkeypatch.setattr(
        manager,
        "refresh_account",
        lambda alias, prompt="ping": calls.append(alias) or {"alias": alias},
    )
    monkeypatch.setattr(manager, "refresh_candidates", lambda: ["work"])

    rows = manager.list_account_quotas(auto_refresh=True)

    assert rows[0]["alias"] == "work"
    assert calls == ["work"]


def test_list_available_accounts_and_pick_available_account(registry, fake_auth_backend):
    usage_provider = AliasUsageProvider(
        {
            "alias:work": {"five_hour": 24.0, "seven_day": 41.0},
            "alias:backup": {"five_hour": 0.0, "seven_day": 80.0},
            "alias:empty": {"five_hour": 100.0, "seven_day": 10.0},
        }
    )
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=usage_provider,
    )
    manager.capture_current_account("work")

    fake_auth_backend.snapshot.oauth_account["emailAddress"] = "backup@example.com"
    fake_auth_backend.snapshot.oauth_account["organizationUuid"] = "org-456"
    fake_auth_backend.snapshot.oauth_account["organizationName"] = "Backup Org"
    fake_auth_backend.snapshot.oauth_account["accountUuid"] = "acct-456"
    manager.capture_current_account("backup")

    fake_auth_backend.snapshot.oauth_account["emailAddress"] = "empty@example.com"
    fake_auth_backend.snapshot.oauth_account["organizationUuid"] = "org-789"
    fake_auth_backend.snapshot.oauth_account["organizationName"] = "Empty Org"
    fake_auth_backend.snapshot.oauth_account["accountUuid"] = "acct-789"
    manager.capture_current_account("empty")

    manager.add_token_account("sdk-only", "token-a", email="sdk@example.com")
    manager.select_account("work")

    rows = manager.list_available_accounts(include_usage=True)
    picked = manager.pick_available_account(include_usage=True)
    relaxed = manager.list_available_accounts(include_usage=False, require_quota=False)

    assert [row["alias"] for row in rows] == ["backup", "work"]
    assert picked["alias"] == "work"
    assert {row["alias"] for row in relaxed} == {"backup", "empty", "sdk-only", "work"}


def test_pick_available_account_raises_when_no_match(registry, fake_auth_backend):
    usage_provider = AliasUsageProvider(
        {
            "alias:work": {"five_hour": 100.0, "seven_day": 100.0},
        }
    )
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=usage_provider,
    )
    manager.capture_current_account("work")

    with pytest.raises(AccountSelectionError):
        manager.pick_available_account()


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
    assert refreshed.record.last_synced_at is not None


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


def test_build_sdk_env_auto_refresh_refreshes_expired_cli_alias(
    registry, fake_auth_backend, fake_usage_provider, monkeypatch
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    details = manager.get_account("work")
    manager.registry.upsert_account(
        alias="work",
        auth_kind=details.record.auth_kind,
        email=details.record.email,
        organization_name=details.record.organization_name,
        organization_id=details.record.organization_id,
        account_uuid=details.record.account_uuid,
        captured_at=details.record.captured_at,
        expires_at=0,
        last_selected_at=details.record.last_selected_at,
        source=details.record.source,
        snapshot=details.snapshot,
        last_synced_at=details.record.last_synced_at,
    )
    refreshed_snapshot = AuthSnapshot(
        oauth_account=details.snapshot.oauth_account,
        credentials={
            "claudeAiOauth": {
                "accessToken": "access-2",
                "refreshToken": "refresh-2",
                "expiresAt": 4102448400000,
                "scopes": ["user:profile"],
            }
        },
    )

    def fake_refresh(alias: str, *, prompt: str = "ping"):
        manager.registry.upsert_account(
            alias=alias,
            auth_kind=AUTH_KIND_CLI_SNAPSHOT,
            email=details.record.email,
            organization_name=details.record.organization_name,
            organization_id=details.record.organization_id,
            account_uuid=details.record.account_uuid,
            captured_at=details.record.captured_at,
            expires_at=4102448400000,
            last_selected_at=details.record.last_selected_at,
            source=details.record.source,
            snapshot=refreshed_snapshot,
            last_synced_at=details.record.last_synced_at,
        )
        return {"alias": alias, "probe_prompt": prompt, "probe_output": "pong"}

    monkeypatch.setattr(manager, "refresh_account", fake_refresh)

    env = manager.build_sdk_env("work", auto_refresh=True)
    quota = manager.get_account_quota("work", auto_refresh=True)
    exported = manager.export_sdk_auth("work", auto_refresh=True)
    selected = manager.select_account("work", auto_refresh=True)

    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "access-2"
    assert quota["status"] == "healthy"
    assert exported["credentials"]["claudeAiOauth"]["accessToken"] == "access-2"
    assert selected["status"] == "healthy"


def test_top_level_build_sdk_env_supports_auto_refresh(
    registry, fake_auth_backend, fake_usage_provider, monkeypatch
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    monkeypatch.setattr("claude_select.manager.AuthManager", lambda: manager)

    env = build_sdk_env("work", auto_refresh=True)

    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "access-1"


def test_list_accounts_auto_refresh_best_effort(
    registry, fake_auth_backend, fake_usage_provider, monkeypatch
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    details = manager.get_account("work")
    manager.registry.upsert_account(
        alias="work",
        auth_kind=details.record.auth_kind,
        email=details.record.email,
        organization_name=details.record.organization_name,
        organization_id=details.record.organization_id,
        account_uuid=details.record.account_uuid,
        captured_at=details.record.captured_at,
        expires_at=0,
        last_selected_at=details.record.last_selected_at,
        source=details.record.source,
        snapshot=details.snapshot,
        last_synced_at=details.record.last_synced_at,
    )
    monkeypatch.setattr(
        manager,
        "refresh_account",
        lambda alias, prompt="ping": (_ for _ in ()).throw(AuthExpiredError("boom")),
    )

    rows = manager.list_accounts(auto_refresh=True)

    assert rows[0]["alias"] == "work"
    assert rows[0]["status"] == "expired"


def test_refresh_account_raises_when_print_probe_fails(
    registry, fake_auth_backend, fake_usage_provider
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")

    def failing_probe(prompt: str) -> tuple[bool, str]:
        return False, "nope"

    fake_auth_backend.run_print_prompt = failing_probe

    with pytest.raises(ConfigError):
        manager.refresh_account("work")
