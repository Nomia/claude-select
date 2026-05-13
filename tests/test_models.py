from __future__ import annotations

from datetime import UTC, datetime

from claude_select.models import (
    STATUS_EXPIRED,
    STATUS_EXPIRING_SOON,
    STATUS_HEALTHY,
    STATUS_UNKNOWN,
    compute_status,
    format_remaining,
)


def test_compute_status_unknown():
    assert compute_status(None) == STATUS_UNKNOWN


def test_compute_status_expired():
    assert compute_status(1) == STATUS_EXPIRED


def test_compute_status_healthy():
    now = datetime(2026, 5, 13, 0, 0, tzinfo=UTC)
    expires_at = int((now.timestamp() + 2 * 60 * 60) * 1000)
    assert compute_status(expires_at, now) == STATUS_HEALTHY


def test_compute_status_expiring_soon():
    now = datetime(2026, 5, 13, 0, 0, tzinfo=UTC)
    expires_at = int((now.timestamp() + 30 * 60) * 1000)
    assert compute_status(expires_at, now) == STATUS_EXPIRING_SOON


def test_format_remaining_unknown():
    assert format_remaining(None) == "unknown"
