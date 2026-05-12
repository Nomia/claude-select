from __future__ import annotations

import json

from claude_select import cli
from claude_select.manager import AuthManager


def test_cli_init_and_list(monkeypatch, capsys, registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    monkeypatch.setattr(cli, "AuthManager", lambda: manager)
    monkeypatch.setattr(manager, "wait_for_login", lambda _launch: None)
    answers = iter(["work", "n", "n", "n"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    assert cli.main(["init"]) == 0
    assert cli.main(["list"]) == 0

    output = capsys.readouterr().out
    assert "work@example.com" in output
    assert "Example Org" in output
    assert "Current registry:" in output
    assert "Status: healthy" in output
    assert "Kind" in output


def test_cli_select_and_current(
    monkeypatch, capsys, registry, fake_auth_backend, fake_usage_provider
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    monkeypatch.setattr(cli, "AuthManager", lambda: manager)

    assert cli.main(["select", "work"]) == 0
    assert cli.main(["current", "--json"]) == 0

    output = capsys.readouterr().out
    assert "Selected work <work@example.com> [Example Org]." in output
    assert "Updated Claude live auth state:" in output
    assert "Current CLI alias: work" in output
    payload = json.loads(
        output.split("Current CLI alias: work\n", maxsplit=1)[1]
    )
    assert payload["current_alias"] == "work"


def test_cli_export_env(monkeypatch, capsys, registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    monkeypatch.setattr(cli, "AuthManager", lambda: manager)

    assert cli.main(["export-env", "work", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["CLAUDE_CODE_OAUTH_TOKEN"] == "access-1"


def test_cli_export_env_plain(
    monkeypatch, capsys, registry, fake_auth_backend, fake_usage_provider
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    monkeypatch.setattr(cli, "AuthManager", lambda: manager)

    assert cli.main(["export-env", "work"]) == 0

    output = capsys.readouterr().out
    assert "CLAUDE_CODE_OAUTH_TOKEN=access-1" in output


def test_cli_add_relogin_remove_current_plain(
    monkeypatch, capsys, registry, fake_auth_backend, fake_usage_provider
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    monkeypatch.setattr(cli, "AuthManager", lambda: manager)
    monkeypatch.setattr(manager, "wait_for_login", lambda _launch: None)

    assert cli.main(["add", "work"]) == 0
    assert cli.main(["select", "work"]) == 0
    assert cli.main(["current"]) == 0
    assert cli.main(["relogin", "work"]) == 0
    assert cli.main(["remove", "work"]) == 0

    output = capsys.readouterr().out
    assert "Captured work <work@example.com> [Example Org]." in output
    assert "Current registry:" in output
    assert "Status: healthy" in output
    assert "work" in output
    assert "Updated work <work@example.com> [Example Org]." in output
    assert "Removed work." in output


def test_cli_add_token(monkeypatch, capsys, registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    monkeypatch.setattr(cli, "AuthManager", lambda: manager)
    monkeypatch.setattr(cli, "_run_setup_token", lambda _launch: None)
    answers = iter(["long-lived-token", "sdk@example.com", "SDK Org", "", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    assert cli.main(["add-token", "work-sdk"]) == 0

    output = capsys.readouterr().out
    assert "[token] work-sdk <sdk@example.com> [SDK Org]." in output
    assert "Kind" in output
    assert "token" in output


def test_cli_init_with_token_phase(
    monkeypatch, capsys, registry, fake_auth_backend, fake_usage_provider
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    monkeypatch.setattr(cli, "AuthManager", lambda: manager)
    monkeypatch.setattr(manager, "wait_for_login", lambda _launch: None)
    monkeypatch.setattr(cli, "_run_setup_token", lambda _launch: None)
    answers = iter(
        [
            "work",
            "n",
            "y",
            "work-sdk",
            "long-lived-token",
            "sdk@example.com",
            "SDK Org",
            "",
            "",
            "n",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    assert cli.main(["init"]) == 0

    output = capsys.readouterr().out
    assert "[token] work-sdk <sdk@example.com> [SDK Org]." in output
    assert "Current registry:" in output


def test_cli_add_no_launch(monkeypatch, registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    monkeypatch.setattr(cli, "AuthManager", lambda: manager)
    observed: list[bool] = []
    monkeypatch.setattr(manager, "wait_for_login", lambda launch: observed.append(launch))

    assert cli.main(["add", "work", "--no-launch"]) == 0
    assert observed == [False]


def test_cli_watch_and_interactive_select(
    monkeypatch, capsys, registry, fake_auth_backend, fake_usage_provider
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    monkeypatch.setattr(cli, "AuthManager", lambda: manager)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "work")

    assert cli.main(["watch", "--iterations", "1", "--interval", "1"]) == 0
    assert cli.main(["select"]) == 0

    output = capsys.readouterr().out
    assert "Current Claude live account" in output
    assert "matched alias: work" in output
    assert "76.0%" in output
    assert "Alias" in output
    assert "Organization" in output
    assert "Selected work <work@example.com> [Example Org]." in output
    assert "Updated Claude live auth state:" in output


def test_cli_sync_current(monkeypatch, capsys, registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    fake_auth_backend.snapshot.credentials["claudeAiOauth"]["expiresAt"] = 4102448400000
    monkeypatch.setattr(cli, "AuthManager", lambda: manager)

    assert cli.main(["sync-current"]) == 0

    output = capsys.readouterr().out
    assert "Synced current live auth state into 'work'." in output
    assert "Current registry:" in output


def test_cli_help_texts(capsys):
    for argv in (
        ["--help"],
        ["add", "--help"],
        ["add-token", "--help"],
        ["select", "--help"],
        ["export-env", "--help"],
        ["whoami", "--help"],
        ["sync-current", "--help"],
    ):
        try:
            cli.main(argv)
        except SystemExit as exc:
            assert exc.code == 0

    output = capsys.readouterr().out
    assert "Typical flow:" in output
    assert "claude-select add work" in output
    assert "claude-select add-token work-sdk" in output
    assert "claude-select select work" in output
    assert "claude-select export-env work --json" in output
    assert "Show the current Claude live auth state." in output


def test_cli_whoami(monkeypatch, capsys, registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    fake_auth_backend.snapshot.credentials["claudeAiOauth"]["expiresAt"] = 4102448400000
    monkeypatch.setattr(cli, "AuthManager", lambda: manager)

    assert cli.main(["whoami"]) == 0
    output = capsys.readouterr().out
    assert "Current Claude live account" in output
    assert "matched alias: work" in output
    assert manager.get_account("work").record.expires_at == 4102448400000

    assert cli.main(["whoami", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["matched_alias"] == "work"
    assert payload["quota_5h_left"] == "76.0%"


def test_cli_sync_current_json(
    monkeypatch, capsys, registry, fake_auth_backend, fake_usage_provider
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    fake_auth_backend.snapshot.credentials["claudeAiOauth"]["expiresAt"] = 4102448400000
    monkeypatch.setattr(cli, "AuthManager", lambda: manager)

    assert cli.main(["sync-current", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "synced"
    assert payload["matched_alias"] == "work"


def test_cli_list_with_usage(monkeypatch, capsys, registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    fake_auth_backend.snapshot.credentials["claudeAiOauth"]["expiresAt"] = 4102448400000
    monkeypatch.setattr(cli, "AuthManager", lambda: manager)

    assert cli.main(["list", "--usage"]) == 0

    output = capsys.readouterr().out
    assert "5h Left" in output
    assert "76.0%" in output
    assert manager.get_account("work").record.expires_at == 4102448400000


def test_cli_export_env_plain_and_setup_token_guidance(monkeypatch, capsys):
    monkeypatch.setattr(cli.shutil, "which", lambda _name: None)

    cli._run_setup_token(False)
    cli._run_setup_token(True)

    output = capsys.readouterr().out
    assert "Run `claude setup-token`, copy the token, then return here." in output
    assert "`claude` was not found in PATH." in output
