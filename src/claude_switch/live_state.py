"""Claude live state backends."""

from __future__ import annotations

import getpass
import json
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Protocol

from claude_switch.exceptions import ConfigError
from claude_switch.models import LiveState
from claude_switch.paths import get_credentials_path, get_global_config_path


class CredentialStore(Protocol):
    """Read and write Claude credentials."""

    def read(self) -> dict[str, Any]:
        """Read the current credentials payload."""

    def write(self, credentials: dict[str, Any]) -> None:
        """Write the current credentials payload."""

    def backup(self, destination_dir: Path) -> None:
        """Back up the credential store if supported."""


class FileCredentialStore:
    """File-backed Claude credential storage."""

    def __init__(self, path: Path):
        self.path = path

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            raise ConfigError(f"Claude credentials file not found: {self.path}")
        with self.path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def write(self, credentials: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.path.parent,
            delete=False,
        ) as handle:
            json.dump(credentials, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temp_name = handle.name
        os.replace(temp_name, self.path)
        if os.name != "nt":
            os.chmod(self.path, 0o600)

    def backup(self, destination_dir: Path) -> None:
        if not self.path.exists():
            return
        destination_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.path, destination_dir / self.path.name)


class MacOSKeychainCredentialStore:
    """macOS keychain-backed Claude credential storage."""

    def __init__(
        self,
        service_name: str = "Claude Code-credentials",
        account_name: str | None = None,
    ):
        self.service_name = service_name
        self.account_name = account_name or getpass.getuser()

    def read(self) -> dict[str, Any]:
        try:
            result = subprocess.run(
                ["security", "find-generic-password", "-s", self.service_name, "-w"],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            raise ConfigError("Claude credentials not found in macOS Keychain.") from exc
        return json.loads(result.stdout)

    def write(self, credentials: dict[str, Any]) -> None:
        result = subprocess.run(
            [
                "security",
                "add-generic-password",
                "-U",
                "-s",
                self.service_name,
                "-a",
                self.account_name,
                "-w",
                json.dumps(credentials, separators=(",", ":")),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise ConfigError(
                f"Failed to write macOS Keychain credentials: {result.stderr.strip()}"
            )

    def backup(self, destination_dir: Path) -> None:
        destination_dir.mkdir(parents=True, exist_ok=True)
        backup_file = destination_dir / "keychain-credentials.json"
        backup_file.write_text(
            json.dumps(self.read(), indent=2, sort_keys=True),
            encoding="utf-8",
        )


def create_default_credential_store(env: dict[str, str] | None = None) -> CredentialStore:
    """Create the default credential store for the current platform."""
    if platform.system() == "Darwin":
        return MacOSKeychainCredentialStore()
    return FileCredentialStore(get_credentials_path(env))


class ClaudeLiveStateBackend:
    """Reads and writes Claude's live runtime auth state."""

    def __init__(
        self,
        config_path: Path | None = None,
        credential_store: CredentialStore | None = None,
        backup_dir: Path | None = None,
        env: dict[str, str] | None = None,
    ):
        self.config_path = config_path or get_global_config_path(env)
        self.credential_store = credential_store or create_default_credential_store(env)
        self.backup_dir = backup_dir or (self.config_path.parent / ".claude-switch-backups")

    def read(self) -> LiveState:
        """Read Claude's current live config and credentials."""
        if not self.config_path.exists():
            raise ConfigError(f"Claude config file not found: {self.config_path}")
        with self.config_path.open("r", encoding="utf-8") as handle:
            config = json.load(handle)
        credentials = self.credential_store.read()
        oauth_account = config.get("oauthAccount")
        if not isinstance(oauth_account, dict) or not oauth_account.get("emailAddress"):
            raise ConfigError("Claude config does not contain a valid oauthAccount.")
        if not isinstance(credentials.get("claudeAiOauth"), dict):
            raise ConfigError("Claude credentials do not contain a valid claudeAiOauth payload.")
        return LiveState(config=config, credentials=credentials)

    def write(self, live_state: LiveState) -> None:
        """Write Claude's current live config and credentials."""
        self.backup()
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.config_path.parent,
            delete=False,
        ) as handle:
            json.dump(live_state.config, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temp_name = handle.name
        os.replace(temp_name, self.config_path)
        self.credential_store.write(live_state.credentials)

    def backup(self) -> None:
        """Create backups for the live config and credentials."""
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        if self.config_path.exists():
            shutil.copy2(self.config_path, self.backup_dir / self.config_path.name)
        self.credential_store.backup(self.backup_dir)
