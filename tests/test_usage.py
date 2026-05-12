from __future__ import annotations

from claude_select.exceptions import UsageUnavailableError
from claude_select.models import AuthSnapshot
from claude_select.usage import OAuthUsageProvider, remaining_percentage, reset_countdown


def test_usage_provider_caches(registry, sample_snapshot):
    calls: list[str] = []

    def fake_fetcher(token: str):
        calls.append(token)
        return {
            "five_hour": {"utilization": 24.0, "resets_at": "2099-01-01T05:00:00Z"},
            "seven_day": {"utilization": 41.0, "resets_at": "2099-01-07T00:00:00Z"},
        }

    provider = OAuthUsageProvider(registry, fetcher=fake_fetcher)

    first = provider.get_usage(sample_snapshot, "alias:work")
    second = provider.get_usage(sample_snapshot, "alias:work")

    assert calls == ["access-1"]
    assert first["five_hour"]["used_percentage"] == 24.0
    assert second["stale"] is False


def test_usage_provider_uses_stale_cache_on_failure(registry, sample_snapshot):
    provider = OAuthUsageProvider(
        registry,
        fetcher=lambda _token: {
            "five_hour": {"utilization": 24.0, "resets_at": "2099-01-01T05:00:00Z"},
            "seven_day": {"utilization": 41.0, "resets_at": "2099-01-07T00:00:00Z"},
        },
    )
    provider.get_usage(sample_snapshot, "alias:work")
    provider.fetcher = lambda _token: (_ for _ in ()).throw(RuntimeError("boom"))

    payload = provider.get_usage(sample_snapshot, "alias:work")

    assert payload["stale"] is False

    stale_provider = OAuthUsageProvider(
        registry,
        cache_ttl_seconds=-1,
        fetcher=lambda _token: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    stale = stale_provider.get_usage(sample_snapshot, "alias:work")
    assert stale["stale"] is True
    assert stale["error"] == "boom"


def test_usage_provider_raises_without_cache(registry, sample_snapshot):
    provider = OAuthUsageProvider(
        registry,
        fetcher=lambda _token: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    try:
        provider.get_usage(sample_snapshot, "alias:work")
    except UsageUnavailableError as exc:
        assert "Unable to fetch usage data" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected UsageUnavailableError")


def test_usage_helpers():
    window = {"used_percentage": 24.0, "resets_at": "2099-01-01T05:00:00Z"}

    assert remaining_percentage(window) == 76.0
    assert reset_countdown(window) != "unknown"


def test_usage_helpers_unknown_and_resetting():
    assert remaining_percentage(None) is None
    assert reset_countdown(None) == "unknown"
    assert (
        reset_countdown({"used_percentage": 50.0, "resets_at": "2000-01-01T00:00:00Z"})
        == "resetting"
    )


def test_usage_provider_normalize_helpers():
    payload = OAuthUsageProvider._normalize_payload(
        {
            "five_hour": {"utilization": 24.0, "resets_at": "2099-01-01T05:00:00Z"},
            "seven_day": {"utilization": 41.0, "resets_at": "2099-01-07T00:00:00Z"},
            "extra_usage": {
                "is_enabled": True,
                "utilization": 15.0,
                "used_credits": 100,
                "monthly_limit": 1000,
            },
        }
    )

    assert payload["five_hour"]["used_percentage"] == 24.0
    assert payload["seven_day"]["used_percentage"] == 41.0
    assert payload["extra_usage"]["used_percentage"] == 15.0


def test_usage_provider_access_token_missing():
    snapshot = AuthSnapshot(
        oauth_account={"emailAddress": "user@example.com"},
        credentials={"claudeAiOauth": {}},
    )

    try:
        OAuthUsageProvider._access_token(snapshot)
    except UsageUnavailableError as exc:
        assert "missing" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected UsageUnavailableError")


def test_usage_provider_epoch_from_iso():
    assert OAuthUsageProvider._epoch_from_iso("2099-01-01T00:00:00Z") is not None
    assert OAuthUsageProvider._epoch_from_iso("bad") is None
