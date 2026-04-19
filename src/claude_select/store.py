"""Profile store implementation."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from claude_select.locking import FileLock
from claude_select.models import ProfileMetadata, SecretPayload, StateFile
from claude_select.paths import get_default_store_root


class FileProfileStore:
    """File-backed profile store."""

    def __init__(self, root: Path | None = None):
        self.root = root or get_default_store_root()
        self.state_path = self.root / "state.json"
        self.secrets_dir = self.root / "secrets"
        self.lock_path = self.root / ".lock"

    def ensure_layout(self) -> None:
        """Create the expected store directories."""
        self.root.mkdir(parents=True, exist_ok=True)
        self.secrets_dir.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(self.root, 0o700)
            os.chmod(self.secrets_dir, 0o700)

    def lock(self) -> FileLock:
        """Return the store lock."""
        self.ensure_layout()
        return FileLock(self.lock_path)

    def load_state(self) -> StateFile:
        """Load state.json or return an empty default state."""
        self.ensure_layout()
        if not self.state_path.exists():
            return StateFile()
        return StateFile.from_dict(self._read_json(self.state_path))

    def save_state(self, state: StateFile) -> None:
        """Persist the full state file."""
        self.ensure_layout()
        self._write_json_atomic(self.state_path, state.to_dict())

    def list_profiles(self) -> list[ProfileMetadata]:
        """Return all known profiles sorted by id."""
        state = self.load_state()
        return [state.profiles[name] for name in sorted(state.profiles)]

    def get_profile(self, name: str) -> ProfileMetadata:
        """Return profile metadata by name."""
        state = self.load_state()
        return state.profiles[name]

    def get_secret(self, ref: str) -> SecretPayload:
        """Return a secret payload."""
        path = self.secrets_dir / f"{ref}.json"
        return SecretPayload.from_dict(self._read_json(path))

    def upsert_profile(self, profile: ProfileMetadata, secret: SecretPayload) -> None:
        """Insert or update a profile and its secret payload."""
        self.ensure_layout()
        with self.lock():
            state = self.load_state()
            state.profiles[profile.id] = profile
            self.save_state(state)
            self._write_json_atomic(
                self.secrets_dir / f"{profile.secret_ref}.json",
                secret.to_dict(),
                mode=0o600,
            )

    def update_profile(self, profile: ProfileMetadata) -> None:
        """Update metadata for an existing profile."""
        self.ensure_layout()
        with self.lock():
            state = self.load_state()
            state.profiles[profile.id] = profile
            self.save_state(state)

    def remove_profile(self, name: str) -> None:
        """Remove a profile and its secret payload if present."""
        self.ensure_layout()
        with self.lock():
            state = self.load_state()
            profile = state.profiles.pop(name)
            if state.current_cli_profile == name:
                state.current_cli_profile = None
            if state.default_sdk_profile == name:
                state.default_sdk_profile = None
            self.save_state(state)
            secret_path = self.secrets_dir / f"{profile.secret_ref}.json"
            if secret_path.exists():
                secret_path.unlink()

    def set_current_cli_profile(self, name: str | None) -> None:
        """Persist the current CLI profile pointer."""
        self.ensure_layout()
        with self.lock():
            state = self.load_state()
            state.current_cli_profile = name
            self.save_state(state)

    def set_default_sdk_profile(self, name: str | None) -> None:
        """Persist the default SDK profile pointer."""
        self.ensure_layout()
        with self.lock():
            state = self.load_state()
            state.default_sdk_profile = name
            self.save_state(state)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _write_json_atomic(path: Path, value: dict[str, Any], mode: int | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
        ) as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temp_name = handle.name
        os.replace(temp_name, path)
        if mode is not None and os.name != "nt":
            os.chmod(path, mode)
