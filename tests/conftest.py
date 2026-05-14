from __future__ import annotations

import copy

import pytest

from claude_select.live_state import ClaudeAuthBackend
from claude_select.models import AuthSnapshot
from claude_select.store import AuthRegistry
from claude_select.usage import UsageProvider


@pytest.fixture
def sample_snapshot() -> AuthSnapshot:
    return AuthSnapshot(
        oauth_account={
            "emailAddress": "work@example.com",
            "organizationUuid": "org-123",
            "organizationName": "Example Org",
            "accountUuid": "acct-123",
        },
        credentials={
            "claudeAiOauth": {
                "accessToken": "access-1",
                "refreshToken": "refresh-1",
                "expiresAt": 4102444800000,
                "scopes": ["user:profile"],
            }
        },
    )


class FakeAuthBackend(ClaudeAuthBackend):
    def __init__(self, snapshot: AuthSnapshot):
        self.snapshot = snapshot
        self.written_snapshot: AuthSnapshot | None = None
        self.login_attempts = 0
        self.print_prompts: list[str] = []
        self.auth_status_payload = {
            "loggedIn": True,
            "authMethod": "claude.ai",
            "apiProvider": "firstParty",
            "email": "work@example.com",
            "orgId": "org-123",
            "orgName": "Example Org",
            "subscriptionType": "team",
        }

    def read_snapshot(self) -> AuthSnapshot:
        return AuthSnapshot(
            oauth_account=copy.deepcopy(self.snapshot.oauth_account),
            credentials=copy.deepcopy(self.snapshot.credentials),
        )

    def write_snapshot(self, snapshot: AuthSnapshot) -> None:
        self.written_snapshot = AuthSnapshot(
            oauth_account=copy.deepcopy(snapshot.oauth_account),
            credentials=copy.deepcopy(snapshot.credentials),
        )
        self.snapshot = self.written_snapshot

    def describe_targets(self) -> list[str]:
        return [
            "config: /fake/.claude.json",
            "credentials store: fake-test-backend",
        ]

    def run_auth_login(self) -> bool:
        self.login_attempts += 1
        return True

    def run_print_prompt(self, prompt: str) -> tuple[bool, str]:
        self.print_prompts.append(prompt)
        return True, "pong"

    def read_auth_status(self) -> dict[str, object] | None:
        return copy.deepcopy(self.auth_status_payload)


class FakeUsageProvider(UsageProvider):
    def __init__(self):
        self.calls: list[str] = []
        self.cached_payload: dict[str, object] | None = None

    def get_usage(self, snapshot: AuthSnapshot, cache_key: str):
        self.calls.append(cache_key)
        return {
            "five_hour": {
                "used_percentage": 24.0,
                "resets_at": "2099-01-01T05:00:00Z",
            },
            "seven_day": {
                "used_percentage": 41.0,
                "resets_at": "2099-01-07T00:00:00Z",
            },
            "seven_day_opus": None,
            "extra_usage": None,
            "fetched_at": "2099-01-01T00:00:00Z",
            "stale": False,
            "error": None,
        }

    def get_cached_usage(self, cache_key: str, *, stale_after_seconds: int | None = None):
        self.calls.append(f"cached:{cache_key}")
        if self.cached_payload is not None:
            return copy.deepcopy(self.cached_payload)
        return {
            "five_hour": {
                "used_percentage": 24.0,
                "resets_at": "2099-01-01T05:00:00Z",
            },
            "seven_day": {
                "used_percentage": 41.0,
                "resets_at": "2099-01-07T00:00:00Z",
            },
            "seven_day_opus": None,
            "extra_usage": None,
            "fetched_at": "2099-01-01T00:00:00Z",
            "stale": False,
            "error": None,
        }


@pytest.fixture
def registry(tmp_path) -> AuthRegistry:
    return AuthRegistry(tmp_path / "registry.db")


@pytest.fixture
def fake_auth_backend(sample_snapshot) -> FakeAuthBackend:
    return FakeAuthBackend(sample_snapshot)


@pytest.fixture
def fake_usage_provider() -> FakeUsageProvider:
    return FakeUsageProvider()
