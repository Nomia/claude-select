"""ProfileManager implementation."""

from __future__ import annotations

import copy
import os
import re
from dataclasses import asdict
from typing import Any

from claude_switch.exceptions import (
    ConfigError,
    ProfileNotFoundError,
    ProfileReauthRequired,
    ProfileValidationError,
)
from claude_switch.live_state import ClaudeLiveStateBackend
from claude_switch.models import (
    AUTH_STATE_REFRESHABLE,
    PROFILE_KIND_OAUTH,
    LiveState,
    ProfileMetadata,
    SecretPayload,
    utc_now_iso,
)
from claude_switch.oauth import (
    classify_auth_state,
    mark_refresh_failure,
    mark_refresh_success,
    refresh_secret_payload,
    update_profile_auth_metadata,
)
from claude_switch.store import FileProfileStore

PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
CONFLICTING_AUTH_ENV_VARS = {
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_REFRESH_TOKEN",
    "CLAUDE_CODE_OAUTH_SCOPES",
}


class ProfileManager:
    """Main entry point for profile management."""

    def __init__(
        self,
        store: FileProfileStore | None = None,
        live_state_backend: ClaudeLiveStateBackend | None = None,
        refresh_request=None,
    ):
        self.store = store or FileProfileStore()
        self.live_state_backend = live_state_backend or ClaudeLiveStateBackend()
        self.refresh_request = refresh_request

    def list_profiles(self) -> list[dict[str, Any]]:
        """Return profile metadata dictionaries."""
        profiles = []
        for profile in self.store.list_profiles():
            secret = self.store.get_secret(profile.secret_ref)
            update_profile_auth_metadata(profile, secret)
            self.store.update_profile(profile)
            profiles.append(asdict(profile))
        return profiles

    def capture_cli_profile(self, name: str) -> dict[str, Any]:
        """Capture the current Claude CLI live state into a named profile."""
        profile_name = self._validate_profile_name(name)
        live_state = self.live_state_backend.read()
        profile, secret = self._build_profile_from_live_state(profile_name, live_state)
        self.store.upsert_profile(profile, secret)
        self.store.set_current_cli_profile(profile_name)
        if self.get_default_sdk_profile() is None:
            self.store.set_default_sdk_profile(profile_name)
        return asdict(profile)

    def sync_cli_profile(self, name: str | None = None) -> dict[str, Any]:
        """Update a named profile using the current Claude CLI live state."""
        state = self.store.load_state()
        profile_name = name or state.current_cli_profile
        if not profile_name:
            raise ProfileValidationError(
                "No profile name provided and no current CLI profile is set."
            )
        if profile_name not in state.profiles:
            raise ProfileNotFoundError(f"Profile '{profile_name}' was not found.")
        live_state = self.live_state_backend.read()
        profile, secret = self._build_profile_from_live_state(profile_name, live_state)
        self.store.upsert_profile(profile, secret)
        return asdict(profile)

    def switch_cli(self, name: str) -> dict[str, Any]:
        """Switch Claude's live state to a named profile."""
        profile, secret = self._load_profile(name)
        profile, secret, refresh_error = self._refresh_profile_if_needed(
            profile,
            secret,
            allow_failure=True,
        )
        try:
            current_live_state = self.live_state_backend.read()
            next_config = copy.deepcopy(current_live_state.config)
        except ConfigError:
            next_config = {}
        next_config["oauthAccount"] = copy.deepcopy(secret.oauth_account)
        live_state = LiveState(
            config=next_config,
            credentials=copy.deepcopy(secret.credentials),
        )
        self.live_state_backend.write(live_state)
        profile.updated_at = utc_now_iso()
        self.store.upsert_profile(profile, secret)
        self.store.set_current_cli_profile(profile.id)
        result = asdict(profile)
        result["refresh_error"] = refresh_error
        return result

    def set_default_sdk_profile(self, name: str) -> None:
        """Set the default profile for SDK env generation."""
        self._load_profile(name)
        self.store.set_default_sdk_profile(name)

    def get_default_sdk_profile(self) -> str | None:
        """Return the default SDK profile if configured."""
        return self.store.load_state().default_sdk_profile

    def get_current_cli_profile(self) -> str | None:
        """Return the currently selected CLI profile."""
        return self.store.load_state().current_cli_profile

    def inspect_profile(self, name: str) -> dict[str, Any]:
        """Return detailed metadata for one profile."""
        profile, secret = self._load_profile(name)
        update_profile_auth_metadata(profile, secret)
        self.store.update_profile(profile)
        details = asdict(profile)
        details["scopes"] = self._get_scopes(secret)
        return details

    def remove_profile(self, name: str) -> None:
        """Remove a stored profile."""
        self._load_profile(name)
        self.store.remove_profile(name)

    def build_sdk_env(
        self,
        name: str | None = None,
        base_env: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Build a clean environment mapping for the requested profile."""
        profile_name = name or self.get_default_sdk_profile()
        if not profile_name:
            raise ProfileValidationError(
                "No profile specified and no default SDK profile is configured."
            )
        profile, secret = self._load_profile(profile_name)
        profile, secret, _refresh_error = self._refresh_profile_if_needed(
            profile,
            secret,
            allow_failure=False,
        )
        env = dict(base_env if base_env is not None else os.environ)
        for key in CONFLICTING_AUTH_ENV_VARS:
            env.pop(key, None)
        oauth = secret.credentials["claudeAiOauth"]
        env["CLAUDE_CODE_OAUTH_TOKEN"] = str(oauth["accessToken"])
        refresh_token = oauth.get("refreshToken")
        if refresh_token:
            env["CLAUDE_CODE_OAUTH_REFRESH_TOKEN"] = str(refresh_token)
        scopes = oauth.get("scopes")
        if isinstance(scopes, list) and scopes:
            env["CLAUDE_CODE_OAUTH_SCOPES"] = " ".join(str(scope) for scope in scopes)
        return env

    def _load_profile(self, name: str) -> tuple[ProfileMetadata, SecretPayload]:
        state = self.store.load_state()
        if name not in state.profiles:
            raise ProfileNotFoundError(f"Profile '{name}' was not found.")
        return state.profiles[name], self.store.get_secret(state.profiles[name].secret_ref)

    def _validate_profile_name(self, name: str) -> str:
        normalized = name.strip()
        if not normalized:
            raise ProfileValidationError("Profile name cannot be empty.")
        if not PROFILE_NAME_RE.match(normalized):
            raise ProfileValidationError(
                "Profile name must only contain letters, numbers, dot, underscore, or dash."
            )
        return normalized

    def _build_profile_from_live_state(
        self,
        name: str,
        live_state: LiveState,
    ) -> tuple[ProfileMetadata, SecretPayload]:
        oauth_account = live_state.config.get("oauthAccount")
        if not isinstance(oauth_account, dict):
            raise ConfigError("Claude config does not contain oauthAccount.")
        email = oauth_account.get("emailAddress")
        if not email:
            raise ConfigError("Claude config oauthAccount is missing emailAddress.")
        secret = SecretPayload(
            oauth_account=copy.deepcopy(oauth_account),
            credentials=copy.deepcopy(live_state.credentials),
        )
        profile = ProfileMetadata(
            id=name,
            kind=PROFILE_KIND_OAUTH,
            label=name,
            email=str(email),
            organization_id=str(oauth_account.get("organizationUuid", "") or ""),
            organization_name=str(oauth_account.get("organizationName", "") or ""),
            account_uuid=str(oauth_account.get("accountUuid", "") or ""),
            secret_ref=name,
        )
        update_profile_auth_metadata(profile, secret)
        return profile, secret

    def _refresh_profile_if_needed(
        self,
        profile: ProfileMetadata,
        secret: SecretPayload,
        *,
        allow_failure: bool,
    ) -> tuple[ProfileMetadata, SecretPayload, str | None]:
        auth_state, _expires_at = classify_auth_state(secret)
        if auth_state != AUTH_STATE_REFRESHABLE:
            update_profile_auth_metadata(profile, secret)
            self.store.update_profile(profile)
            return profile, secret, None
        try:
            refreshed_secret = refresh_secret_payload(secret, request_refresh=self.refresh_request)
        except Exception as exc:
            error = str(exc)
            mark_refresh_failure(profile, error)
            self.store.upsert_profile(profile, secret)
            if allow_failure:
                return profile, secret, error
            raise ProfileReauthRequired(
                f"Profile '{profile.id}' requires reauthentication: {error}"
            ) from exc
        mark_refresh_success(profile, refreshed_secret)
        self.store.upsert_profile(profile, refreshed_secret)
        return profile, refreshed_secret, None

    @staticmethod
    def _get_scopes(secret: SecretPayload) -> list[str]:
        oauth = secret.credentials.get("claudeAiOauth", {})
        scopes = oauth.get("scopes", [])
        return [str(scope) for scope in scopes] if isinstance(scopes, list) else []


def build_sdk_env(profile: str, base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Convenience wrapper around ProfileManager.build_sdk_env."""
    return ProfileManager().build_sdk_env(profile, base_env=base_env)
