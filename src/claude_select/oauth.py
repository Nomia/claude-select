"""OAuth helpers for Claude-backed profiles."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from claude_select.exceptions import OAuthRefreshError
from claude_select.models import (
    AUTH_STATE_EXPIRING_SOON,
    AUTH_STATE_INVALID,
    AUTH_STATE_OK,
    AUTH_STATE_REAUTH_REQUIRED,
    AUTH_STATE_REFRESHABLE,
    ProfileMetadata,
    SecretPayload,
    utc_now_iso,
)

OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
OAUTH_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
EXPIRY_BUFFER_MS = 5 * 60 * 1000

RefreshRequest = Callable[[str], dict[str, Any]]


def extract_oauth_data(secret: SecretPayload) -> dict[str, Any]:
    """Return the nested Claude OAuth dict."""
    oauth = secret.credentials.get("claudeAiOauth", {})
    return oauth if isinstance(oauth, dict) else {}


def classify_auth_state(secret: SecretPayload, now_ms: int | None = None) -> tuple[str, int | None]:
    """Classify auth state based on stored OAuth credentials."""
    oauth = extract_oauth_data(secret)
    access_token = oauth.get("accessToken")
    refresh_token = oauth.get("refreshToken")
    expires_at = oauth.get("expiresAt")
    if not access_token:
        return AUTH_STATE_INVALID, None
    if not isinstance(expires_at, int):
        return AUTH_STATE_OK, None
    current_ms = now_ms if now_ms is not None else utc_now_ms()
    if current_ms + EXPIRY_BUFFER_MS >= expires_at:
        if refresh_token:
            return AUTH_STATE_REFRESHABLE, expires_at
        return AUTH_STATE_REAUTH_REQUIRED, expires_at
    if current_ms + (60 * 60 * 1000) >= expires_at:
        return AUTH_STATE_EXPIRING_SOON, expires_at
    return AUTH_STATE_OK, expires_at


def refresh_secret_payload(
    secret: SecretPayload,
    request_refresh: RefreshRequest | None = None,
) -> SecretPayload:
    """Refresh an expired OAuth access token."""
    oauth = extract_oauth_data(secret)
    refresh_token = oauth.get("refreshToken")
    if not refresh_token:
        raise OAuthRefreshError("Profile has no refresh token.")
    request = request_refresh or request_oauth_refresh
    response = request(str(refresh_token))
    expires_in = response.get("expires_in")
    access_token = response.get("access_token")
    if not access_token or not isinstance(expires_in, int):
        raise OAuthRefreshError("OAuth refresh response was missing required fields.")
    updated = json.loads(json.dumps(secret.to_dict()))
    updated_oauth = updated["credentials"]["claudeAiOauth"]
    updated_oauth["accessToken"] = access_token
    updated_oauth["expiresAt"] = utc_now_ms() + (expires_in * 1000)
    if response.get("refresh_token"):
        updated_oauth["refreshToken"] = response["refresh_token"]
    if response.get("scope"):
        updated_oauth["scopes"] = str(response["scope"]).split()
    return SecretPayload.from_dict(updated)


def request_oauth_refresh(refresh_token: str) -> dict[str, Any]:
    """Refresh an OAuth access token via Claude's OAuth endpoint."""
    body = json.dumps(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": OAUTH_CLIENT_ID,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        OAUTH_TOKEN_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": "claude-select/0.1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read() if hasattr(exc, "read") else b""
        raw_body = error_body if isinstance(error_body, bytes) else str(error_body).encode("utf-8")
        error_text = raw_body.decode(errors="replace")
        raise OAuthRefreshError(
            f"OAuth refresh failed: HTTP {exc.code}: {error_text[:200]}"
        ) from exc
    except OSError as exc:
        raise OAuthRefreshError(f"OAuth refresh failed: {exc}") from exc


def update_profile_auth_metadata(
    profile: ProfileMetadata,
    secret: SecretPayload,
) -> ProfileMetadata:
    """Refresh metadata fields derived from the secret payload."""
    state, expires_at = classify_auth_state(secret)
    if (
        profile.auth_state == AUTH_STATE_REAUTH_REQUIRED
        and profile.last_refresh_error
        and state == AUTH_STATE_REFRESHABLE
    ):
        state = AUTH_STATE_REAUTH_REQUIRED
    profile.auth_state = state
    profile.expires_at = expires_at
    profile.updated_at = utc_now_iso()
    return profile


def mark_refresh_success(profile: ProfileMetadata, secret: SecretPayload) -> ProfileMetadata:
    """Update metadata after a successful refresh."""
    update_profile_auth_metadata(profile, secret)
    profile.last_refresh_at = utc_now_iso()
    profile.last_refresh_error = None
    return profile


def mark_refresh_failure(profile: ProfileMetadata, error: str) -> ProfileMetadata:
    """Update metadata after a failed refresh."""
    profile.auth_state = AUTH_STATE_REAUTH_REQUIRED
    profile.last_refresh_error = error
    profile.updated_at = utc_now_iso()
    return profile


def utc_now_ms() -> int:
    """Return the current UTC timestamp in milliseconds."""
    return int(datetime.now(tz=UTC).timestamp() * 1000)
