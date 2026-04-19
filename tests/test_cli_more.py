from __future__ import annotations

from claude_select import cli
from claude_select.manager import ProfileManager


def test_cli_current_set_default_inspect_remove(monkeypatch, capsys, store, fake_live_backend):
    manager = ProfileManager(store=store, live_state_backend=fake_live_backend)
    manager.capture_cli_profile("work")
    monkeypatch.setattr(cli, "ProfileManager", lambda: manager)

    assert cli.main(["set-default-sdk", "work"]) == 0
    assert cli.main(["current", "--json"]) == 0
    assert cli.main(["inspect", "work", "--json"]) == 0
    assert cli.main(["remove", "work"]) == 0

    output = capsys.readouterr().out
    assert "Default SDK profile set to 'work'." in output
    assert '"current_cli_profile": "work"' in output
    assert '"id": "work"' in output
    assert "Removed profile 'work'." in output


def test_cli_errors(monkeypatch, capsys, store, fake_live_backend):
    manager = ProfileManager(store=store, live_state_backend=fake_live_backend)
    monkeypatch.setattr(cli, "ProfileManager", lambda: manager)

    assert cli.main(["inspect", "missing"]) == 1

    error = capsys.readouterr().err
    assert "Error:" in error
