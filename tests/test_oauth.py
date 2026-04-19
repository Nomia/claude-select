from __future__ import annotations

from claude_switch.models import SecretPayload
from claude_switch.oauth import classify_auth_state, refresh_secret_payload


def test_classify_auth_state_refreshable():
    secret = SecretPayload(
        oauth_account={"emailAddress": "user@example.com"},
        credentials={
            "claudeAiOauth": {
                "accessToken": "token",
                "refreshToken": "refresh",
                "expiresAt": 1000,
            }
        },
    )

    state, expires_at = classify_auth_state(secret, now_ms=1000)

    assert state == "refreshable"
    assert expires_at == 1000


def test_refresh_secret_payload_updates_tokens():
    secret = SecretPayload(
        oauth_account={"emailAddress": "user@example.com"},
        credentials={
            "claudeAiOauth": {
                "accessToken": "old-access",
                "refreshToken": "old-refresh",
                "expiresAt": 1000,
            }
        },
    )

    refreshed = refresh_secret_payload(
        secret,
        request_refresh=lambda token: {
            "access_token": f"new-{token}",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
            "scope": "user:profile user:settings",
        },
    )

    oauth = refreshed.credentials["claudeAiOauth"]
    assert oauth["accessToken"] == "new-old-refresh"
    assert oauth["refreshToken"] == "new-refresh"
    assert oauth["scopes"] == ["user:profile", "user:settings"]
