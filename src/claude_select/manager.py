"""High-level auth registry manager and SDK helpers."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from claude_select.exceptions import (
    AccountExistsError,
    AccountKindError,
    AccountNotFoundError,
    AccountSelectionError,
    AuthExpiredError,
    ConfigError,
)
from claude_select.live_state import ClaudeAuthBackend
from claude_select.models import (
    AUTH_KIND_CLI_SNAPSHOT,
    AUTH_KIND_TOKEN,
    STATUS_EXPIRED,
    AccountDetails,
    AccountRecord,
    AuthSnapshot,
    parse_iso8601,
    utc_now,
    utc_now_iso,
)
from claude_select.store import AuthRegistry
from claude_select.usage import (
    OAuthUsageProvider,
    UsageProvider,
    remaining_percentage,
    reset_countdown,
)

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
TOKEN_PROFILE_API_URLS = (
    "https://api.anthropic.com/api/oauth/profile",
    "https://claude.ai/api/oauth/profile",
)
TOKEN_PROFILE_BETA_HEADER = "oauth-2025-04-20"


class AuthManager:
    """Manage local Claude auth snapshots for CLI and SDK consumption."""

    def __init__(
        self,
        registry: AuthRegistry | None = None,
        auth_backend: ClaudeAuthBackend | None = None,
        usage_provider: UsageProvider | None = None,
        token_metadata_fetcher: Callable[[str], dict[str, Any]] | None = None,
    ):
        self.registry = registry or AuthRegistry()
        self.auth_backend = auth_backend or ClaudeAuthBackend()
        self.usage_provider = usage_provider or OAuthUsageProvider(self.registry)
        self.token_metadata_fetcher = token_metadata_fetcher or self._fetch_token_metadata

    SDK_FIVE_HOUR_LIMIT_PERCENT = 100.0
    SDK_SEVEN_DAY_LIMIT_PERCENT = 100.0

    def list_accounts(self, include_usage: bool = False) -> list[dict[str, Any]]:
        """Return account records as dictionaries for CLI/SDK output."""
        now = utc_now()
        rows = []
        for record in self.registry.list_accounts():
            payload = asdict(record)
            payload["status"] = record.status(now)
            payload["expires_in"] = record.expires_in(now)
            payload["kind_label"] = self._kind_label(record)
            payload["display_name"] = self.format_account_label(payload)
            if include_usage:
                if record.auth_kind == AUTH_KIND_TOKEN:
                    payload["usage"] = None
                    payload["quota_5h_left"] = "n/a"
                    payload["quota_5h_reset"] = "n/a"
                    payload["quota_7d_left"] = "n/a"
                    payload["quota_7d_reset"] = "n/a"
                else:
                    usage = self._usage_for_alias(record.alias)
                    payload["usage"] = usage
                    payload["quota_5h_left"] = self._format_window_remaining(usage, "five_hour")
                    payload["quota_5h_reset"] = self._format_window_reset(usage, "five_hour")
                    payload["quota_7d_left"] = self._format_window_remaining(usage, "seven_day")
                    payload["quota_7d_reset"] = self._format_window_reset(usage, "seven_day")
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

    def add_token_account(
        self,
        alias: str,
        token: str,
        *,
        email: str,
        organization_name: str = "",
        organization_id: str = "",
        account_uuid: str = "",
        overwrite: bool = True,
    ) -> dict[str, Any]:
        """Store or attach a long-lived setup-token entry for SDK/program usage."""
        normalized = self._normalize_alias(alias)
        normalized_email = email.strip()
        if not normalized_email:
            raise AccountSelectionError("Email cannot be empty for token entries.")
        snapshot = self._build_token_snapshot(
            token=token,
            email=normalized_email,
            organization_name=organization_name.strip(),
            organization_id=organization_id.strip(),
            account_uuid=account_uuid.strip(),
        )
        expires_at = self._one_year_expiry_epoch_ms()
        try:
            existing = self.registry.get_account(normalized)
        except AccountNotFoundError:
            existing = None
        if existing is None:
            record = self._upsert_snapshot(
                normalized,
                snapshot,
                auth_kind=AUTH_KIND_TOKEN,
                expires_at_override=expires_at,
            )
        elif existing.record.auth_kind == AUTH_KIND_CLI_SNAPSHOT:
            self.registry.attach_sdk_token(
                alias=normalized,
                captured_at=utc_now_iso(),
                expires_at=expires_at,
                snapshot=snapshot,
            )
            record = self.registry.get_account(normalized).record
        else:
            if not overwrite:
                raise AccountExistsError(f"Account '{normalized}' already exists.")
            record = self._upsert_snapshot(
                normalized,
                snapshot,
                auth_kind=AUTH_KIND_TOKEN,
                expires_at_override=expires_at,
            )
        return self._record_payload(record)

    def resolve_token_metadata(self, token: str) -> dict[str, str]:
        """Resolve token metadata for one long-lived setup-token entry.

        This is a best-effort lookup. Claude does not currently document a stable
        third-party metadata endpoint for `claude setup-token`, so failures should
        fall back to prompting the user for missing fields.
        """
        normalized_token = token.strip()
        if not normalized_token:
            raise AccountSelectionError("Token cannot be empty.")
        try:
            raw = self.token_metadata_fetcher(normalized_token)
        except Exception:
            return {}
        return self._normalize_token_metadata(raw)

    def probe_token(self, token: str) -> dict[str, Any]:
        """Probe one long-lived token and return best-effort validation details."""
        normalized_token = token.strip()
        if not normalized_token:
            raise AccountSelectionError("Token cannot be empty.")
        try:
            raw = self.token_metadata_fetcher(normalized_token)
        except urllib.error.HTTPError as exc:
            if exc.code == 403:
                reason = self._extract_http_error_reason(exc)
                warning = (
                    "Profile metadata is unavailable for this token scope."
                    if "scope requirement" in reason.lower()
                    else "Profile metadata could not be read for this token."
                )
                return {
                    "valid": True,
                    "metadata": {},
                    "error": None,
                    "warning": warning,
                }
            return {
                "valid": False,
                "metadata": {},
                "error": str(exc),
                "warning": None,
            }
        except Exception as exc:
            return {
                "valid": False,
                "metadata": {},
                "error": str(exc),
                "warning": None,
            }
        return {
            "valid": True,
            "metadata": self._normalize_token_metadata(raw),
            "error": None,
            "warning": None,
        }

    def relogin_account(self, alias: str) -> dict[str, Any]:
        """Overwrite an existing account using the current live auth state."""
        normalized = self._normalize_alias(alias)
        details = self.registry.get_account(normalized)
        if details.record.auth_kind != AUTH_KIND_CLI_SNAPSHOT:
            raise AccountKindError(
                f"Account '{normalized}' is a token entry and cannot be relogged from Claude CLI."
            )
        snapshot = self.auth_backend.read_snapshot()
        record = self._upsert_snapshot(normalized, snapshot)
        return self._record_payload(record)

    def sync_current_account(self) -> dict[str, Any]:
        """Sync Claude's current live auth state back into the matching registry entry."""
        snapshot = self.auth_backend.read_snapshot()
        matches = self._matching_aliases(snapshot)
        if not matches:
            return {
                "status": "unregistered",
                "matched_alias": None,
                "updated": False,
                "message": "Current Claude live account is not registered.",
            }
        if len(matches) > 1:
            return {
                "status": "ambiguous",
                "matched_alias": None,
                "updated": False,
                "message": "Current Claude live account matches multiple aliases.",
                "candidates": matches,
            }
        alias = matches[0]
        details = self.registry.get_account(alias)
        before = details.snapshot
        changed = self._snapshot_changed(before, snapshot)
        if changed:
            record = self._sync_snapshot(alias, snapshot)
            return {
                "status": "synced",
                "matched_alias": alias,
                "updated": True,
                "record": self._record_payload(record),
                "previous_expires_at": before.expires_at(),
                "current_expires_at": snapshot.expires_at(),
                "message": f"Synced current live auth state into '{alias}'.",
            }
        return {
            "status": "unchanged",
            "matched_alias": alias,
            "updated": False,
            "record": self._record_payload(details.record),
            "previous_expires_at": before.expires_at(),
            "current_expires_at": snapshot.expires_at(),
            "message": f"Current live auth state already matches '{alias}'.",
        }

    def remove_account(self, alias: str) -> None:
        """Delete an account from the registry."""
        self.registry.remove_account(self._normalize_alias(alias))

    def select_account(self, alias: str) -> dict[str, Any]:
        """Write a stored auth snapshot back into Claude's live auth backend."""
        details = self.registry.get_account(self._normalize_alias(alias))
        if details.record.auth_kind != AUTH_KIND_CLI_SNAPSHOT:
            raise AccountKindError(
                f"Account '{details.record.alias}' is a token entry and cannot be selected for CLI."
            )
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
        sdk_snapshot = self._sdk_snapshot_for_details(details)
        if sdk_snapshot is None and details.record.status() == STATUS_EXPIRED:
            raise AuthExpiredError(
                f"Account '{details.record.alias}' is expired. Run relogin before using it."
            )
        env = dict(base_env if base_env is not None else os.environ)
        for key in CONFLICTING_AUTH_ENV_VARS:
            env.pop(key, None)
        effective_snapshot = sdk_snapshot or details.snapshot
        oauth = effective_snapshot.credentials["claudeAiOauth"]
        env["CLAUDE_CODE_OAUTH_TOKEN"] = str(oauth["accessToken"])
        scopes = effective_snapshot.scopes()
        if scopes:
            env["CLAUDE_CODE_OAUTH_SCOPES"] = " ".join(scopes)
        return env

    def pick_sdk_account(
        self,
        preferred_alias: str | None = None,
    ) -> dict[str, Any]:
        """Deprecated quota-aware token auto-selection."""
        raise AccountSelectionError(
            "Quota-aware SDK auto-selection is not supported for long-lived token entries. "
            "Choose an alias explicitly with build_sdk_env(alias)."
        )

    def build_sdk_env_auto(
        self,
        preferred_alias: str | None = None,
        base_env: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Deprecated quota-aware token auto-selection."""
        _ = preferred_alias
        _ = base_env
        raise AccountSelectionError(
            "Quota-aware SDK auto-selection is not supported for long-lived token entries. "
            "Choose an alias explicitly with build_sdk_env(alias)."
        )

    def export_sdk_auth(self, alias: str) -> dict[str, Any]:
        """Return a structured auth payload for SDK consumers."""
        details = self.registry.get_account(self._normalize_alias(alias))
        sdk_snapshot = self._sdk_snapshot_for_details(details)
        if sdk_snapshot is None and details.record.status() == STATUS_EXPIRED:
            raise AuthExpiredError(
                f"Account '{details.record.alias}' is expired. Run relogin before using it."
            )
        effective_snapshot = sdk_snapshot or details.snapshot
        return {
            "alias": details.record.alias,
            "email": details.record.email,
            "status": details.record.status(),
            "expires_at": details.record.expires_at,
            "oauth_account": effective_snapshot.oauth_account,
            "credentials": effective_snapshot.credentials,
        }

    def current_alias(self) -> str | None:
        """Return the last selected CLI alias if any."""
        return self.registry.get_current_alias()

    def current_live_account(self) -> dict[str, Any]:
        """Return the current Claude live auth state with optional registry match."""
        snapshot = self.auth_backend.read_snapshot()
        oauth_account = snapshot.oauth_account
        expires_at = snapshot.expires_at()
        payload: dict[str, Any] = {
            "matched_alias": self._match_snapshot_alias(snapshot),
            "email": str(oauth_account.get("emailAddress", "") or ""),
            "organization_name": str(oauth_account.get("organizationName", "") or ""),
            "organization_id": str(oauth_account.get("organizationUuid", "") or ""),
            "account_uuid": str(oauth_account.get("accountUuid", "") or ""),
            "expires_at": expires_at,
            "status": self._status_from_expires_at(expires_at),
            "expires_in": self._format_expires_in(expires_at),
            "targets": self.auth_backend.describe_targets(),
        }
        auth_status = self.auth_backend.read_auth_status()
        payload["auth_status"] = auth_status
        if isinstance(auth_status, dict):
            payload["logged_in"] = auth_status.get("loggedIn")
            payload["auth_method"] = auth_status.get("authMethod")
            payload["api_provider"] = auth_status.get("apiProvider")
            payload["subscription_type"] = auth_status.get("subscriptionType")
        usage = self._usage_for_snapshot(
            snapshot,
            payload["matched_alias"] or self._usage_cache_key_for_snapshot(snapshot),
        )
        payload["usage"] = usage
        payload["quota_5h_left"] = self._format_window_remaining(usage, "five_hour")
        payload["quota_5h_reset"] = self._format_window_reset(usage, "five_hour")
        payload["quota_7d_left"] = self._format_window_remaining(usage, "seven_day")
        payload["quota_7d_reset"] = self._format_window_reset(usage, "seven_day")
        return payload

    def get_live_quota(self) -> dict[str, Any]:
        """Return quota details for Claude's current live auth state."""
        current = self.current_live_account()
        return self._quota_payload(
            alias=current["matched_alias"],
            email=current["email"],
            organization_name=current["organization_name"],
            organization_id=current["organization_id"],
            account_uuid=current["account_uuid"],
            status=current["status"],
            expires_at=current["expires_at"],
            expires_in=current["expires_in"],
            usage=current["usage"],
        )

    def get_account_quota(self, alias: str) -> dict[str, Any]:
        """Return quota details for one stored account alias."""
        details = self.registry.get_account(self._normalize_alias(alias))
        if details.record.auth_kind == AUTH_KIND_TOKEN:
            return self._quota_payload(
                alias=details.record.alias,
                email=details.record.email,
                organization_name=details.record.organization_name,
                organization_id=details.record.organization_id,
                account_uuid=details.record.account_uuid,
                status=details.record.status(),
                expires_at=details.record.expires_at,
                expires_in=details.record.expires_in(),
                usage=None,
                unsupported_reason="quota unsupported for long-lived token entries",
            )
        usage = self._usage_for_alias(details.record.alias)
        return self._quota_payload(
            alias=details.record.alias,
            email=details.record.email,
            organization_name=details.record.organization_name,
            organization_id=details.record.organization_id,
            account_uuid=details.record.account_uuid,
            status=details.record.status(),
            expires_at=details.record.expires_at,
            expires_in=details.record.expires_in(),
            usage=usage,
        )

    def list_account_quotas(self) -> list[dict[str, Any]]:
        """Return quota details for every stored account alias."""
        return [self.get_account_quota(record.alias) for record in self.registry.list_accounts()]

    def render_table(self, include_usage: bool = False) -> str:
        """Render the current account list as a plain-text table."""
        rows = self.list_accounts(include_usage=include_usage)
        if not rows:
            return "No accounts have been captured yet."
        headers = [
            "Alias",
            "Kind",
            "Email",
            "Organization",
            "Status",
            "Expires In",
            "Last Selected",
            "Last Synced",
        ]
        if include_usage:
            headers.extend(["5h Left", "5h Reset", "7d Left", "7d Reset"])
        body = [
            self._table_row(row, include_usage=include_usage)
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

    def render_current_live_account(self) -> str:
        """Render a short summary of Claude's current live auth state."""
        current = self.current_live_account()
        lines = ["Current Claude live account"]
        lines.append(f"  matched alias: {current['matched_alias'] or '-'}")
        lines.append(f"  email: {current['email'] or '-'}")
        lines.append(f"  organization: {current['organization_name'] or '-'}")
        lines.append(f"  expires in: {current['expires_in']}")
        auth_method = current.get("auth_method")
        if auth_method:
            lines.append(f"  auth method: {auth_method}")
        subscription_type = current.get("subscription_type")
        if subscription_type:
            lines.append(f"  subscription: {subscription_type}")
        lines.append(f"  5h quota left: {current['quota_5h_left']}")
        lines.append(f"  5h resets in: {current['quota_5h_reset']}")
        lines.append(f"  7d quota left: {current['quota_7d_left']}")
        lines.append(f"  7d resets in: {current['quota_7d_reset']}")
        for target in current["targets"]:
            lines.append(f"  target: {target}")
        return "\n".join(lines)

    def wait_for_login(self, launch: bool) -> None:
        """Guide the user through logging in with the Claude CLI."""
        if launch:
            if self.auth_backend.run_auth_login():
                print("Launching `claude auth login` in this terminal.")
                print("Complete account authorization, then return here.")
            else:
                print("`claude` was not found in PATH.")
                print("Run `claude auth login`, complete authorization, then return here.")
        else:
            print("Run `claude auth login` in another shell, then return here.")
        input("Press Enter after login is complete...")

    def choose_alias_interactively(self) -> str:
        """Prompt the user to choose one of the stored aliases."""
        accounts = self.registry.list_accounts()
        if not accounts:
            raise AccountSelectionError("No accounts are available.")
        print(self.render_table())
        raw = input("Select an account by alias: ").strip()
        normalized = self._normalize_alias(raw)
        cli_aliases = {
            account.alias for account in accounts if account.auth_kind == AUTH_KIND_CLI_SNAPSHOT
        }
        if normalized not in cli_aliases:
            raise AccountSelectionError(f"Unknown account alias: {normalized}")
        return normalized

    def _upsert_snapshot(
        self,
        alias: str,
        snapshot: AuthSnapshot,
        *,
        auth_kind: str = AUTH_KIND_CLI_SNAPSHOT,
        expires_at_override: int | None = None,
    ) -> AccountRecord:
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
            auth_kind=auth_kind,
            email=str(email),
            organization_name=str(oauth_account.get("organizationName", "") or ""),
            organization_id=str(oauth_account.get("organizationUuid", "") or ""),
            account_uuid=str(oauth_account.get("accountUuid", "") or ""),
            captured_at=captured_at,
            expires_at=(
                expires_at_override
                if expires_at_override is not None
                else snapshot.expires_at()
            ),
            last_selected_at=existing_last_selected,
            source="claude_cli" if auth_kind == AUTH_KIND_CLI_SNAPSHOT else "claude_setup_token",
            snapshot=snapshot,
            last_synced_at=captured_at,
        )
        return self.registry.get_account(alias).record

    def _sync_snapshot(self, alias: str, snapshot: AuthSnapshot) -> AccountRecord:
        oauth_account = snapshot.oauth_account
        email = oauth_account.get("emailAddress")
        if not email:
            raise ConfigError("Claude oauthAccount is missing emailAddress.")
        existing = self.registry.get_account(alias).record
        self.registry.upsert_account(
            alias=alias,
            auth_kind=existing.auth_kind,
            email=str(email),
            organization_name=str(oauth_account.get("organizationName", "") or ""),
            organization_id=str(oauth_account.get("organizationUuid", "") or ""),
            account_uuid=str(oauth_account.get("accountUuid", "") or ""),
            captured_at=existing.captured_at,
            expires_at=snapshot.expires_at(),
            last_selected_at=existing.last_selected_at,
            source=existing.source,
            snapshot=snapshot,
            last_synced_at=utc_now_iso(),
        )
        return self.registry.get_account(alias).record

    @staticmethod
    def _build_token_snapshot(
        *,
        token: str,
        email: str,
        organization_name: str,
        organization_id: str,
        account_uuid: str,
    ) -> AuthSnapshot:
        normalized_token = token.strip()
        if not normalized_token:
            raise AccountSelectionError("Token cannot be empty.")
        return AuthSnapshot(
            oauth_account={
                "emailAddress": email,
                "organizationName": organization_name,
                "organizationUuid": organization_id,
                "accountUuid": account_uuid,
            },
            credentials={
                "claudeAiOauth": {
                    "accessToken": normalized_token,
                    "scopes": [],
                }
            },
        )

    def _fetch_token_metadata(self, token: str) -> dict[str, Any]:
        last_error: Exception | None = None
        for url in TOKEN_PROFILE_API_URLS:
            request = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "anthropic-beta": TOKEN_PROFILE_BETA_HEADER,
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=10.0) as response:
                    return json.loads(response.read().decode("utf-8"))
            except (urllib.error.URLError, json.JSONDecodeError) as exc:
                last_error = exc
                continue
        if last_error is not None:
            raise last_error
        raise AccountSelectionError("Unable to resolve token metadata.")

    @staticmethod
    def _extract_http_error_reason(exc: urllib.error.HTTPError) -> str:
        try:
            payload = exc.read().decode("utf-8", errors="replace")
        except Exception:
            return str(exc)
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            return payload or str(exc)
        error = parsed.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message
        if isinstance(error, str) and error.strip():
            return error
        message = parsed.get("message")
        if isinstance(message, str) and message.strip():
            return message
        return payload or str(exc)

    @staticmethod
    def _normalize_token_metadata(raw: dict[str, Any]) -> dict[str, str]:
        if not isinstance(raw, dict):
            return {}

        def _string(value: object) -> str:
            return str(value).strip() if value is not None else ""

        organization = raw.get("organization")
        if not isinstance(organization, dict):
            organization = {}

        metadata = {
            "email": (
                _string(raw.get("emailAddress"))
                or _string(raw.get("email"))
            ),
            "organization_name": (
                _string(raw.get("organizationName"))
                or _string(organization.get("name"))
            ),
            "organization_id": (
                _string(raw.get("organizationUuid"))
                or _string(raw.get("organizationId"))
                or _string(organization.get("uuid"))
                or _string(organization.get("id"))
            ),
            "account_uuid": (
                _string(raw.get("accountUuid"))
                or _string(raw.get("accountId"))
                or _string(raw.get("uuid"))
                or _string(raw.get("id"))
            ),
        }
        return {key: value for key, value in metadata.items() if value}

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
        payload["kind_label"] = self._kind_label(record)
        payload["display_name"] = self.format_account_label(payload)
        return payload

    @staticmethod
    def format_account_label(account: AccountRecord | dict[str, Any]) -> str:
        """Return a compact human-readable label with alias, email, and org."""
        if isinstance(account, AccountRecord):
            alias = account.alias
            auth_kind = AuthManager._kind_label(account)
            email = account.email
            organization_name = account.organization_name
        else:
            alias = str(account["alias"])
            auth_kind = str(account.get("kind_label") or account.get("auth_kind", "") or "")
            email = str(account["email"])
            organization_name = str(account.get("organization_name", "") or "")
        kind_prefix = "[token] " if auth_kind == "token" else ""
        if organization_name:
            return f"{kind_prefix}{alias} <{email}> [{organization_name}]"
        return f"{kind_prefix}{alias} <{email}>"

    def _match_snapshot_alias(self, snapshot: AuthSnapshot) -> str | None:
        matches = self._matching_aliases(snapshot)
        if len(matches) == 1:
            return matches[0]
        return None

    def _matching_aliases(self, snapshot: AuthSnapshot) -> list[str]:
        oauth = snapshot.oauth_account
        snapshot_email = str(oauth.get("emailAddress", "") or "")
        snapshot_org_id = str(oauth.get("organizationUuid", "") or "")
        snapshot_account_uuid = str(oauth.get("accountUuid", "") or "")
        matches: list[str] = []
        for record in self.registry.list_accounts():
            if record.auth_kind != AUTH_KIND_CLI_SNAPSHOT:
                continue
            details = self.registry.get_account(record.alias)
            candidate = details.snapshot.oauth_account
            candidate_email = str(candidate.get("emailAddress", "") or "")
            candidate_org_id = str(candidate.get("organizationUuid", "") or "")
            candidate_account_uuid = str(candidate.get("accountUuid", "") or "")
            if candidate_email != snapshot_email:
                continue
            if snapshot_org_id and candidate_org_id != snapshot_org_id:
                continue
            if (
                snapshot_account_uuid
                and candidate_account_uuid
                and candidate_account_uuid != snapshot_account_uuid
            ):
                continue
            matches.append(record.alias)
        return matches

    @staticmethod
    def _snapshot_changed(before: AuthSnapshot, after: AuthSnapshot) -> bool:
        return (
            before.oauth_account != after.oauth_account
            or before.credentials != after.credentials
        )

    def _usage_for_alias(self, alias: str) -> dict[str, Any] | None:
        details = self.registry.get_account(alias)
        return self._usage_for_snapshot(details.snapshot, f"alias:{alias}")

    def _sdk_candidate_available(self, row: dict[str, Any]) -> bool:
        usage = row.get("usage")
        if not isinstance(usage, dict) or usage.get("stale"):
            return False
        five_hour = self._window_payload(usage, "five_hour")
        seven_day = self._window_payload(usage, "seven_day")
        return (
            not self._window_limit_reached(five_hour, self.SDK_FIVE_HOUR_LIMIT_PERCENT)
            and not self._window_limit_reached(seven_day, self.SDK_SEVEN_DAY_LIMIT_PERCENT)
        )

    def _sdk_candidate_sort_key(self, row: dict[str, Any]) -> tuple[float, float, str]:
        usage = row.get("usage")
        five_hour_remaining = remaining_percentage(self._window_payload(usage, "five_hour")) or 0.0
        seven_day_remaining = remaining_percentage(self._window_payload(usage, "seven_day")) or 0.0
        return (five_hour_remaining, seven_day_remaining, str(row["alias"]))

    @staticmethod
    def _window_limit_reached(window: dict[str, Any] | None, limit: float) -> bool:
        if not window:
            return True
        used = window.get("used_percentage")
        if not isinstance(used, (int, float)):
            return True
        return float(used) >= limit

    def _usage_for_snapshot(self, snapshot: AuthSnapshot, cache_key: str) -> dict[str, Any] | None:
        resolved_key = cache_key if cache_key.startswith("alias:") else f"live:{cache_key}"
        try:
            return self.usage_provider.get_usage(snapshot, resolved_key)
        except Exception:
            return None

    @staticmethod
    def _usage_cache_key_for_snapshot(snapshot: AuthSnapshot) -> str:
        oauth = snapshot.oauth_account
        return "|".join(
            [
                str(oauth.get("emailAddress", "") or ""),
                str(oauth.get("organizationUuid", "") or ""),
                str(oauth.get("accountUuid", "") or ""),
            ]
        )

    @staticmethod
    def _window_payload(
        usage: dict[str, Any] | None,
        window_name: str,
    ) -> dict[str, Any] | None:
        if not usage:
            return None
        window = usage.get(window_name)
        return window if isinstance(window, dict) else None

    def _format_window_remaining(self, usage: dict[str, Any] | None, window_name: str) -> str:
        remaining = remaining_percentage(self._window_payload(usage, window_name))
        if remaining is None:
            return "unknown"
        suffix = "~" if usage and usage.get("stale") else ""
        return f"{remaining:.1f}%{suffix}"

    def _format_window_reset(self, usage: dict[str, Any] | None, window_name: str) -> str:
        reset = reset_countdown(self._window_payload(usage, window_name))
        if usage and usage.get("stale") and reset != "unknown":
            return f"{reset}~"
        return reset

    def _quota_payload(
        self,
        *,
        alias: str | None,
        email: str,
        organization_name: str,
        organization_id: str,
        account_uuid: str,
        status: str,
        expires_at: int | None,
        expires_in: str,
        usage: dict[str, Any] | None,
        unsupported_reason: str | None = None,
    ) -> dict[str, Any]:
        if unsupported_reason:
            return {
                "alias": alias,
                "email": email,
                "organization_name": organization_name,
                "organization_id": organization_id,
                "account_uuid": account_uuid,
                "status": status,
                "expires_at": expires_at,
                "expires_in": expires_in,
                "available": False,
                "stale": False,
                "error": unsupported_reason,
                "five_hour": None,
                "seven_day": None,
                "seven_day_opus": None,
                "extra_usage": None,
                "fetched_at": None,
                "quota_5h_left": "n/a",
                "quota_5h_reset": "n/a",
                "quota_7d_left": "n/a",
                "quota_7d_reset": "n/a",
            }
        return {
            "alias": alias,
            "email": email,
            "organization_name": organization_name,
            "organization_id": organization_id,
            "account_uuid": account_uuid,
            "status": status,
            "expires_at": expires_at,
            "expires_in": expires_in,
            "available": usage is not None,
            "stale": bool(usage and usage.get("stale")),
            "error": usage.get("error") if usage else "usage unavailable",
            "five_hour": self._window_payload(usage, "five_hour"),
            "seven_day": self._window_payload(usage, "seven_day"),
            "seven_day_opus": self._window_payload(usage, "seven_day_opus"),
            "extra_usage": usage.get("extra_usage") if usage else None,
            "fetched_at": usage.get("fetched_at") if usage else None,
            "quota_5h_left": self._format_window_remaining(usage, "five_hour"),
            "quota_5h_reset": self._format_window_reset(usage, "five_hour"),
            "quota_7d_left": self._format_window_remaining(usage, "seven_day"),
            "quota_7d_reset": self._format_window_reset(usage, "seven_day"),
        }

    def _table_row(self, row: dict[str, Any], *, include_usage: bool) -> list[str]:
        values = [
            row["alias"],
            self._display_auth_kind(str(row.get("kind_label") or row["auth_kind"])),
            row["email"],
            row["organization_name"] or "-",
            row["status"],
            row["expires_in"],
            self._format_last_selected(row["last_selected_at"]),
            self._format_last_selected(row["last_synced_at"]),
        ]
        if include_usage:
            values.extend(
                [
                    row["quota_5h_left"],
                    row["quota_5h_reset"],
                    row["quota_7d_left"],
                    row["quota_7d_reset"],
                ]
            )
        return [str(value) for value in values]

    @staticmethod
    def _status_from_expires_at(expires_at: int | None) -> str:
        record = AccountRecord(
            alias="",
            auth_kind=AUTH_KIND_CLI_SNAPSHOT,
            email="",
            organization_name="",
            organization_id="",
            account_uuid="",
            captured_at="",
            expires_at=expires_at,
            last_selected_at=None,
            source="",
        )
        return record.status()

    @staticmethod
    def _format_expires_in(expires_at: int | None) -> str:
        record = AccountRecord(
            alias="",
            auth_kind=AUTH_KIND_CLI_SNAPSHOT,
            email="",
            organization_name="",
            organization_id="",
            account_uuid="",
            captured_at="",
            expires_at=expires_at,
            last_selected_at=None,
            source="",
        )
        return record.expires_in()

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

    @staticmethod
    def _display_auth_kind(auth_kind: str) -> str:
        if auth_kind == "cli+token":
            return "cli+token"
        if auth_kind == AUTH_KIND_CLI_SNAPSHOT:
            return "cli"
        if auth_kind == AUTH_KIND_TOKEN:
            return "token"
        return auth_kind

    @staticmethod
    def _kind_label(record: AccountRecord) -> str:
        if record.auth_kind == AUTH_KIND_CLI_SNAPSHOT and record.has_sdk_token:
            return "cli+token"
        return record.auth_kind

    @staticmethod
    def _sdk_snapshot_for_details(details: AccountDetails) -> AuthSnapshot | None:
        if details.sdk_token_snapshot is not None:
            return details.sdk_token_snapshot
        if details.record.auth_kind == AUTH_KIND_TOKEN:
            return details.snapshot
        return None

    @staticmethod
    def _one_year_expiry_epoch_ms() -> int:
        return int((utc_now().timestamp() + 365 * 24 * 60 * 60) * 1000)


def build_sdk_env(alias: str, base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Convenience wrapper around AuthManager.build_sdk_env."""
    return AuthManager().build_sdk_env(alias, base_env=base_env)


def build_sdk_env_auto(
    preferred_alias: str | None = None,
    base_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Convenience wrapper around AuthManager.build_sdk_env_auto."""
    return AuthManager().build_sdk_env_auto(preferred_alias=preferred_alias, base_env=base_env)
