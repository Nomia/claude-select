from __future__ import annotations

import json

from claude_switch import cli
from claude_switch.manager import ProfileManager


def test_cli_capture_and_list(monkeypatch, capsys, store, fake_live_backend):
    manager = ProfileManager(store=store, live_state_backend=fake_live_backend)
    monkeypatch.setattr(cli, "ProfileManager", lambda: manager)

    assert cli.main(["capture", "work"]) == 0
    assert cli.main(["list", "--json"]) == 0

    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    json_start = next(index for index, line in enumerate(lines) if line.strip() == "[")
    payload = json.loads("\n".join(lines[json_start:]))
    assert payload[0]["id"] == "work"


def test_cli_use_reports_refresh_error(monkeypatch, capsys, store, fake_live_backend):
    fake_live_backend._live_state.credentials["claudeAiOauth"]["expiresAt"] = 1
    manager = ProfileManager(
        store=store,
        live_state_backend=fake_live_backend,
        refresh_request=lambda _refresh_token: (_ for _ in ()).throw(RuntimeError("expired")),
    )
    manager.capture_cli_profile("work")
    monkeypatch.setattr(cli, "ProfileManager", lambda: manager)

    assert cli.main(["use", "work"]) == 0

    captured = capsys.readouterr()
    assert "Switched CLI to profile 'work'." in captured.out
    assert "reauthentication" in captured.err
