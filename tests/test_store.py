from __future__ import annotations

from claude_select.store import AuthRegistry


def test_registry_upsert_and_get(registry: AuthRegistry, sample_snapshot):
    registry.upsert_account(
        alias="work",
        auth_kind="cli_snapshot",
        email="work@example.com",
        organization_name="Example Org",
        organization_id="org-123",
        account_uuid="acct-123",
        captured_at="2026-05-10T00:00:00Z",
        expires_at=4102444800000,
        last_selected_at=None,
        source="claude_cli",
        snapshot=sample_snapshot,
    )

    details = registry.get_account("work")

    assert details.record.alias == "work"
    assert details.record.email == "work@example.com"
    assert details.snapshot.credentials["claudeAiOauth"]["accessToken"] == "access-1"
    assert details.record.last_synced_at is None


def test_registry_mark_selected(registry: AuthRegistry, sample_snapshot):
    registry.upsert_account(
        alias="work",
        auth_kind="cli_snapshot",
        email="work@example.com",
        organization_name="Example Org",
        organization_id="org-123",
        account_uuid="acct-123",
        captured_at="2026-05-10T00:00:00Z",
        expires_at=4102444800000,
        last_selected_at=None,
        source="claude_cli",
        snapshot=sample_snapshot,
    )

    registry.mark_selected("work", "2026-05-10T01:00:00Z")

    assert registry.get_current_alias() == "work"
    assert registry.get_account("work").record.last_selected_at == "2026-05-10T01:00:00Z"


def test_registry_usage_cache(registry: AuthRegistry):
    payload = {"five_hour": {"used_percentage": 24.0}}

    registry.set_usage_cache("alias:work", payload, fetched_at=100)

    assert registry.get_usage_cache("alias:work", max_age_seconds=60, now_epoch=120) == payload
    assert registry.get_usage_cache("alias:work", max_age_seconds=10, now_epoch=120) is None


def test_registry_attach_sdk_token(registry: AuthRegistry, sample_snapshot):
    registry.upsert_account(
        alias="work",
        auth_kind="cli_snapshot",
        email="work@example.com",
        organization_name="Example Org",
        organization_id="org-123",
        account_uuid="acct-123",
        captured_at="2026-05-10T00:00:00Z",
        expires_at=4102444800000,
        last_selected_at=None,
        source="claude_cli",
        snapshot=sample_snapshot,
    )
    token_snapshot = sample_snapshot.__class__(
        oauth_account={
            "emailAddress": "work@example.com",
            "organizationName": "Example Org",
            "organizationUuid": "org-123",
            "accountUuid": "acct-123",
        },
        credentials={"claudeAiOauth": {"accessToken": "token-access", "scopes": []}},
    )

    registry.attach_sdk_token(
        alias="work",
        captured_at="2026-05-10T02:00:00Z",
        expires_at=4202444800000,
        snapshot=token_snapshot,
    )

    details = registry.get_account("work")
    rows = registry.list_accounts()

    assert details.record.auth_kind == "cli_snapshot"
    assert details.record.has_sdk_token is True
    assert details.record.last_synced_at == "2026-05-10T02:00:00Z"
    assert details.sdk_token_snapshot is not None
    assert details.sdk_token_snapshot.credentials["claudeAiOauth"]["accessToken"] == "token-access"
    assert rows[0].has_sdk_token is True
