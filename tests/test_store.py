from __future__ import annotations

from claude_switch.models import ProfileMetadata, SecretPayload


def test_upsert_and_load_profile(store):
    profile = ProfileMetadata(
        id="work",
        kind="oauth",
        label="work",
        email="work@example.com",
        secret_ref="work",
        auth_state="ok",
    )
    secret = SecretPayload(
        oauth_account={"emailAddress": "work@example.com"},
        credentials={"claudeAiOauth": {"accessToken": "token"}},
    )

    store.upsert_profile(profile, secret)

    loaded = store.get_profile("work")
    loaded_secret = store.get_secret("work")

    assert loaded.email == "work@example.com"
    assert loaded_secret.credentials["claudeAiOauth"]["accessToken"] == "token"


def test_remove_profile_clears_pointers(store):
    profile = ProfileMetadata(
        id="work",
        kind="oauth",
        label="work",
        email="work@example.com",
        secret_ref="work",
        auth_state="ok",
    )
    secret = SecretPayload(
        oauth_account={"emailAddress": "work@example.com"},
        credentials={"claudeAiOauth": {"accessToken": "token"}},
    )
    store.upsert_profile(profile, secret)
    store.set_current_cli_profile("work")
    store.set_default_sdk_profile("work")

    store.remove_profile("work")

    state = store.load_state()
    assert state.current_cli_profile is None
    assert state.default_sdk_profile is None
    assert state.profiles == {}
