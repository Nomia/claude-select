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
