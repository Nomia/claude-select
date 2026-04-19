from __future__ import annotations

import copy

import pytest

from claude_switch.live_state import ClaudeLiveStateBackend
from claude_switch.models import LiveState
from claude_switch.store import FileProfileStore


@pytest.fixture
def sample_live_state() -> LiveState:
    return LiveState(
        config={
            "oauthAccount": {
                "emailAddress": "work@example.com",
                "organizationUuid": "org-123",
                "organizationName": "Example Org",
                "accountUuid": "acct-123",
            }
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


class FakeLiveStateBackend(ClaudeLiveStateBackend):
    def __init__(self, live_state: LiveState):
        self._live_state = live_state
        self.written_state: LiveState | None = None

    def read(self) -> LiveState:
        return LiveState(
            config=copy.deepcopy(self._live_state.config),
            credentials=copy.deepcopy(self._live_state.credentials),
        )

    def write(self, live_state: LiveState) -> None:
        self.written_state = LiveState(
            config=copy.deepcopy(live_state.config),
            credentials=copy.deepcopy(live_state.credentials),
        )
        self._live_state = self.written_state


@pytest.fixture
def store(tmp_path):
    return FileProfileStore(tmp_path / "store")


@pytest.fixture
def fake_live_backend(sample_live_state):
    return FakeLiveStateBackend(sample_live_state)
