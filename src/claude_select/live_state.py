"""Read and write Claude's live auth state."""

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

from claude_select.exceptions import ConfigError
from claude_select.models import AuthSnapshot
from claude_select.paths import get_credentials_path, get_global_config_path


class CredentialStore(Protocol):
    """Protocol for Claude credential backends."""

    def read(self) -> dict[str, Any]:
        """Return current credentials payload."""

    def write(self, credentials: dict[str, Any]) -> None:
        """Write credentials payload."""

    def backup(self, destination_dir: Path) -> None:
        """Persist a backup copy if supported."""


class FileCredentialStore:
    """File-backed Claude credentials."""

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
        if self.path.exists():
            destination_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.path, destination_dir / self.path.name)


class MacOSKeychainCredentialStore:
    """macOS keychain-backed Claude credentials."""

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
        (destination_dir / "keychain-credentials.json").write_text(
            json.dumps(self.read(), indent=2, sort_keys=True),
            encoding="utf-8",
        )


def create_default_credential_store(
    env: dict[str, str] | None = None,
) -> CredentialStore:
    """Create the default store for the current platform."""
    if platform.system() == "Darwin":
        return MacOSKeychainCredentialStore()
    return FileCredentialStore(get_credentials_path(env))


class ClaudeAuthBackend:
    """Read and write Claude's current active auth snapshot."""

    def __init__(
        self,
        config_path: Path | None = None,
        credential_store: CredentialStore | None = None,
        backup_dir: Path | None = None,
        env: dict[str, str] | None = None,
    ):
        self.config_path = config_path or get_global_config_path(env)
        self.credential_store = credential_store or create_default_credential_store(env)
        self.backup_dir = backup_dir or (self.config_path.parent / ".claude-select-backups")

    def read_snapshot(self) -> AuthSnapshot:
        """Read the current Claude live auth snapshot."""
        if not self.config_path.exists():
            raise ConfigError(f"Claude config file not found: {self.config_path}")
        with self.config_path.open("r", encoding="utf-8") as handle:
            config = json.load(handle)
        oauth_account = config.get("oauthAccount")
        if not isinstance(oauth_account, dict) or not oauth_account.get("emailAddress"):
            raise ConfigError("Claude config does not contain a valid oauthAccount.")
        credentials = self.credential_store.read()
        if not isinstance(credentials.get("claudeAiOauth"), dict):
            raise ConfigError("Claude credentials do not contain a valid claudeAiOauth payload.")
        return AuthSnapshot(oauth_account=oauth_account, credentials=credentials)

    def write_snapshot(self, snapshot: AuthSnapshot) -> None:
        """Write a selected auth snapshot back into Claude's live state."""
        self._backup_live_state()
        config: dict[str, Any]
        if self.config_path.exists():
            with self.config_path.open("r", encoding="utf-8") as handle:
                config = json.load(handle)
        else:
            config = {}
        config["oauthAccount"] = snapshot.oauth_account
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.config_path.parent,
            delete=False,
        ) as handle:
            json.dump(config, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temp_name = handle.name
        os.replace(temp_name, self.config_path)
        self.credential_store.write(snapshot.credentials)

    def describe_targets(self) -> list[str]:
        """Describe which Claude live-state targets will be updated."""
        targets = [f"config: {self.config_path}"]
        if isinstance(self.credential_store, FileCredentialStore):
            targets.append(f"credentials file: {self.credential_store.path}")
        elif isinstance(self.credential_store, MacOSKeychainCredentialStore):
            targets.append(
                "credentials store: macOS Keychain "
                f"({self.credential_store.service_name}/{self.credential_store.account_name})"
            )
        else:
            targets.append(
                f"credentials store: {self.credential_store.__class__.__name__}"
            )
        return targets

    def run_auth_login(self) -> bool:
        """Run `claude auth login` if the Claude CLI is available."""
        claude_path = shutil.which("claude")
        if not claude_path:
            return False
        subprocess.run([claude_path, "auth", "login"], check=False)
        return True

    def run_print_prompt(self, prompt: str) -> tuple[bool, str]:
        """Run `claude -p <prompt>` and return whether it succeeded."""
        claude_path = shutil.which("claude")
        if not claude_path:
            return False, "`claude` was not found in PATH."
        result = subprocess.run(
            [claude_path, "-p", prompt],
            check=False,
            capture_output=True,
            text=True,
        )
        output = (result.stdout or result.stderr or "").strip()
        if result.returncode != 0:
            if not output:
                output = f"`claude -p` exited with status {result.returncode}."
            return False, output
        return True, output

    def read_auth_status(self) -> dict[str, Any] | None:
        """Return structured `claude auth status` output when available."""
        claude_path = shutil.which("claude")
        if not claude_path:
            return None
        try:
            result = subprocess.run(
                [claude_path, "auth", "status"],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError:
            return None
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def _backup_live_state(self) -> None:
        """Back up current auth files before mutation."""
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        if self.config_path.exists():
            shutil.copy2(self.config_path, self.backup_dir / self.config_path.name)
        self.credential_store.backup(self.backup_dir)
