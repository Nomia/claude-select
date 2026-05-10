from __future__ import annotations

import json

from claude_select import cli
from claude_select.manager import AuthManager


def test_cli_init_and_list(monkeypatch, capsys, registry, fake_auth_backend):
    manager = AuthManager(registry=registry, auth_backend=fake_auth_backend)
    monkeypatch.setattr(cli, "AuthManager", lambda: manager)
    answers = iter(["work", "", "n"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    assert cli.main(["init"]) == 0
    assert cli.main(["list"]) == 0

    output = capsys.readouterr().out
    assert "work@example.com" in output


def test_cli_select_and_current(monkeypatch, capsys, registry, fake_auth_backend):
    manager = AuthManager(registry=registry, auth_backend=fake_auth_backend)
    manager.capture_current_account("work")
    monkeypatch.setattr(cli, "AuthManager", lambda: manager)

    assert cli.main(["select", "work"]) == 0
    assert cli.main(["current", "--json"]) == 0

    output = capsys.readouterr().out
    assert "Selected work <work@example.com>." in output
    payload = json.loads(output.split("Selected work <work@example.com>.\n", maxsplit=1)[1])
    assert payload["current_alias"] == "work"


def test_cli_export_env(monkeypatch, capsys, registry, fake_auth_backend):
    manager = AuthManager(registry=registry, auth_backend=fake_auth_backend)
    manager.capture_current_account("work")
    monkeypatch.setattr(cli, "AuthManager", lambda: manager)

    assert cli.main(["export-env", "work", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["CLAUDE_CODE_OAUTH_TOKEN"] == "access-1"


def test_cli_add_relogin_remove_current_plain(monkeypatch, capsys, registry, fake_auth_backend):
    manager = AuthManager(registry=registry, auth_backend=fake_auth_backend)
    monkeypatch.setattr(cli, "AuthManager", lambda: manager)
    monkeypatch.setattr(manager, "wait_for_login", lambda _launch: None)

    assert cli.main(["add", "work"]) == 0
    assert cli.main(["select", "work"]) == 0
    assert cli.main(["current"]) == 0
    assert cli.main(["relogin", "work"]) == 0
    assert cli.main(["remove", "work"]) == 0

    output = capsys.readouterr().out
    assert "Captured work <work@example.com>." in output
    assert "work" in output
    assert "Updated work <work@example.com>." in output
    assert "Removed work." in output


def test_cli_watch_and_interactive_select(monkeypatch, capsys, registry, fake_auth_backend):
    manager = AuthManager(registry=registry, auth_backend=fake_auth_backend)
    manager.capture_current_account("work")
    monkeypatch.setattr(cli, "AuthManager", lambda: manager)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "work")

    assert cli.main(["watch", "--iterations", "1", "--interval", "1"]) == 0
    assert cli.main(["select"]) == 0

    output = capsys.readouterr().out
    assert "Alias" in output
    assert "Selected work <work@example.com>." in output
