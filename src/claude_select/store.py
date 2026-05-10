"""SQLite-backed auth registry."""

from __future__ import annotations

import json
import os
import sqlite3
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
                        email TEXT NOT NULL,
                        organization_name TEXT NOT NULL DEFAULT '',
                        organization_id TEXT NOT NULL DEFAULT '',
                        account_uuid TEXT NOT NULL DEFAULT '',
                        captured_at TEXT NOT NULL,
                        expires_at INTEGER,
                        last_selected_at TEXT,
                        source TEXT NOT NULL,
                        oauth_account_json TEXT NOT NULL,
                        credentials_json TEXT NOT NULL
                    )
                    """
            )
            connection.execute(
                """
                    CREATE TABLE IF NOT EXISTS meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
            )

    def upsert_account(
        self,
        *,
        alias: str,
        email: str,
        organization_name: str,
        organization_id: str,
        account_uuid: str,
        captured_at: str,
        expires_at: int | None,
        last_selected_at: str | None,
        source: str,
        snapshot: AuthSnapshot,
    ) -> None:
        """Create or update an account snapshot."""
        self.initialize()
        with self.lock(), self._connect() as connection:
            connection.execute(
                """
                    INSERT INTO accounts (
                        alias, email, organization_name, organization_id,
                        account_uuid, captured_at, expires_at, last_selected_at,
                        source, oauth_account_json, credentials_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(alias) DO UPDATE SET
                        email=excluded.email,
                        organization_name=excluded.organization_name,
                        organization_id=excluded.organization_id,
                        account_uuid=excluded.account_uuid,
                        captured_at=excluded.captured_at,
                        expires_at=excluded.expires_at,
                        last_selected_at=excluded.last_selected_at,
                        source=excluded.source,
                        oauth_account_json=excluded.oauth_account_json,
                        credentials_json=excluded.credentials_json
                    """,
                (
                    alias,
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
                ),
            )

    def list_accounts(self) -> list[AccountRecord]:
        """Return all registered accounts sorted by alias."""
        self.initialize()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT alias, email, organization_name, organization_id, account_uuid,
                       captured_at, expires_at, last_selected_at, source
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
                       captured_at, expires_at, last_selected_at, source,
                       oauth_account_json, credentials_json
                FROM accounts
                WHERE alias = ?
                """,
                (alias,),
            )
            row = cursor.fetchone()
        if row is None:
            raise AccountNotFoundError(f"Account '{alias}' was not found.")
        record = self._row_to_record(row[:9])
        snapshot = AuthSnapshot(
            oauth_account=json.loads(row[9]),
            credentials=json.loads(row[10]),
        )
        return AccountDetails(record=record, snapshot=snapshot)

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
            email=str(row[1]),
            organization_name=str(row[2]),
            organization_id=str(row[3]),
            account_uuid=str(row[4]),
            captured_at=str(row[5]),
            expires_at=row[6] if isinstance(row[6], int) else None,
            last_selected_at=str(row[7]) if row[7] is not None else None,
            source=str(row[8]),
        )

