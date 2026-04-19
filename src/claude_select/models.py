"""Data models for profile metadata and Claude live state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

AUTH_STATE_OK = "ok"
AUTH_STATE_EXPIRING_SOON = "expiring_soon"
AUTH_STATE_REFRESHABLE = "refreshable"
AUTH_STATE_REAUTH_REQUIRED = "reauth_required"
AUTH_STATE_INVALID = "invalid"

PROFILE_KIND_OAUTH = "oauth"


def utc_now_iso() -> str:
    """Return the current UTC timestamp in ISO format."""
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(slots=True)
class ProfileMetadata:
    """Non-sensitive profile metadata persisted in state.json."""

    id: str
    kind: str
    label: str
    email: str
    organization_id: str = ""
    organization_name: str = ""
    account_uuid: str = ""
    auth_state: str = AUTH_STATE_INVALID
    expires_at: int | None = None
    secret_ref: str = ""
    updated_at: str = field(default_factory=utc_now_iso)
    last_refresh_at: str | None = None
    last_refresh_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the profile metadata to a JSON-safe dict."""
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "email": self.email,
            "organization_id": self.organization_id,
            "organization_name": self.organization_name,
            "account_uuid": self.account_uuid,
            "auth_state": self.auth_state,
            "expires_at": self.expires_at,
            "secret_ref": self.secret_ref,
            "updated_at": self.updated_at,
            "last_refresh_at": self.last_refresh_at,
            "last_refresh_error": self.last_refresh_error,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ProfileMetadata:
        """Deserialize a profile metadata dict."""
        return cls(
            id=str(value["id"]),
            kind=str(value["kind"]),
            label=str(value["label"]),
            email=str(value["email"]),
            organization_id=str(value.get("organization_id", "")),
            organization_name=str(value.get("organization_name", "")),
            account_uuid=str(value.get("account_uuid", "")),
            auth_state=str(value.get("auth_state", AUTH_STATE_INVALID)),
            expires_at=value.get("expires_at"),
            secret_ref=str(value.get("secret_ref", value["id"])),
            updated_at=str(value.get("updated_at", utc_now_iso())),
            last_refresh_at=value.get("last_refresh_at"),
            last_refresh_error=value.get("last_refresh_error"),
        )


@dataclass(slots=True)
class SecretPayload:
    """Sensitive auth material stored separately from the profile metadata."""

    oauth_account: dict[str, Any]
    credentials: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Serialize the secret payload."""
        return {
            "oauthAccount": self.oauth_account,
            "credentials": self.credentials,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> SecretPayload:
        """Deserialize a secret payload dict."""
        return cls(
            oauth_account=dict(value.get("oauthAccount", {})),
            credentials=dict(value.get("credentials", {})),
        )


@dataclass(slots=True)
class LiveState:
    """Claude live runtime state."""

    config: dict[str, Any]
    credentials: dict[str, Any]


@dataclass(slots=True)
class StateFile:
    """In-memory representation of state.json."""

    version: int = 1
    current_cli_profile: str | None = None
    default_sdk_profile: str | None = None
    profiles: dict[str, ProfileMetadata] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the state file."""
        return {
            "version": self.version,
            "current_cli_profile": self.current_cli_profile,
            "default_sdk_profile": self.default_sdk_profile,
            "profiles": {key: profile.to_dict() for key, profile in sorted(self.profiles.items())},
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> StateFile:
        """Deserialize a state file dict."""
        profiles = {
            key: ProfileMetadata.from_dict(profile)
            for key, profile in dict(value.get("profiles", {})).items()
        }
        return cls(
            version=int(value.get("version", 1)),
            current_cli_profile=value.get("current_cli_profile"),
            default_sdk_profile=value.get("default_sdk_profile"),
            profiles=profiles,
        )
