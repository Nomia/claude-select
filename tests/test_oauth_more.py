from __future__ import annotations

import io
import json
import urllib.error

import pytest

from claude_select.exceptions import OAuthRefreshError
from claude_select.models import ProfileMetadata, SecretPayload
from claude_select.oauth import (
    mark_refresh_failure,
    mark_refresh_success,
    request_oauth_refresh,
    update_profile_auth_metadata,
)


def test_mark_refresh_success_and_failure():
    profile = ProfileMetadata(
        id="work",
        kind="oauth",
        label="work",
        email="work@example.com",
        secret_ref="work",
    )
    secret = SecretPayload(
        oauth_account={"emailAddress": "work@example.com"},
        credentials={
            "claudeAiOauth": {
                "accessToken": "token",
                "refreshToken": "refresh",
                "expiresAt": 4102444800000,
            }
        },
    )

    mark_refresh_success(profile, secret)
    assert profile.last_refresh_at is not None
    assert profile.last_refresh_error is None

    secret.credentials["claudeAiOauth"]["expiresAt"] = 1
    mark_refresh_failure(profile, "boom")
    update_profile_auth_metadata(profile, secret)
    assert profile.auth_state == "reauth_required"


def test_request_oauth_refresh_success(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"access_token": "new", "expires_in": 3600}).encode("utf-8")

    monkeypatch.setattr(
        "claude_select.oauth.urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeResponse(),
    )

    response = request_oauth_refresh("refresh")

    assert response["access_token"] == "new"


def test_request_oauth_refresh_http_error(monkeypatch):
    def raise_http_error(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            url="https://example.com",
            code=401,
            msg="bad",
            hdrs=None,
            fp=io.BytesIO(b'{"error":"invalid"}'),
        )

    monkeypatch.setattr("claude_select.oauth.urllib.request.urlopen", raise_http_error)

    with pytest.raises(OAuthRefreshError):
        request_oauth_refresh("refresh")
