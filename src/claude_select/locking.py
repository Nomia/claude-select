"""Cross-platform file locking."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import IO

from claude_select.exceptions import LockTimeoutError

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


class FileLock:
    """A simple cross-process file lock."""

    def __init__(self, path: Path):
        self.path = path
        self._handle: IO[str] | None = None
        self._locked = False

    def acquire(self, timeout: float = 10.0) -> None:
        """Acquire an exclusive lock or raise on timeout."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a+", encoding="utf-8")
        deadline = time.monotonic() + timeout
        while True:
            try:
                if sys.platform == "win32":
                    msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._locked = True
                return
            except OSError as exc:
                if time.monotonic() >= deadline:
                    self.release()
                    raise LockTimeoutError(f"Timed out waiting for lock: {self.path}") from exc
                time.sleep(0.05)

    def release(self) -> None:
        """Release the lock if held."""
        if not self._handle:
            return
        try:
            if self._locked:
                if sys.platform == "win32":
                    msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None
            self._locked = False

    def __enter__(self) -> FileLock:
        self.acquire()
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()
