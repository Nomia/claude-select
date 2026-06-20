"""High-level auth registry manager and SDK helpers."""

from __future__ import annotations

import http.client
import json
import os
import re
import shutil
import sqlite3
import subprocess
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
    ClaudeSelectError,
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

    RUNTIME_REFRESH_WINDOW_SECONDS = 5 * 60
    BACKGROUND_REFRESH_WINDOW_SECONDS = 30 * 60
    OAUTH_TOKEN_REFRESH_URL = "https://platform.claude.com/v1/oauth/token"

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

    def list_accounts(
        self,
        include_usage: bool = False,
        *,
        auto_refresh: bool = False,
        usage_mode: str = "foreground",
        usage_stale_after_seconds: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return account records as dictionaries for CLI/SDK output."""
        if auto_refresh:
            self._best_effort_auto_refresh_candidates()
        now = utc_now()
        rows = []
        for record in self.registry.list_accounts():
            payload = self._record_payload(record)
            payload["status"] = record.status(now)
            payload["expires_in"] = record.expires_in(now)
            if include_usage:
                quota = self.get_account_quota(
                    record.alias,
                    auto_refresh=False,
                    usage_mode=usage_mode,
                    usage_stale_after_seconds=usage_stale_after_seconds,
                )
                payload.update(
                    {
                        "usage": quota["usage"],
                        "available": quota["available"],
                        "stale": quota["stale"],
                        "error": quota["error"],
                        "fetched_at": quota["fetched_at"],
                        "five_hour": quota["five_hour"],
                        "seven_day": quota["seven_day"],
                        "seven_day_opus": quota["seven_day_opus"],
                        "extra_usage": quota["extra_usage"],
                        "quota_5h_left": quota["quota_5h_left"],
                        "quota_5h_reset": quota["quota_5h_reset"],
                        "quota_7d_left": quota["quota_7d_left"],
                        "quota_7d_reset": quota["quota_7d_reset"],
                    }
                )
            rows.append(payload)
        return rows

    def get_account(self, alias: str, *, auto_refresh: bool = False) -> AccountDetails:
        """Return one account and snapshot."""
        normalized = self._normalize_alias(alias)
        if auto_refresh:
            return self.refresh_if_needed(normalized, context="runtime")
        return self.registry.get_account(normalized)

    def list_cli_accounts(
        self,
        include_usage: bool = False,
        *,
        auto_refresh: bool = False,
        usage_mode: str = "foreground",
        usage_stale_after_seconds: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return only CLI-backed accounts."""
        return [
            row
            for row in self.list_accounts(
                include_usage=include_usage,
                auto_refresh=auto_refresh,
                usage_mode=usage_mode,
                usage_stale_after_seconds=usage_stale_after_seconds,
            )
            if row["auth_kind"] == AUTH_KIND_CLI_SNAPSHOT
        ]

    def list_token_accounts(
        self,
        include_usage: bool = False,
        *,
        usage_mode: str = "foreground",
        usage_stale_after_seconds: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return only token-only accounts."""
        return [
            row
            for row in self.list_accounts(
                include_usage=include_usage,
                usage_mode=usage_mode,
                usage_stale_after_seconds=usage_stale_after_seconds,
            )
            if row["auth_kind"] == AUTH_KIND_TOKEN
        ]

    def get_account_summary(
        self,
        alias: str,
        *,
        include_usage: bool = False,
        auto_refresh: bool = False,
    ) -> dict[str, Any]:
        """Return one account as a summary dictionary."""
        details = self.get_account(alias, auto_refresh=auto_refresh)
        payload = self._record_payload(details.record)
        if include_usage:
            quota = self.get_account_quota(details.record.alias, auto_refresh=False)
            payload["usage"] = quota["usage"]
            payload["quota_5h_left"] = quota["quota_5h_left"]
            payload["quota_5h_reset"] = quota["quota_5h_reset"]
            payload["quota_7d_left"] = quota["quota_7d_left"]
            payload["quota_7d_reset"] = quota["quota_7d_reset"]
        return payload

    def get_current_account_summary(self, *, include_usage: bool = True) -> dict[str, Any]:
        """Return a single summary payload for the current Claude live account."""
        current = self.current_live_account()
        payload = {
            "alias": current["matched_alias"],
            "email": current["email"],
            "organization_name": current["organization_name"],
            "organization_id": current["organization_id"],
            "account_uuid": current["account_uuid"],
            "status": current["status"],
            "expires_at": current["expires_at"],
            "expires_in": current["expires_in"],
            "auth_method": current.get("auth_method"),
            "subscription_type": current.get("subscription_type"),
            "targets": current["targets"],
        }
        if include_usage:
            payload["usage"] = current["usage"]
            payload["quota_5h_left"] = current["quota_5h_left"]
            payload["quota_5h_reset"] = current["quota_5h_reset"]
            payload["quota_7d_left"] = current["quota_7d_left"]
            payload["quota_7d_reset"] = current["quota_7d_reset"]
        return payload

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

    def rename_account(self, old_alias: str, new_alias: str) -> dict[str, Any]:
        """Rename one stored account alias."""
        normalized_old = self._normalize_alias(old_alias)
        normalized_new = self._normalize_alias(new_alias)
        if normalized_old == normalized_new:
            raise AccountSelectionError("New alias must be different from the current alias.")
        try:
            self.registry.rename_account(normalized_old, normalized_new)
        except sqlite3.IntegrityError as exc:
            raise AccountExistsError(f"Account '{normalized_new}' already exists.") from exc
        return self._record_payload(self.registry.get_account(normalized_new).record)

    def select_account(
        self,
        alias: str,
        *,
        auto_refresh: bool = False,
    ) -> dict[str, Any]:
        """Write a stored auth snapshot back into Claude's live auth backend."""
        normalized = self._normalize_alias(alias)
        if auto_refresh:
            self.refresh_if_needed(normalized, context="runtime")
        return self._activate_cli_account(normalized, allow_expired=True)

    def refresh_account(
        self,
        alias: str,
        *,
        prompt: str = "ping",
        progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Try to refresh one CLI account via direct OAuth refresh or a Claude probe."""
        def emit(stage: str, **payload: Any) -> None:
            if progress_callback is not None:
                progress_callback(stage, payload)

        normalized = self._normalize_alias(alias)
        details = self.registry.get_account(normalized)
        original_snapshot = self.auth_backend.read_snapshot()
        original_current_alias = self.current_alias()
        should_restore = self._snapshot_changed(original_snapshot, details.snapshot)
        emit(
            "start",
            alias=normalized,
            original_current_alias=original_current_alias,
            will_restore=should_restore,
            prompt=prompt,
        )
        emit("activating_target", alias=normalized)
        account = self._activate_cli_account(normalized, allow_expired=True, mark_selected=False)
        emit("target_activated", alias=account["alias"], status=account["status"])
        try:
            output = ""
            refresh_method = "probe"
            direct_refresh_reason = self._direct_refresh_unavailable_reason(details.snapshot)
            if direct_refresh_reason is None:
                emit("running_direct_refresh", alias=account["alias"])
                try:
                    refreshed_snapshot = self._refresh_snapshot_via_oauth(details.snapshot)
                except ClaudeSelectError as exc:
                    direct_refresh_reason = str(exc)
                    emit(
                        "direct_refresh_failed",
                        alias=account["alias"],
                        reason=direct_refresh_reason,
                    )
                else:
                    self.auth_backend.write_snapshot(refreshed_snapshot)
                    refresh_method = "oauth_token"
                    output = "refreshed via OAuth token endpoint"
                    emit("direct_refresh_succeeded", alias=account["alias"])
            if refresh_method != "oauth_token":
                if direct_refresh_reason is not None:
                    emit(
                        "falling_back_to_probe",
                        alias=account["alias"],
                        reason=direct_refresh_reason,
                    )
                emit("running_probe", alias=account["alias"], prompt=prompt)
                ok, output = self.auth_backend.run_print_prompt(prompt)
                if not ok:
                    emit("probe_failed", alias=account["alias"], prompt=prompt, output=output)
                    raise ConfigError(f"Claude refresh probe failed: {output}")
                emit("probe_succeeded", alias=account["alias"], prompt=prompt, output=output)
            emit("syncing_current", alias=account["alias"])
            sync_payload = self.sync_current_account()
            emit("sync_succeeded", alias=account["alias"], message=sync_payload["message"])
            refreshed = self.registry.get_account(account["alias"]).record
            return {
                "alias": account["alias"],
                "refresh_method": refresh_method,
                "probe_prompt": prompt,
                "probe_output": output,
                "sync": sync_payload,
                "record": self._record_payload(refreshed),
            }
        finally:
            emit(
                "restoring_original",
                alias=account["alias"],
                original_current_alias=original_current_alias,
                will_restore=should_restore,
            )
            if should_restore:
                self.auth_backend.write_snapshot(original_snapshot)
            self.registry.set_current_alias(original_current_alias)
            emit(
                "restore_complete",
                alias=account["alias"],
                original_current_alias=original_current_alias,
                restored=should_restore,
            )

    def refresh_candidates(self) -> list[str]:
        """Return CLI aliases that are already expired."""
        rows = self.list_accounts(include_usage=False)
        return [
            str(row["alias"])
            for row in rows
            if row["auth_kind"] == AUTH_KIND_CLI_SNAPSHOT
            and row["status"] == STATUS_EXPIRED
        ]

    def auto_refresh_candidates(self) -> list[str]:
        """Return CLI aliases that should be auto-refreshed in watch mode."""
        rows = self.list_accounts(include_usage=False)
        return [
            str(row["alias"])
            for row in rows
            if row["auth_kind"] == AUTH_KIND_CLI_SNAPSHOT
            and self._should_refresh_expires_at(row.get("expires_at"), context="background")
        ]

    def _activate_cli_account(
        self,
        alias: str,
        *,
        allow_expired: bool,
        mark_selected: bool = True,
    ) -> dict[str, Any]:
        """Write a stored CLI snapshot back into Claude's live auth backend."""
        details = self.registry.get_account(self._normalize_alias(alias))
        if details.record.auth_kind != AUTH_KIND_CLI_SNAPSHOT:
            raise AccountKindError(
                f"Account '{details.record.alias}' is a token entry and cannot be selected for CLI."
            )
        self.auth_backend.write_snapshot(details.snapshot)
        if mark_selected:
            selected_at = utc_now_iso()
            self.registry.mark_selected(details.record.alias, selected_at)
        refreshed = self.registry.get_account(details.record.alias).record
        return self._record_payload(refreshed)

    def build_sdk_env(
        self,
        alias: str,
        base_env: dict[str, str] | None = None,
        *,
        auto_refresh: bool = False,
        probe_availability: bool = False,
    ) -> dict[str, str]:
        """Return an env mapping for Claude Agent SDK usage.

        Captured auth is treated as a fixed snapshot. With ``auto_refresh=True``,
        CLI snapshots are refreshed on demand before the SDK env is
        built. With ``probe_availability=True``, one minimal Claude request is
        attempted to verify that the prepared env is actually usable.
        """
        details = self.get_account(alias, auto_refresh=auto_refresh)
        env = self._sdk_env_for_details(details, base_env=base_env)
        if probe_availability:
            ok, reason = self._probe_sdk_env_availability(env)
            if not ok:
                raise AccountSelectionError(
                    f"Account '{details.record.alias}' failed runtime probe: {reason}"
                )
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

    def export_sdk_auth(
        self,
        alias: str,
        *,
        auto_refresh: bool = False,
    ) -> dict[str, Any]:
        """Return a structured auth payload for SDK consumers."""
        details = self.get_account(alias, auto_refresh=auto_refresh)
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

    def _sdk_env_for_details(
        self,
        details: AccountDetails,
        *,
        base_env: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Build SDK env from one resolved account details object."""
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

    def current_alias(self) -> str | None:
        """Return the last selected CLI alias if any."""
        return self.registry.get_current_alias()

    def current_live_account(
        self,
        *,
        include_usage: bool = True,
        usage_mode: str = "foreground",
        usage_stale_after_seconds: int | None = None,
    ) -> dict[str, Any]:
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
        usage = None
        if include_usage:
            usage = self._usage_for_snapshot(
                snapshot,
                payload["matched_alias"] or self._usage_cache_key_for_snapshot(snapshot),
                usage_mode=usage_mode,
                usage_stale_after_seconds=usage_stale_after_seconds,
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

    def get_account_quota(
        self,
        alias: str,
        *,
        auto_refresh: bool = False,
        usage_mode: str = "foreground",
        usage_stale_after_seconds: int | None = None,
    ) -> dict[str, Any]:
        """Return quota details for one stored account alias."""
        details = self.get_account(alias, auto_refresh=auto_refresh)
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
        usage = self._usage_for_alias(
            details.record.alias,
            usage_mode=usage_mode,
            usage_stale_after_seconds=usage_stale_after_seconds,
        )
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

    def list_account_quotas(self, *, auto_refresh: bool = False) -> list[dict[str, Any]]:
        """Return quota details for every stored account alias."""
        aliases = [record.alias for record in self.registry.list_accounts()]
        if auto_refresh:
            self._best_effort_auto_refresh_candidates()
        return [self.get_account_quota(alias, auto_refresh=False) for alias in aliases]

    def list_available_accounts(
        self,
        *,
        include_usage: bool = True,
        auto_refresh: bool = False,
        require_quota: bool = True,
        probe_availability: bool = False,
    ) -> list[dict[str, Any]]:
        """Return accounts that are currently usable, optionally requiring quota visibility."""
        include_usage = include_usage or require_quota
        rows = self.list_accounts(
            include_usage=include_usage,
            auto_refresh=False,
        )
        available: list[dict[str, Any]] = []
        for row in rows:
            if auto_refresh and row["auth_kind"] == AUTH_KIND_CLI_SNAPSHOT:
                try:
                    self.refresh_if_needed(str(row["alias"]), context="runtime")
                except ClaudeSelectError:
                    continue
                row = self._account_row(str(row["alias"]), include_usage=include_usage)
            if row["status"] == STATUS_EXPIRED:
                continue
            if require_quota:
                if row["auth_kind"] != AUTH_KIND_CLI_SNAPSHOT:
                    continue
                if not self._row_has_remaining_quota(row):
                    continue
            available.append(row)
        if probe_availability:
            return self._filter_probeable_available_rows(
                available,
                auto_refresh=auto_refresh,
            )
        return available

    def pick_available_account(
        self,
        *,
        include_usage: bool = True,
        auto_refresh: bool = False,
        require_quota: bool = True,
        prefer_current: bool = True,
        probe_availability: bool = False,
    ) -> dict[str, Any]:
        """Pick one currently available account using a simple deterministic strategy."""
        available = self.list_available_accounts(
            include_usage=include_usage,
            auto_refresh=auto_refresh,
            require_quota=require_quota,
            probe_availability=False,
        )
        if not available:
            raise AccountSelectionError("No available accounts matched the requested criteria.")
        ordered = self._ordered_available_rows(
            available,
            require_quota=require_quota,
            prefer_current=prefer_current,
        )
        if not probe_availability:
            return ordered[0]
        failures: list[str] = []
        for row in ordered:
            ok, reason = self._probe_sdk_alias_availability(
                str(row["alias"]),
                auto_refresh=auto_refresh,
            )
            if ok:
                return row
            failures.append(f"{row['alias']}: {reason}")
        raise AccountSelectionError(
            "No available accounts passed runtime probe. Tried: "
            + "; ".join(failures)
        )

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
        snapshot = self._snapshot_with_persisted_client_id(alias, snapshot)
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
        snapshot = self._snapshot_with_persisted_client_id(alias, snapshot)
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

    def _snapshot_with_persisted_client_id(
        self,
        alias: str,
        snapshot: AuthSnapshot,
    ) -> AuthSnapshot:
        """Attach a persisted client_id when the captured snapshot itself does not include one."""
        client_id = snapshot.client_id()
        if client_id:
            return snapshot
        pending_client_id = self.auth_backend.consume_auth_login_client_id()
        if pending_client_id:
            return self._snapshot_with_client_id(snapshot, pending_client_id)
        try:
            existing = self.registry.get_account(alias).snapshot.client_id()
        except AccountNotFoundError:
            existing = None
        if existing:
            return self._snapshot_with_client_id(snapshot, existing)
        return snapshot

    @staticmethod
    def _snapshot_with_client_id(snapshot: AuthSnapshot, client_id: str) -> AuthSnapshot:
        """Return a snapshot whose Claude OAuth payload also carries client_id."""
        normalized = client_id.strip()
        if not normalized:
            return snapshot
        credentials = json.loads(json.dumps(snapshot.credentials))
        oauth = credentials.setdefault("claudeAiOauth", {})
        if isinstance(oauth, dict):
            oauth["clientId"] = normalized
        return AuthSnapshot(
            oauth_account=json.loads(json.dumps(snapshot.oauth_account)),
            credentials=credentials,
        )

    @staticmethod
    def _direct_refresh_unavailable_reason(snapshot: AuthSnapshot) -> str | None:
        """Return why direct OAuth refresh cannot be attempted, or None when it can."""
        oauth = snapshot.credentials.get("claudeAiOauth", {})
        if not isinstance(oauth, dict):
            return "missing Claude OAuth payload"
        refresh_token = oauth.get("refreshToken", "")
        if not isinstance(refresh_token, str) or not refresh_token.strip():
            return "missing refresh token"
        if snapshot.client_id() is None:
            return "client_id was not captured for this snapshot"
        return None

    def _refresh_snapshot_via_oauth(self, snapshot: AuthSnapshot) -> AuthSnapshot:
        """Refresh one stored OAuth snapshot directly via Claude's token endpoint."""
        oauth = snapshot.credentials.get("claudeAiOauth", {})
        if not isinstance(oauth, dict):
            raise ConfigError("Claude OAuth credentials are missing.")
        refresh_token = str(oauth.get("refreshToken", "") or "").strip()
        client_id = snapshot.client_id()
        if not refresh_token or not client_id:
            raise ConfigError("Direct OAuth refresh requires both refresh_token and client_id.")
        request = urllib.request.Request(
            self.OAUTH_TOKEN_REFRESH_URL,
            data=json.dumps(
                {
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                }
            ).encode("utf-8"),
            headers={
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
                "User-Agent": "axios/1.13.6",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise ConfigError(self._extract_http_error_reason(exc)) from exc
        except (
            urllib.error.URLError,
            json.JSONDecodeError,
            http.client.HTTPException,
            OSError,
        ) as exc:
            raise ConfigError(f"OAuth token refresh failed: {exc}") from exc

        access_token = str(payload.get("access_token", "") or "").strip()
        if not access_token:
            raise ConfigError("OAuth token refresh did not return an access_token.")
        expires_in_raw = payload.get("expires_in")
        if not isinstance(expires_in_raw, int):
            try:
                expires_in = int(expires_in_raw)
            except (TypeError, ValueError) as exc:
                raise ConfigError("OAuth token refresh returned an invalid expires_in.") from exc
        else:
            expires_in = expires_in_raw
        refreshed_credentials = json.loads(json.dumps(snapshot.credentials))
        refreshed_oauth = refreshed_credentials.setdefault("claudeAiOauth", {})
        if not isinstance(refreshed_oauth, dict):
            raise ConfigError("Claude OAuth credentials are missing.")
        refreshed_oauth["accessToken"] = access_token
        refreshed_oauth["clientId"] = client_id
        refreshed_oauth["expiresAt"] = int((utc_now().timestamp() + expires_in) * 1000)
        refreshed_token = str(payload.get("refresh_token", "") or "").strip()
        if refreshed_token:
            refreshed_oauth["refreshToken"] = refreshed_token
        scopes = payload.get("scope")
        if isinstance(scopes, str) and scopes.strip():
            refreshed_oauth["scopes"] = scopes.split()
        return AuthSnapshot(
            oauth_account=json.loads(json.dumps(snapshot.oauth_account)),
            credentials=refreshed_credentials,
        )

    def _usage_for_alias(
        self,
        alias: str,
        *,
        usage_mode: str = "foreground",
        usage_stale_after_seconds: int | None = None,
    ) -> dict[str, Any] | None:
        details = self.registry.get_account(alias)
        return self._usage_for_snapshot(
            details.snapshot,
            f"alias:{alias}",
            usage_mode=usage_mode,
            usage_stale_after_seconds=usage_stale_after_seconds,
        )

    def refresh_if_needed(
        self,
        alias: str,
        *,
        context: str = "runtime",
    ) -> AccountDetails:
        """Refresh one CLI alias when it falls inside the chosen refresh window."""
        normalized = self._normalize_alias(alias)
        details = self.registry.get_account(normalized)
        if details.record.auth_kind != AUTH_KIND_CLI_SNAPSHOT:
            return details
        if details.sdk_token_snapshot is not None:
            return details
        if not self._should_refresh_record(details.record, context=context):
            return details
        self.refresh_account(normalized)
        return self.registry.get_account(normalized)

    def _maybe_auto_refresh_alias(self, alias: str) -> AccountDetails:
        """Backward-compatible wrapper for runtime auto-refresh."""
        return self.refresh_if_needed(alias, context="runtime")

    def _probe_sdk_alias_availability(
        self,
        alias: str,
        *,
        auto_refresh: bool = False,
        base_env: dict[str, str] | None = None,
    ) -> tuple[bool, str]:
        """Probe whether one alias can satisfy a minimal Claude SDK-style request."""
        details = self.get_account(alias, auto_refresh=auto_refresh)
        env = self._sdk_env_for_details(details, base_env=base_env)
        return self._probe_sdk_env_availability(env)

    def _probe_sdk_env_availability(
        self,
        env: dict[str, str],
        *,
        prompt: str = "ping",
    ) -> tuple[bool, str]:
        """Probe one prepared SDK env via a minimal Claude CLI request."""
        claude_path = shutil.which("claude")
        if not claude_path:
            return False, "`claude` was not found in PATH."
        result = subprocess.run(
            [claude_path, "-p", prompt],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        output = (result.stdout or "").strip() or (result.stderr or "").strip()
        return result.returncode == 0, output or f"Claude exited with code {result.returncode}"

    def _filter_probeable_available_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        auto_refresh: bool,
    ) -> list[dict[str, Any]]:
        """Return only rows that pass a runtime availability probe."""
        available: list[dict[str, Any]] = []
        for row in rows:
            ok, _reason = self._probe_sdk_alias_availability(
                str(row["alias"]),
                auto_refresh=auto_refresh,
            )
            if ok:
                available.append(row)
        return available

    def _best_effort_auto_refresh_candidates(self) -> None:
        """Best-effort refresh for list-style APIs that opt into auto-refresh."""
        for alias in self.auto_refresh_candidates():
            try:
                self.refresh_if_needed(alias, context="background")
            except ClaudeSelectError:
                continue

    @staticmethod
    def _seconds_until_expiry(expires_at: int | None, *, now: Any | None = None) -> int | None:
        if expires_at is None:
            return None
        current = now or utc_now()
        return int(expires_at / 1000 - current.timestamp())

    def _is_within_refresh_probe_window(self, record: AccountRecord) -> bool:
        return self._should_refresh_record(record, context="runtime")

    def _is_expires_at_within_refresh_probe_window(
        self,
        expires_at: int | None,
        *,
        now: Any | None = None,
    ) -> bool:
        return self._should_refresh_expires_at(expires_at, context="runtime", now=now)

    def _should_refresh_record(
        self,
        record: AccountRecord,
        *,
        context: str,
        now: Any | None = None,
    ) -> bool:
        return self._should_refresh_expires_at(record.expires_at, context=context, now=now)

    def _should_refresh_expires_at(
        self,
        expires_at: int | None,
        *,
        context: str,
        now: Any | None = None,
    ) -> bool:
        remaining = self._seconds_until_expiry(expires_at, now=now)
        if remaining is None:
            return False
        if remaining <= 0:
            return True
        return remaining <= self._refresh_window_seconds(context)

    def _refresh_window_seconds(self, context: str) -> int:
        normalized = context.strip().lower()
        if normalized == "runtime":
            return self.RUNTIME_REFRESH_WINDOW_SECONDS
        if normalized == "background":
            return self.BACKGROUND_REFRESH_WINDOW_SECONDS
        raise AccountSelectionError(f"Unknown refresh context: {context}")

    def _account_row(
        self,
        alias: str,
        *,
        include_usage: bool,
    ) -> dict[str, Any]:
        details = self.registry.get_account(alias)
        payload = self._record_payload(details.record)
        if include_usage:
            quota = self.get_account_quota(alias, auto_refresh=False)
            payload.update(
                {
                    "usage": quota["usage"],
                    "available": quota["available"],
                    "stale": quota["stale"],
                    "error": quota["error"],
                    "fetched_at": quota["fetched_at"],
                    "five_hour": quota["five_hour"],
                    "seven_day": quota["seven_day"],
                    "seven_day_opus": quota["seven_day_opus"],
                    "extra_usage": quota["extra_usage"],
                    "quota_5h_left": quota["quota_5h_left"],
                    "quota_5h_reset": quota["quota_5h_reset"],
                    "quota_7d_left": quota["quota_7d_left"],
                    "quota_7d_reset": quota["quota_7d_reset"],
                }
            )
        return payload

    @staticmethod
    def _row_has_remaining_quota(row: dict[str, Any]) -> bool:
        """Return whether a rendered row still has usable quota data."""
        usage = row.get("usage")
        if not isinstance(usage, dict) or usage.get("stale"):
            return False
        five_hour_remaining = remaining_percentage(usage.get("five_hour"))
        seven_day_remaining = remaining_percentage(usage.get("seven_day"))
        if five_hour_remaining is None or seven_day_remaining is None:
            return False
        return five_hour_remaining > 0.0 and seven_day_remaining > 0.0

    @staticmethod
    def _available_account_sort_key(row: dict[str, Any]) -> tuple[float, float, str]:
        """Sort available accounts by remaining quota, then alias."""
        usage = row.get("usage")
        if not isinstance(usage, dict):
            return (0.0, 0.0, str(row["alias"]))
        five_hour_remaining = remaining_percentage(usage.get("five_hour")) or 0.0
        seven_day_remaining = remaining_percentage(usage.get("seven_day")) or 0.0
        return (five_hour_remaining, seven_day_remaining, str(row["alias"]))

    def _ordered_available_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        require_quota: bool,
        prefer_current: bool,
    ) -> list[dict[str, Any]]:
        """Order candidate rows using the same preference rules as account picking."""
        ordered = list(rows)
        if require_quota:
            ordered = sorted(
                ordered,
                key=self._available_account_sort_key,
                reverse=True,
            )
        else:
            ordered = sorted(ordered, key=lambda row: str(row["alias"]))
        if not prefer_current:
            return ordered
        current_alias = self.current_alias()
        if not current_alias:
            return ordered
        for index, row in enumerate(ordered):
            if row["alias"] == current_alias:
                if index == 0:
                    return ordered
                return [row] + ordered[:index] + ordered[index + 1 :]
        return ordered

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

    def _usage_for_snapshot(
        self,
        snapshot: AuthSnapshot,
        cache_key: str,
        *,
        usage_mode: str = "foreground",
        usage_stale_after_seconds: int | None = None,
    ) -> dict[str, Any] | None:
        resolved_key = cache_key if cache_key.startswith("alias:") else f"live:{cache_key}"
        try:
            if usage_mode == "cache_only":
                get_cached = getattr(self.usage_provider, "get_cached_usage", None)
                if callable(get_cached):
                    return get_cached(
                        resolved_key,
                        stale_after_seconds=usage_stale_after_seconds,
                    )
                return None
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
                "usage": None,
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
            "usage": usage,
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


def build_sdk_env(
    alias: str,
    base_env: dict[str, str] | None = None,
    *,
    auto_refresh: bool = False,
    probe_availability: bool = False,
) -> dict[str, str]:
    """Convenience wrapper around AuthManager.build_sdk_env."""
    return AuthManager().build_sdk_env(
        alias,
        base_env=base_env,
        auto_refresh=auto_refresh,
        probe_availability=probe_availability,
    )


def build_sdk_env_auto(
    preferred_alias: str | None = None,
    base_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Convenience wrapper around AuthManager.build_sdk_env_auto."""
    return AuthManager().build_sdk_env_auto(preferred_alias=preferred_alias, base_env=base_env)
