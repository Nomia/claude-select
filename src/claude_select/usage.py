"""Quota usage provider and cache helpers."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from claude_select.exceptions import UsageUnavailableError
from claude_select.models import AuthSnapshot, utc_now_iso
from claude_select.store import AuthRegistry

USAGE_API_URL = "https://api.anthropic.com/api/oauth/usage"
USAGE_BETA_HEADER = "oauth-2025-04-20"
USAGE_CACHE_TTL_SECONDS = 60


class UsageProvider(Protocol):
    """Fetch and cache usage payloads."""

    def get_usage(self, snapshot: AuthSnapshot, cache_key: str) -> dict[str, Any]:
        """Return structured usage data for one auth snapshot."""


class OAuthUsageProvider:
    """Fetch OAuth-backed quota usage with a small local cache."""

    def __init__(
        self,
        registry: AuthRegistry,
        *,
        cache_ttl_seconds: int = USAGE_CACHE_TTL_SECONDS,
        timeout_seconds: float = 10.0,
        fetcher: Callable[[str], dict[str, Any]] | None = None,
    ):
        self.registry = registry
        self.cache_ttl_seconds = cache_ttl_seconds
        self.timeout_seconds = timeout_seconds
        self.fetcher = fetcher or self._fetch_remote

    def get_usage(self, snapshot: AuthSnapshot, cache_key: str) -> dict[str, Any]:
        """Return structured usage data, preferring fresh cache when available."""
        now_epoch = int(time.time())
        cached = self.registry.get_usage_cache(
            cache_key,
            max_age_seconds=self.cache_ttl_seconds,
            now_epoch=now_epoch,
        )
        if cached is not None:
            cached["stale"] = False
            cached["cache_age_seconds"] = 0
            return cached

        token = self._access_token(snapshot)
        try:
            raw = self.fetcher(token)
            payload = self._normalize_payload(raw)
            self.registry.set_usage_cache(cache_key, payload, now_epoch)
            payload["stale"] = False
            payload["cache_age_seconds"] = 0
            return payload
        except Exception as exc:  # pragma: no cover
            # Fallback to stale cached usage when the live fetch fails.
            stale = self.registry.get_usage_cache(
                cache_key,
                max_age_seconds=None,
                now_epoch=now_epoch,
            )
            if stale is not None:
                fetched_at = (
                    self._epoch_from_iso(str(stale.get("fetched_at", "") or ""))
                    or now_epoch
                )
                stale["stale"] = True
                stale["cache_age_seconds"] = max(now_epoch - fetched_at, 0)
                stale["error"] = str(exc)
                return stale
            raise UsageUnavailableError(f"Unable to fetch usage data: {exc}") from exc

    def _fetch_remote(self, token: str) -> dict[str, Any]:
        request = urllib.request.Request(
            USAGE_API_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "anthropic-beta": USAGE_BETA_HEADER,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise UsageUnavailableError(f"Usage API request failed: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise UsageUnavailableError("Usage API returned invalid JSON.") from exc

    @staticmethod
    def _normalize_payload(raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "five_hour": OAuthUsageProvider._normalize_window(raw.get("five_hour")),
            "seven_day": OAuthUsageProvider._normalize_window(raw.get("seven_day")),
            "seven_day_opus": OAuthUsageProvider._normalize_window(raw.get("seven_day_opus")),
            "extra_usage": OAuthUsageProvider._normalize_extra_usage(raw.get("extra_usage")),
            "fetched_at": utc_now_iso(),
            "error": None,
        }

    @staticmethod
    def _normalize_window(raw: object) -> dict[str, Any] | None:
        if not isinstance(raw, dict):
            return None
        utilization = raw.get("utilization")
        resets_at = raw.get("resets_at")
        return {
            "used_percentage": (
                float(utilization) if isinstance(utilization, (int, float)) else None
            ),
            "resets_at": str(resets_at) if resets_at else None,
        }

    @staticmethod
    def _normalize_extra_usage(raw: object) -> dict[str, Any] | None:
        if not isinstance(raw, dict):
            return None
        utilization = raw.get("utilization")
        used_credits = raw.get("used_credits")
        monthly_limit = raw.get("monthly_limit")
        return {
            "is_enabled": bool(raw.get("is_enabled")),
            "used_percentage": (
                float(utilization) if isinstance(utilization, (int, float)) else None
            ),
            "used_credits": int(used_credits) if isinstance(used_credits, int) else None,
            "monthly_limit": int(monthly_limit) if isinstance(monthly_limit, int) else None,
        }

    @staticmethod
    def _access_token(snapshot: AuthSnapshot) -> str:
        oauth = snapshot.credentials.get("claudeAiOauth", {})
        token = oauth.get("accessToken")
        if not token:
            raise UsageUnavailableError("Claude OAuth access token is missing.")
        return str(token)

    @staticmethod
    def _epoch_from_iso(value: str) -> int | None:
        if not value:
            return None
        try:
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
        except ValueError:
            return None


def remaining_percentage(window: dict[str, Any] | None) -> float | None:
    """Compute remaining percentage from a normalized usage window."""
    if not window:
        return None
    used = window.get("used_percentage")
    if not isinstance(used, (int, float)):
        return None
    return max(0.0, min(100.0, 100.0 - float(used)))


def reset_countdown(window: dict[str, Any] | None, now: datetime | None = None) -> str:
    """Format time until reset for a normalized usage window."""
    if not window:
        return "unknown"
    resets_at = window.get("resets_at")
    if not resets_at:
        return "unknown"
    try:
        reset_dt = datetime.fromisoformat(str(resets_at).replace("Z", "+00:00"))
    except ValueError:
        return "unknown"
    current = now or datetime.now(tz=UTC)
    remaining = int(reset_dt.timestamp() - current.timestamp())
    if remaining <= 0:
        return "resetting"
    days, remainder = divmod(remaining, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"
