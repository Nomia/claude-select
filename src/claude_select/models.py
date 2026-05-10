"""Data models used by the auth registry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

WARNING_WINDOW_SECONDS = 6 * 60 * 60

STATUS_HEALTHY = "healthy"
STATUS_EXPIRING_SOON = "expiring_soon"
STATUS_EXPIRED = "expired"
STATUS_UNKNOWN = "unknown"


def utc_now() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(tz=UTC)


def utc_now_iso() -> str:
    """Return the current UTC timestamp in ISO format."""
    return utc_now().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso8601(value: str | None) -> datetime | None:
    """Parse a normalized UTC timestamp or return None."""
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def compute_status(expires_at: int | None, now: datetime | None = None) -> str:
    """Compute account health from an epoch-milliseconds expiry."""
    if expires_at is None:
        return STATUS_UNKNOWN
    current = now or utc_now()
    remaining = int(expires_at / 1000 - current.timestamp())
    if remaining <= 0:
        return STATUS_EXPIRED
    if remaining <= WARNING_WINDOW_SECONDS:
        return STATUS_EXPIRING_SOON
    return STATUS_HEALTHY


def format_remaining(expires_at: int | None, now: datetime | None = None) -> str:
    """Format time until expiry for human-readable table output."""
    if expires_at is None:
        return "unknown"
    current = now or utc_now()
    remaining = int(expires_at / 1000 - current.timestamp())
    if remaining <= 0:
        return "expired"
    hours, remainder = divmod(remaining, 3600)
    minutes = remainder // 60
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


@dataclass(slots=True)
class AuthSnapshot:
    """Captured Claude auth payload."""

    oauth_account: dict[str, Any]
    credentials: dict[str, Any]

    def expires_at(self) -> int | None:
        """Return the OAuth expiry epoch milliseconds if available."""
        oauth = self.credentials.get("claudeAiOauth", {})
        expires_at = oauth.get("expiresAt")
        return expires_at if isinstance(expires_at, int) else None

    def scopes(self) -> list[str]:
        """Return normalized scopes."""
        oauth = self.credentials.get("claudeAiOauth", {})
        raw = oauth.get("scopes")
        if not isinstance(raw, list):
            return []
        return [str(scope) for scope in raw]


@dataclass(slots=True)
class AccountRecord:
    """Account metadata stored in the registry database."""

    alias: str
    email: str
    organization_name: str
    organization_id: str
    account_uuid: str
    captured_at: str
    expires_at: int | None
    last_selected_at: str | None
    source: str

    def status(self, now: datetime | None = None) -> str:
        """Return the computed health status."""
        return compute_status(self.expires_at, now)

    def expires_in(self, now: datetime | None = None) -> str:
        """Return human-friendly remaining time."""
        return format_remaining(self.expires_at, now)


@dataclass(slots=True)
class AccountDetails:
    """Joined account metadata and snapshot."""

    record: AccountRecord
    snapshot: AuthSnapshot
