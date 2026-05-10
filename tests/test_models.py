from __future__ import annotations

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


def test_compute_status_expiring_soon():
    assert compute_status(4102444800000) in {STATUS_HEALTHY, STATUS_EXPIRING_SOON}


def test_format_remaining_unknown():
    assert format_remaining(None) == "unknown"
