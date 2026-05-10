from __future__ import annotations

from claude_select.locking import FileLock


def test_file_lock_context_manager(tmp_path):
    lock = FileLock(tmp_path / "registry.lock")

    with lock:
        assert lock._locked is True

    assert lock._locked is False
