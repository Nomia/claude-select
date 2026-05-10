"""High-level auth registry manager and SDK helpers."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import asdict
from typing import Any

from claude_select.exceptions import (
    AccountExistsError,
    AccountNotFoundError,
    AccountSelectionError,
    AuthExpiredError,
    ConfigError,
)
from claude_select.live_state import ClaudeAuthBackend
from claude_select.models import (
    STATUS_EXPIRED,
    AccountDetails,
    AccountRecord,
    AuthSnapshot,
    parse_iso8601,
    utc_now,
    utc_now_iso,
)
from claude_select.store import AuthRegistry

ALIAS_RE = re.compile(r"^[A-Za-z0-9._-]+$")
CONFLICTING_AUTH_ENV_VARS = {
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_SCOPES",
}


class AuthManager:
    """Manage local Claude auth snapshots for CLI and SDK consumption."""

    def __init__(
        self,
        registry: AuthRegistry | None = None,
        auth_backend: ClaudeAuthBackend | None = None,
    ):
        self.registry = registry or AuthRegistry()
        self.auth_backend = auth_backend or ClaudeAuthBackend()

    def list_accounts(self) -> list[dict[str, Any]]:
        """Return account records as dictionaries for CLI/SDK output."""
        now = utc_now()
        rows = []
        for record in self.registry.list_accounts():
            payload = asdict(record)
            payload["status"] = record.status(now)
            payload["expires_in"] = record.expires_in(now)
            rows.append(payload)
        return rows

    def get_account(self, alias: str) -> AccountDetails:
        """Return one account and snapshot."""
        return self.registry.get_account(self._normalize_alias(alias))

    def capture_current_account(self, alias: str, overwrite: bool = True) -> dict[str, Any]:
        """Capture the current live auth state into the registry."""
        normalized = self._normalize_alias(alias)
        if not overwrite:
            existing_aliases = {record.alias for record in self.registry.list_accounts()}
            if normalized in existing_aliases:
                raise AccountExistsError(f"Account '{normalized}' already exists.")
        snapshot = self.auth_backend.read_snapshot()
        record = self._upsert_snapshot(normalized, snapshot)
        return self._record_payload(record)

    def relogin_account(self, alias: str) -> dict[str, Any]:
        """Overwrite an existing account using the current live auth state."""
        normalized = self._normalize_alias(alias)
        self.registry.get_account(normalized)
        snapshot = self.auth_backend.read_snapshot()
        record = self._upsert_snapshot(normalized, snapshot)
        return self._record_payload(record)

    def remove_account(self, alias: str) -> None:
        """Delete an account from the registry."""
        self.registry.remove_account(self._normalize_alias(alias))

    def select_account(self, alias: str) -> dict[str, Any]:
        """Write a stored auth snapshot back into Claude's live auth backend."""
        details = self.registry.get_account(self._normalize_alias(alias))
        if details.record.status() == STATUS_EXPIRED:
            raise AuthExpiredError(
                f"Account '{details.record.alias}' is expired. Run relogin before selecting it."
            )
        self.auth_backend.write_snapshot(details.snapshot)
        selected_at = utc_now_iso()
        self.registry.mark_selected(details.record.alias, selected_at)
        refreshed = self.registry.get_account(details.record.alias).record
        return self._record_payload(refreshed)

    def build_sdk_env(
        self,
        alias: str,
        base_env: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Return an env mapping for Claude Agent SDK usage.

        Captured auth is treated as a fixed snapshot. This tool does not try to
        refresh tokens automatically, so only the access token and scopes are
        exported for SDK consumption.
        """
        details = self.registry.get_account(self._normalize_alias(alias))
        if details.record.status() == STATUS_EXPIRED:
            raise AuthExpiredError(
                f"Account '{details.record.alias}' is expired. Run relogin before using it."
            )
        env = dict(base_env if base_env is not None else os.environ)
        for key in CONFLICTING_AUTH_ENV_VARS:
            env.pop(key, None)
        oauth = details.snapshot.credentials["claudeAiOauth"]
        env["CLAUDE_CODE_OAUTH_TOKEN"] = str(oauth["accessToken"])
        scopes = details.snapshot.scopes()
        if scopes:
            env["CLAUDE_CODE_OAUTH_SCOPES"] = " ".join(scopes)
        return env

    def export_sdk_auth(self, alias: str) -> dict[str, Any]:
        """Return a structured auth payload for SDK consumers."""
        details = self.registry.get_account(self._normalize_alias(alias))
        if details.record.status() == STATUS_EXPIRED:
            raise AuthExpiredError(
                f"Account '{details.record.alias}' is expired. Run relogin before using it."
            )
        return {
            "alias": details.record.alias,
            "email": details.record.email,
            "status": details.record.status(),
            "expires_at": details.record.expires_at,
            "oauth_account": details.snapshot.oauth_account,
            "credentials": details.snapshot.credentials,
        }

    def current_alias(self) -> str | None:
        """Return the last selected CLI alias if any."""
        return self.registry.get_current_alias()

    def render_table(self) -> str:
        """Render the current account list as a plain-text table."""
        rows = self.list_accounts()
        if not rows:
            return "No accounts have been captured yet."
        headers = ["Alias", "Email", "Status", "Expires In", "Last Selected"]
        body = [
            [
                row["alias"],
                row["email"],
                row["status"],
                row["expires_in"],
                self._format_last_selected(row["last_selected_at"]),
            ]
            for row in rows
        ]
        widths = [
            max(len(headers[index]), *(len(str(row[index])) for row in body))
            for index in range(len(headers))
        ]
        lines = [
            "  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)),
            "  ".join("-" * width for width in widths),
        ]
        lines.extend(
            "  ".join(str(value).ljust(widths[index]) for index, value in enumerate(row))
            for row in body
        )
        return "\n".join(lines)

    def wait_for_login(self, launch: bool) -> None:
        """Optionally launch Claude and block until the user confirms login completion."""
        if launch and shutil.which("claude"):
            subprocess.run(["claude"], check=False)
        else:
            print("Complete /login in Claude Code, then return here.")
        input("Press Enter after login is complete...")

    def choose_alias_interactively(self) -> str:
        """Prompt the user to choose one of the stored aliases."""
        accounts = self.registry.list_accounts()
        if not accounts:
            raise AccountSelectionError("No accounts are available.")
        print(self.render_table())
        raw = input("Select an account by alias: ").strip()
        normalized = self._normalize_alias(raw)
        if normalized not in {account.alias for account in accounts}:
            raise AccountSelectionError(f"Unknown account alias: {normalized}")
        return normalized

    def _upsert_snapshot(self, alias: str, snapshot: AuthSnapshot) -> AccountRecord:
        oauth_account = snapshot.oauth_account
        email = oauth_account.get("emailAddress")
        if not email:
            raise ConfigError("Claude oauthAccount is missing emailAddress.")
        captured_at = utc_now_iso()
        existing_last_selected = None
        try:
            existing_last_selected = self.registry.get_account(alias).record.last_selected_at
        except AccountNotFoundError:
            existing_last_selected = None
        self.registry.upsert_account(
            alias=alias,
            email=str(email),
            organization_name=str(oauth_account.get("organizationName", "") or ""),
            organization_id=str(oauth_account.get("organizationUuid", "") or ""),
            account_uuid=str(oauth_account.get("accountUuid", "") or ""),
            captured_at=captured_at,
            expires_at=snapshot.expires_at(),
            last_selected_at=existing_last_selected,
            source="claude_cli",
            snapshot=snapshot,
        )
        return self.registry.get_account(alias).record

    def _normalize_alias(self, alias: str) -> str:
        normalized = alias.strip()
        if not normalized:
            raise AccountSelectionError("Alias cannot be empty.")
        if not ALIAS_RE.match(normalized):
            raise AccountSelectionError(
                "Alias must contain only letters, numbers, dot, underscore, or dash."
            )
        return normalized

    def _record_payload(self, record: AccountRecord) -> dict[str, Any]:
        payload = asdict(record)
        payload["status"] = record.status()
        payload["expires_in"] = record.expires_in()
        return payload

    @staticmethod
    def _format_last_selected(value: str | None) -> str:
        if not value:
            return "-"
        dt = parse_iso8601(value)
        if dt is None:
            return value
        now = utc_now()
        delta = now - dt
        total_minutes = int(delta.total_seconds() // 60)
        if total_minutes < 1:
            return "just now"
        if total_minutes < 60:
            return f"{total_minutes}m ago"
        hours = total_minutes // 60
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        return f"{days}d ago"


def build_sdk_env(alias: str, base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Convenience wrapper around AuthManager.build_sdk_env."""
    return AuthManager().build_sdk_env(alias, base_env=base_env)
