"""SQLite-backed auth registry."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

from claude_select.exceptions import AccountNotFoundError
from claude_select.locking import FileLock
from claude_select.models import AccountDetails, AccountRecord, AuthSnapshot
from claude_select.paths import get_registry_db_path


class AuthRegistry:
    """SQLite-backed registry for Claude auth snapshots."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or get_registry_db_path()
        self.lock_path = self.db_path.with_suffix(".lock")

    def lock(self) -> FileLock:
        """Return the registry lock."""
        self._ensure_parent()
        return FileLock(self.lock_path)

    def initialize(self) -> None:
        """Create the schema if it does not exist."""
        self._ensure_parent()
        with self.lock(), self._connect() as connection:
            connection.execute(
                """
                    CREATE TABLE IF NOT EXISTS accounts (
                        alias TEXT PRIMARY KEY,
                        auth_kind TEXT NOT NULL DEFAULT 'cli_snapshot',
                        email TEXT NOT NULL,
                        organization_name TEXT NOT NULL DEFAULT '',
                        organization_id TEXT NOT NULL DEFAULT '',
                        account_uuid TEXT NOT NULL DEFAULT '',
                        captured_at TEXT NOT NULL,
                        expires_at INTEGER,
                        last_selected_at TEXT,
                        source TEXT NOT NULL,
                        oauth_account_json TEXT NOT NULL,
                        credentials_json TEXT NOT NULL,
                        last_synced_at TEXT,
                        sdk_token_captured_at TEXT,
                        sdk_token_expires_at INTEGER,
                        sdk_token_oauth_account_json TEXT,
                        sdk_token_credentials_json TEXT
                    )
                    """
            )
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(accounts)").fetchall()
            }
            if "auth_kind" not in columns:
                connection.execute(
                    "ALTER TABLE accounts ADD COLUMN auth_kind TEXT NOT NULL DEFAULT 'cli_snapshot'"
                )
            if "last_synced_at" not in columns:
                connection.execute("ALTER TABLE accounts ADD COLUMN last_synced_at TEXT")
            if "sdk_token_captured_at" not in columns:
                connection.execute("ALTER TABLE accounts ADD COLUMN sdk_token_captured_at TEXT")
            if "sdk_token_expires_at" not in columns:
                connection.execute("ALTER TABLE accounts ADD COLUMN sdk_token_expires_at INTEGER")
            if "sdk_token_oauth_account_json" not in columns:
                connection.execute(
                    "ALTER TABLE accounts ADD COLUMN sdk_token_oauth_account_json TEXT"
                )
            if "sdk_token_credentials_json" not in columns:
                connection.execute(
                    "ALTER TABLE accounts ADD COLUMN sdk_token_credentials_json TEXT"
                )
            connection.execute(
                """
                    CREATE TABLE IF NOT EXISTS meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
            )
            connection.execute(
                """
                    CREATE TABLE IF NOT EXISTS usage_cache (
                        cache_key TEXT PRIMARY KEY,
                        payload_json TEXT NOT NULL,
                        fetched_at INTEGER NOT NULL
                    )
                    """
            )

    def upsert_account(
        self,
        *,
        alias: str,
        auth_kind: str,
        email: str,
        organization_name: str,
        organization_id: str,
        account_uuid: str,
        captured_at: str,
        expires_at: int | None,
        last_selected_at: str | None,
        source: str,
        snapshot: AuthSnapshot,
        last_synced_at: str | None = None,
    ) -> None:
        """Create or update an account snapshot."""
        self.initialize()
        with self.lock(), self._connect() as connection:
            connection.execute(
                """
                    INSERT INTO accounts (
                        alias, auth_kind, email, organization_name, organization_id,
                        account_uuid, captured_at, expires_at, last_selected_at,
                        source, oauth_account_json, credentials_json, last_synced_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(alias) DO UPDATE SET
                        auth_kind=excluded.auth_kind,
                        email=excluded.email,
                        organization_name=excluded.organization_name,
                        organization_id=excluded.organization_id,
                        account_uuid=excluded.account_uuid,
                        captured_at=excluded.captured_at,
                        expires_at=excluded.expires_at,
                        last_selected_at=excluded.last_selected_at,
                        source=excluded.source,
                        oauth_account_json=excluded.oauth_account_json,
                        credentials_json=excluded.credentials_json,
                        last_synced_at=excluded.last_synced_at
                    """,
                (
                    alias,
                    auth_kind,
                    email,
                    organization_name,
                    organization_id,
                    account_uuid,
                    captured_at,
                    expires_at,
                    last_selected_at,
                    source,
                    json.dumps(snapshot.oauth_account, sort_keys=True),
                    json.dumps(snapshot.credentials, sort_keys=True),
                    last_synced_at,
                ),
            )

    def attach_sdk_token(
        self,
        *,
        alias: str,
        captured_at: str,
        expires_at: int | None,
        snapshot: AuthSnapshot,
    ) -> None:
        """Attach or replace one SDK token for an existing alias."""
        self.initialize()
        with self.lock(), self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE accounts
                SET sdk_token_captured_at = ?,
                    sdk_token_expires_at = ?,
                    sdk_token_oauth_account_json = ?,
                    sdk_token_credentials_json = ?,
                    last_synced_at = ?
                WHERE alias = ?
                """,
                (
                    captured_at,
                    expires_at,
                    json.dumps(snapshot.oauth_account, sort_keys=True),
                    json.dumps(snapshot.credentials, sort_keys=True),
                    captured_at,
                    alias,
                ),
            )
            if cursor.rowcount == 0:
                raise AccountNotFoundError(f"Account '{alias}' was not found.")

    def list_accounts(self) -> list[AccountRecord]:
        """Return all registered accounts sorted by alias."""
        self.initialize()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT alias, email, organization_name, organization_id, account_uuid,
                       captured_at, expires_at, last_selected_at, source, last_synced_at,
                       auth_kind, sdk_token_credentials_json
                FROM accounts
                ORDER BY alias
                """
            )
            return [self._row_to_record(row) for row in cursor.fetchall()]

    def get_account(self, alias: str) -> AccountDetails:
        """Return one account and its snapshot."""
        self.initialize()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT alias, email, organization_name, organization_id, account_uuid,
                       captured_at, expires_at, last_selected_at, source, last_synced_at,
                       auth_kind, sdk_token_credentials_json,
                       oauth_account_json, credentials_json,
                       sdk_token_oauth_account_json
                FROM accounts
                WHERE alias = ?
                """,
                (alias,),
            )
            row = cursor.fetchone()
        if row is None:
            raise AccountNotFoundError(f"Account '{alias}' was not found.")
        record = self._row_to_record(row[:12])
        snapshot = AuthSnapshot(
            oauth_account=json.loads(row[12]),
            credentials=json.loads(row[13]),
        )
        sdk_token_snapshot = None
        if row[11] and row[14]:
            sdk_token_snapshot = AuthSnapshot(
                oauth_account=json.loads(row[14]),
                credentials=json.loads(row[11]),
            )
        return AccountDetails(
            record=record,
            snapshot=snapshot,
            sdk_token_snapshot=sdk_token_snapshot,
        )

    def remove_account(self, alias: str) -> None:
        """Delete an account from the registry."""
        self.initialize()
        with self.lock(), self._connect() as connection:
            cursor = connection.execute("DELETE FROM accounts WHERE alias = ?", (alias,))
            if cursor.rowcount == 0:
                raise AccountNotFoundError(f"Account '{alias}' was not found.")
            connection.execute(
                "DELETE FROM meta WHERE key = 'current_alias' AND value = ?",
                (alias,),
            )
            connection.execute("DELETE FROM usage_cache WHERE cache_key = ?", (f"alias:{alias}",))

    def rename_account(self, old_alias: str, new_alias: str) -> None:
        """Rename one account alias and update related registry metadata."""
        self.initialize()
        with self.lock(), self._connect() as connection:
            existing = connection.execute(
                "SELECT 1 FROM accounts WHERE alias = ?",
                (old_alias,),
            ).fetchone()
            if existing is None:
                raise AccountNotFoundError(f"Account '{old_alias}' was not found.")
            conflict = connection.execute(
                "SELECT 1 FROM accounts WHERE alias = ?",
                (new_alias,),
            ).fetchone()
            if conflict is not None:
                raise sqlite3.IntegrityError(f"Account '{new_alias}' already exists.")
            connection.execute(
                "UPDATE accounts SET alias = ? WHERE alias = ?",
                (new_alias, old_alias),
            )
            connection.execute(
                """
                UPDATE meta
                SET value = ?
                WHERE key = 'current_alias' AND value = ?
                """,
                (new_alias, old_alias),
            )
            connection.execute(
                """
                UPDATE usage_cache
                SET cache_key = ?
                WHERE cache_key = ?
                """,
                (f"alias:{new_alias}", f"alias:{old_alias}"),
            )

    def mark_selected(self, alias: str, selected_at: str) -> None:
        """Persist selection timestamp and current alias metadata."""
        self.initialize()
        with self.lock(), self._connect() as connection:
            cursor = connection.execute(
                "UPDATE accounts SET last_selected_at = ? WHERE alias = ?",
                (selected_at, alias),
            )
            if cursor.rowcount == 0:
                raise AccountNotFoundError(f"Account '{alias}' was not found.")
            connection.execute(
                """
                    INSERT INTO meta (key, value) VALUES ('current_alias', ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                (alias,),
            )

    def get_current_alias(self) -> str | None:
        """Return the last CLI-selected alias if known."""
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM meta WHERE key = 'current_alias'"
            ).fetchone()
        return str(row[0]) if row else None

    def set_current_alias(self, alias: str | None) -> None:
        """Set or clear the current CLI alias metadata without touching timestamps."""
        self.initialize()
        with self.lock(), self._connect() as connection:
            if alias is None:
                connection.execute("DELETE FROM meta WHERE key = 'current_alias'")
                return
            connection.execute(
                """
                    INSERT INTO meta (key, value) VALUES ('current_alias', ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                (alias,),
            )

    def set_usage_cache(self, cache_key: str, payload: dict[str, object], fetched_at: int) -> None:
        """Upsert one cached usage payload."""
        self.initialize()
        with self.lock(), self._connect() as connection:
            connection.execute(
                """
                INSERT INTO usage_cache (cache_key, payload_json, fetched_at)
                VALUES (?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    fetched_at = excluded.fetched_at
                """,
                (cache_key, json.dumps(payload, sort_keys=True), fetched_at),
            )

    def get_usage_cache(
        self,
        cache_key: str,
        *,
        max_age_seconds: int | None,
        now_epoch: int | None = None,
    ) -> dict[str, object] | None:
        """Return one cached usage payload if present and fresh enough."""
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json, fetched_at
                FROM usage_cache
                WHERE cache_key = ?
                """,
                (cache_key,),
            ).fetchone()
        if row is None:
            return None
        fetched_at = int(row[1])
        if max_age_seconds is not None:
            current = now_epoch if now_epoch is not None else int(time.time())
            if current - fetched_at > max_age_seconds:
                return None
        return json.loads(str(row[0]))

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _ensure_parent(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(self.db_path.parent, 0o700)

    @staticmethod
    def _row_to_record(row: tuple[object, ...]) -> AccountRecord:
        return AccountRecord(
            alias=str(row[0]),
            auth_kind=str(row[10] if row[10] is not None else "cli_snapshot"),
            email=str(row[1]),
            organization_name=str(row[2]),
            organization_id=str(row[3]),
            account_uuid=str(row[4]),
            captured_at=str(row[5]),
            expires_at=row[6] if isinstance(row[6], int) else None,
            last_selected_at=str(row[7]) if row[7] is not None else None,
            source=str(row[8]),
            last_synced_at=str(row[9]) if row[9] is not None else None,
            has_sdk_token=row[11] is not None,
        )
