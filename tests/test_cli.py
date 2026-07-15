from __future__ import annotations

import json

import pytest

from claude_select import cli
from claude_select.exceptions import ClaudeSelectError
from claude_select.manager import AuthManager


def test_cli_init_and_list(monkeypatch, capsys, registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    monkeypatch.setattr(cli, "AuthManager", lambda: manager)
    monkeypatch.setattr(manager, "wait_for_login", lambda _launch: None)
    monkeypatch.setattr(
        cli,
        "_confirm_current_auth_status",
        lambda manager, *, alias, action: None,
    )
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


def test_cli_usage_plain(monkeypatch, capsys, registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    monkeypatch.setattr(cli, "AuthManager", lambda: manager)

    assert cli.main(["usage", "work"]) == 0

    output = capsys.readouterr().out
    assert "alias: work" in output
    assert "email: work@example.com" in output
    assert "5h left: 76.0%" in output
    assert "7d left: 59.0%" in output


def test_cli_usage_json(monkeypatch, capsys, registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    monkeypatch.setattr(cli, "AuthManager", lambda: manager)

    assert cli.main(["usage", "work", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["alias"] == "work"
    assert payload["quota_5h_left"] == "76.0%"
    assert payload["quota_7d_left"] == "59.0%"


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
    monkeypatch.setattr(
        cli,
        "_confirm_current_auth_status",
        lambda manager, *, alias, action: None,
    )

    assert cli.main(["add", "work"]) == 0
    assert cli.main(["select", "work"]) == 0
    assert cli.main(["current"]) == 0
    fake_auth_backend.snapshot.credentials["claudeAiOauth"]["accessToken"] = "access-2"
    assert cli.main(["relogin", "work"]) == 0
    assert cli.main(["remove", "work"]) == 0

    output = capsys.readouterr().out
    assert "Captured work <work@example.com> [Example Org]." in output


def test_cli_rename_account(
    monkeypatch, capsys, registry, fake_auth_backend, fake_usage_provider
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    monkeypatch.setattr(cli, "AuthManager", lambda: manager)

    assert cli.main(["rename", "work", "personal"]) == 0

    output = capsys.readouterr().out
    assert "Renamed work -> personal" in output
    assert manager.get_account("personal").record.alias == "personal"


def test_cli_select_expired_account_warns(
    monkeypatch, capsys, registry, fake_auth_backend, fake_usage_provider
):
    fake_auth_backend.snapshot.credentials["claudeAiOauth"]["expiresAt"] = 1
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    monkeypatch.setattr(cli, "AuthManager", lambda: manager)

    assert cli.main(["select", "work"]) == 0

    output = capsys.readouterr().out
    assert "Selected work <work@example.com> [Example Org]." in output
    assert "Warning: work is expired." in output
    assert "claude-select refresh work" in output


def test_cli_add_token(monkeypatch, capsys, registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    monkeypatch.setattr(cli, "AuthManager", lambda: manager)
    monkeypatch.setattr(
        cli,
        "_run_setup_token",
        lambda _launch: "Your OAuth token:\n\nsk-ant-oat01-tokenvalue\n",
    )
    monkeypatch.setattr(
        manager,
        "probe_token",
        lambda _token: {
            "valid": True,
            "metadata": {
                "email": "sdk@example.com",
                "organization_name": "SDK Org",
            },
            "error": None,
        },
    )
    answers = iter([])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    assert cli.main(["add-token", "work-sdk"]) == 0

    output = capsys.readouterr().out
    assert "Detected the long-lived token from setup-token output." in output
    assert "Validated token for SDK/program use." in output
    assert "Detected account metadata:" in output
    assert "email: sdk@example.com" in output
    assert "[token] work-sdk <sdk@example.com> [SDK Org]." in output
    assert "Kind" in output
    assert "token" in output


def test_cli_add_token_prompts_when_metadata_missing(
    monkeypatch, capsys, registry, fake_auth_backend, fake_usage_provider
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    monkeypatch.setattr(cli, "AuthManager", lambda: manager)
    monkeypatch.setattr(cli, "_run_setup_token", lambda _launch: "")
    monkeypatch.setattr(
        manager,
        "probe_token",
        lambda _token: {"valid": False, "metadata": {}, "error": "boom"},
    )
    answers = iter(["long-lived-token", "sdk@example.com", "SDK Org"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    assert cli.main(["add-token", "work-sdk"]) == 0

    output = capsys.readouterr().out
    assert "Could not validate the token automatically." in output
    assert "Detected account metadata:" not in output
    assert "[token] work-sdk <sdk@example.com> [SDK Org]." in output


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
    monkeypatch.setattr(
        cli,
        "_confirm_current_auth_status",
        lambda manager, *, alias, action: None,
    )
    monkeypatch.setattr(cli, "_run_setup_token", lambda _launch: "")
    monkeypatch.setattr(
        manager,
        "probe_token",
        lambda _token: {
            "valid": True,
            "metadata": {
                "email": "sdk@example.com",
                "organization_name": "SDK Org",
            },
            "error": None,
        },
    )
    answers = iter(
        [
            "work",
            "n",
            "y",
            "work-sdk",
            "long-lived-token",
            "n",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    assert cli.main(["init"]) == 0

    output = capsys.readouterr().out
    assert "[token] work-sdk <sdk@example.com> [SDK Org]." in output
    assert "Current registry:" in output


def test_extract_token_from_output():
    output = "Your OAuth token:\n\nsk-ant-oat01-abc_DEF-123\n"

    assert cli._extract_token_from_output(output) == "sk-ant-oat01-abc_DEF-123"


def test_extract_token_from_output_multiline():
    output = "Your OAuth token:\n\nsk-ant-oat01-abc_DEF-\n123-XYZ\n\nStore this token securely.\n"

    assert cli._extract_token_from_output(output) == "sk-ant-oat01-abc_DEF-123-XYZ"


def test_extract_token_from_output_missing():
    assert cli._extract_token_from_output("no token here") is None


def test_stream_and_capture_command(monkeypatch, capsys):
    class FakeProcess:
        def __init__(self):
            self.stdout = iter(["line 1\n", "line 2\n"])

        def wait(self):
            return 0

    monkeypatch.setattr(cli.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())

    output = cli._stream_and_capture_command(["claude", "setup-token"])

    assert output == "line 1\nline 2\n"
    assert "line 1" in capsys.readouterr().out


def test_run_setup_token_without_launch(capsys):
    output = cli._run_setup_token(False)

    assert output == ""
    assert "Run `claude setup-token`, copy the token, then return here." in capsys.readouterr().out


def test_run_setup_token_with_launch(monkeypatch, capsys):
    monkeypatch.setattr(cli.shutil, "which", lambda _name: "/usr/bin/claude")
    observed: list[list[str]] = []
    monkeypatch.setattr(
        cli,
        "_stream_and_capture_command",
        lambda command: observed.append(command) or "captured-output",
    )

    output = cli._run_setup_token(True)

    assert output == "captured-output"
    assert observed == [["/usr/bin/claude", "setup-token"]]
    text = capsys.readouterr().out
    assert "Launching `claude setup-token` in this terminal." in text


def test_prompt_for_token_capture_scope_limited(
    monkeypatch, capsys, registry, fake_auth_backend, fake_usage_provider
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    monkeypatch.setattr(cli, "_run_setup_token", lambda _launch: "sk-ant-oat01-abc\nDEF\n")
    monkeypatch.setattr(
        manager,
        "probe_token",
        lambda _token: {
            "valid": True,
            "metadata": {},
            "error": None,
            "warning": "Profile metadata is unavailable for this token scope.",
        },
    )
    answers = iter(["sdk@example.com", "SDK Org"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    payload = cli._prompt_for_token_capture(manager, launch=True)

    assert payload["token"] == "sk-ant-oat01-abcDEF"
    assert payload["email"] == "sdk@example.com"
    output = capsys.readouterr().out
    assert "Validated token for SDK/program use." in output
    assert "Profile metadata is unavailable for this token scope." in output


def test_build_panels_for_empty_and_error_state(
    registry, fake_auth_backend, fake_usage_provider, monkeypatch
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    monkeypatch.setattr(
        manager,
        "current_live_account",
        lambda *args, **kwargs: (_ for _ in ()).throw(ClaudeSelectError("bad live state")),
    )

    panel = cli._build_current_account_panel(manager)
    table_or_panel = cli._build_accounts_table(manager, include_usage=True)

    assert "bad live state" in str(panel.renderable)
    assert "No accounts have been captured yet." in str(table_or_panel.renderable)


def test_cli_add_no_launch(monkeypatch, registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    monkeypatch.setattr(cli, "AuthManager", lambda: manager)
    observed: list[bool] = []
    monkeypatch.setattr(manager, "wait_for_login", lambda launch: observed.append(launch))
    monkeypatch.setattr(
        cli,
        "_confirm_current_auth_status",
        lambda manager, *, alias, action: None,
    )

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
    assert "auth method: claude.ai" in output
    assert "subscription: team" in output
    assert "Alias" in output
    assert "Organization" in output
    assert "Last Synced" in output
    assert "Selected work <work@example.com> [Example Org]." in output
    assert "Updated Claude live auth state:" in output


def test_cli_watch_usage_flag(
    monkeypatch, capsys, registry, fake_auth_backend, fake_usage_provider
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    monkeypatch.setattr(cli, "AuthManager", lambda: manager)

    assert cli.main(["watch", "--usage", "--iterations", "1", "--interval", "1"]) == 0

    table = cli._build_accounts_table(manager, include_usage=True)
    output = capsys.readouterr().out
    assert "Current Claude live account" in output
    assert "auth method: claude.ai" in output
    assert [column.header for column in table.columns][-4:] == [
        "5h Left",
        "5h Reset",
        "7d Left",
        "7d Reset",
    ]


def test_cli_list_usage_prints_diagnostics(monkeypatch, capsys):
    row = {
        "alias": "work",
        "auth_kind": "cli_snapshot",
        "kind_label": "cli",
        "email": "work@example.com",
        "organization_name": "Example Org",
        "status": "healthy",
        "expires_in": "7h 0m",
        "last_selected_at": None,
        "last_synced_at": None,
        "quota_5h_left": "100.0%~",
        "quota_5h_reset": "unknown",
        "quota_7d_left": "95.0%~",
        "quota_7d_reset": "6d 5h~",
        "stale": True,
        "available": True,
        "error": "Usage API request failed: ECONNREFUSED",
        "fetched_at": None,
    }

    class StubManager:
        def __init__(self):
            self.auth_backend = None

        def list_accounts(self, include_usage=False, auto_refresh=False):
            assert include_usage is True
            return [row]

        def render_table(self, include_usage=False):
            raise AssertionError("render_table should not be used for --usage")

        def _table_row(self, payload, include_usage):
            return [
                payload["alias"],
                payload["kind_label"],
                payload["email"],
                payload["organization_name"],
                payload["status"],
                payload["expires_in"],
                "-",
                "-",
                payload["quota_5h_left"],
                payload["quota_5h_reset"],
                payload["quota_7d_left"],
                payload["quota_7d_reset"],
            ]

        def _format_last_selected(self, value):
            return value if value else "-"

    monkeypatch.setattr(cli, "AuthManager", lambda: StubManager())
    monkeypatch.setattr(cli, "_best_effort_sync_current", lambda _manager: None)

    assert cli.main(["list", "--usage"]) == 0
    output = capsys.readouterr().out
    assert "Usage diagnostics:" in output
    assert "work: stale usage cache" in output
    assert "Usage API request failed: ECONNREFUSED" in output


def test_build_usage_diagnostics_panel_shows_stale_and_unavailable(
    registry, fake_auth_backend, fake_usage_provider
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    rows = [
        {
            "alias": "work",
            "auth_kind": "cli_snapshot",
            "kind_label": "cli",
            "stale": True,
            "available": True,
            "error": "boom",
            "fetched_at": None,
        },
        {
            "alias": "personal",
            "auth_kind": "cli_snapshot",
            "kind_label": "cli",
            "stale": False,
            "available": False,
            "error": "usage unavailable",
            "fetched_at": None,
        },
    ]

    panel = cli._build_usage_diagnostics_panel(manager, rows)

    assert panel is not None
    rendered = panel.renderable
    text = rendered if isinstance(rendered, str) else str(rendered)
    assert "work: stale usage cache" in text
    assert "personal: usage unavailable" in text


def test_watch_key_requests_exit():
    assert cli._watch_key_requests_exit("q") is True
    assert cli._watch_key_requests_exit("Q") is True
    assert cli._watch_key_requests_exit("\x1b") is True
    assert cli._watch_key_requests_exit("x") is False
    assert cli._watch_key_requests_exit(None) is False


def test_watch_input_context_non_tty(monkeypatch):
    class FakeStdin:
        def isatty(self):
            return False

    monkeypatch.setattr(cli.sys, "stdin", FakeStdin())

    context = cli._watch_input_context()

    assert isinstance(context, cli._NullContext)


def test_watch_input_context_tty(monkeypatch):
    class FakeStdin:
        def isatty(self):
            return True

        def fileno(self):
            return 9

    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(cli.sys, "stdin", FakeStdin())
    monkeypatch.setattr(cli.termios, "tcgetattr", lambda fd: ["orig", fd])
    monkeypatch.setattr(cli.tty, "setcbreak", lambda fd: calls.append(("setcbreak", fd)))
    monkeypatch.setattr(
        cli.termios,
        "tcsetattr",
        lambda fd, when, original: calls.append(("tcsetattr", fd, when, original)),
    )

    context = cli._watch_input_context()

    assert isinstance(context, cli._TTYContext)
    context.__enter__()
    context.__exit__(None, None, None)
    assert calls[0] == ("setcbreak", 9)
    assert calls[1][0] == "tcsetattr"
    assert calls[1][1] == 9


def test_watch_input_context_tty_fallback_on_error(monkeypatch):
    class FakeStdin:
        def isatty(self):
            return True

        def fileno(self):
            raise ValueError("boom")

    monkeypatch.setattr(cli.sys, "stdin", FakeStdin())

    context = cli._watch_input_context()

    assert isinstance(context, cli._NullContext)


def test_read_watch_key_non_tty(monkeypatch):
    class FakeStdin:
        def isatty(self):
            return False

    monkeypatch.setattr(cli.sys, "stdin", FakeStdin())

    assert cli._read_watch_key() is None


def test_read_watch_key_paths(monkeypatch):
    class FakeStdin:
        def isatty(self):
            return True

        def fileno(self):
            return 9

    monkeypatch.setattr(cli.sys, "stdin", FakeStdin())
    monkeypatch.setattr(cli.select, "select", lambda *args, **kwargs: ([cli.sys.stdin], [], []))
    monkeypatch.setattr(cli.os, "read", lambda fd, size: b"q")

    assert cli._read_watch_key() == "q"
    assert cli._watch_exit_requested() is True


def test_read_watch_key_handles_empty_and_errors(monkeypatch):
    class FakeStdin:
        def isatty(self):
            return True

        def fileno(self):
            return 9

    monkeypatch.setattr(cli.sys, "stdin", FakeStdin())
    monkeypatch.setattr(cli.select, "select", lambda *args, **kwargs: ([], [], []))
    assert cli._read_watch_key() is None

    monkeypatch.setattr(
        cli.select,
        "select",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("boom")),
    )
    assert cli._read_watch_key() is None

    monkeypatch.setattr(cli.select, "select", lambda *args, **kwargs: ([cli.sys.stdin], [], []))
    monkeypatch.setattr(cli.os, "read", lambda fd, size: b"")
    assert cli._read_watch_key() is None

    monkeypatch.setattr(cli.os, "read", lambda fd, size: (_ for _ in ()).throw(OSError("boom")))
    assert cli._read_watch_key() is None


def test_run_watch_handles_keyboard_interrupt(
    monkeypatch, registry, fake_auth_backend, fake_usage_provider
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    monkeypatch.setattr(cli, "_watch_input_context", lambda: cli._NullContext())
    monkeypatch.setattr(cli, "_watch_exit_requested", lambda: False)
    monkeypatch.setattr(
        cli.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    assert (
        cli._run_watch(
            manager,
            interval=1,
            sync_interval=60,
            iterations=0,
            include_usage=False,
            auto_refresh=False,
        )
        == 0
    )


def test_watch_auto_refresh_helper(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    details = manager.get_account("work")
    manager.registry.upsert_account(
        alias="work",
        auth_kind=details.record.auth_kind,
        email=details.record.email,
        organization_name=details.record.organization_name,
        organization_id=details.record.organization_id,
        account_uuid=details.record.account_uuid,
        captured_at=details.record.captured_at,
        expires_at=0,
        last_selected_at=details.record.last_selected_at,
        source=details.record.source,
        snapshot=details.snapshot,
        last_synced_at=details.record.last_synced_at,
    )
    manager.auto_refresh_candidates = lambda: ["work"]  # type: ignore[method-assign]

    message = cli._maybe_auto_refresh_accounts(manager, {}, 1000.0)

    assert message is not None
    assert "Auto-refreshed work" in message
    assert fake_auth_backend.print_prompts == ["ping"]


def test_watch_auto_refresh_expired_accounts_retry_on_longer_cooldown(
    registry, fake_auth_backend, fake_usage_provider
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    details = manager.get_account("work")
    manager.registry.upsert_account(
        alias="work",
        auth_kind=details.record.auth_kind,
        email=details.record.email,
        organization_name=details.record.organization_name,
        organization_id=details.record.organization_id,
        account_uuid=details.record.account_uuid,
        captured_at=details.record.captured_at,
        expires_at=0,
        last_selected_at=details.record.last_selected_at,
        source=details.record.source,
        snapshot=details.snapshot,
        last_synced_at=details.record.last_synced_at,
    )

    message = cli._maybe_auto_refresh_accounts(manager, {}, 1000.0)
    assert message is not None
    assert "Auto-refreshed work" in message

    fake_auth_backend.print_prompts.clear()
    attempts = {"work": 1000.0}
    message = cli._maybe_auto_refresh_accounts(manager, attempts, 1059.0)
    assert message is None
    assert fake_auth_backend.print_prompts == []

    message = cli._maybe_auto_refresh_accounts(manager, attempts, 1061.0)
    assert message is not None
    assert "Auto-refreshed work" in message
    assert fake_auth_backend.print_prompts == ["ping"]


def test_watch_usage_refresh_rate_limits_with_backoff(
    monkeypatch, registry, fake_auth_backend, fake_usage_provider
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    rows = [
        {
            "alias": "work",
            "auth_kind": "cli_snapshot",
            "kind_label": "cli",
            "available": True,
            "stale": True,
        }
    ]

    def boom(alias: str, **kwargs):
        raise ClaudeSelectError("Usage API request failed: Too Many Requests")

    monkeypatch.setattr(manager, "get_account_quota", boom)

    state: dict[str, dict[str, object]] = {}
    message = cli._maybe_refresh_watch_usage(manager, rows=rows, state=state, now=1000.0)

    assert message is not None
    assert "rate-limited" in message
    assert state["work"]["backoff_until"] == (
        1000.0 + cli.WATCH_USAGE_ALIAS_RATE_LIMIT_BACKOFF_SECONDS
    )
    assert state["_global"]["backoff_until"] == (
        1000.0 + cli.WATCH_USAGE_GLOBAL_RATE_LIMIT_BACKOFF_SECONDS
    )

    message = cli._maybe_refresh_watch_usage(manager, rows=rows, state=state, now=1001.0)
    assert message is not None
    assert "backing off globally" in message


def test_watch_hint_panel_for_expired_account(registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.list_accounts = lambda include_usage=False: [  # type: ignore[method-assign]
        {
            "alias": "work",
            "auth_kind": "cli",
            "kind_label": "cli",
            "status": "expired",
        }
    ]

    hint = cli._build_watch_hint_panel(manager)

    assert hint is not None
    assert hint.title == "Action recommended"
    assert "claude-select refresh work" in str(hint.renderable)
    assert "claude-select watch --auto-refresh" in str(hint.renderable)
    assert "claude-select relogin work" in str(hint.renderable)


def test_watch_hint_panel_for_expired_account_with_auto_refresh(
    registry, fake_auth_backend, fake_usage_provider
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.list_accounts = lambda include_usage=False: [  # type: ignore[method-assign]
        {
            "alias": "work",
            "auth_kind": "cli",
            "kind_label": "cli",
            "status": "expired",
        }
    ]

    hint = cli._build_watch_hint_panel(manager, auto_refresh=True)

    assert hint is not None
    assert "Auto-refresh is enabled" in str(hint.renderable)
    assert "claude-select refresh work" not in str(hint.renderable)
    assert "claude-select relogin work" in str(hint.renderable)


def test_watch_hint_panel_for_expiring_account_mentions_auto_refresh(
    registry, fake_auth_backend, fake_usage_provider
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.list_accounts = lambda include_usage=False: [  # type: ignore[method-assign]
        {
            "alias": "work",
            "auth_kind": "cli",
            "kind_label": "cli",
            "status": "expiring_soon",
        }
    ]

    hint = cli._build_watch_hint_panel(manager)

    assert hint is not None
    assert "No manual refresh is needed yet." in str(hint.renderable)
    assert "claude-select refresh work" not in str(hint.renderable)
    assert "claude-select watch --auto-refresh" in str(hint.renderable)


def test_watch_hint_panel_for_expiring_account_with_auto_refresh(
    registry, fake_auth_backend, fake_usage_provider
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.list_accounts = lambda include_usage=False: [  # type: ignore[method-assign]
        {
            "alias": "work",
            "auth_kind": "cli",
            "kind_label": "cli",
            "status": "expiring_soon",
        }
    ]

    hint = cli._build_watch_hint_panel(manager, auto_refresh=True)

    assert hint is not None
    assert "before expiry" in str(hint.renderable)


def test_watch_sleep_seconds_stays_on_requested_interval():
    rows = [
        {
            "alias": "work",
            "auth_kind": "cli_snapshot",
            "kind_label": "cli",
            "expires_at": 1_700_000_030_000,
        }
    ]

    assert cli._watch_sleep_seconds(rows, interval=30, auto_refresh=True) == 30
    assert cli._watch_sleep_seconds(rows, interval=30, auto_refresh=False) == 30


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


def test_confirm_current_auth_status_accepts(
    capsys, registry, fake_auth_backend, fake_usage_provider, monkeypatch
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")

    cli._confirm_current_auth_status(manager, alias="work", action="capture")

    output = capsys.readouterr().out
    assert "Current Claude auth status:" in output
    assert "email: work@example.com" in output
    assert "organization: Example Org" in output


def test_confirm_current_auth_status_skips_matching_relogin_prompt(
    capsys, registry, fake_auth_backend, fake_usage_provider, monkeypatch
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")

    def unexpected_input(_prompt=""):
        raise AssertionError("input should not be called for matching relogin")

    monkeypatch.setattr("builtins.input", unexpected_input)

    cli._confirm_current_auth_status(manager, alias="work", action="relogin")

    output = capsys.readouterr().out
    assert output == ""


def test_confirm_current_auth_status_rejects(
    registry, fake_auth_backend, fake_usage_provider, monkeypatch
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": "n")

    with pytest.raises(ClaudeSelectError):
        cli._confirm_current_auth_status(manager, alias="work", action="capture")


def test_confirm_current_auth_status_still_prompts_for_mismatched_relogin(
    capsys, registry, fake_auth_backend, fake_usage_provider, monkeypatch
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    fake_auth_backend.auth_status_payload["email"] = "other@example.com"
    fake_auth_backend.auth_status_payload["orgName"] = "Other Org"
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")

    cli._confirm_current_auth_status(manager, alias="work", action="relogin")

    output = capsys.readouterr().out
    assert "Current Claude auth status:" in output
    assert "email: other@example.com" in output


def test_cli_refresh(monkeypatch, capsys, registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    account = manager.capture_current_account("work")
    monkeypatch.setattr(cli, "AuthManager", lambda: manager)
    manager.registry.upsert_account(
        alias="work",
        auth_kind=account["auth_kind"],
        email=account["email"],
        organization_name=account["organization_name"],
        organization_id=account["organization_id"],
        account_uuid=account["account_uuid"],
        captured_at=account["captured_at"],
        expires_at=0,
        last_selected_at=account["last_selected_at"],
        source=account["source"],
        snapshot=manager.get_account("work").snapshot,
        last_synced_at=account["last_synced_at"],
    )

    assert cli.main(["refresh", "work"]) == 0

    output = capsys.readouterr().out
    assert "Refreshing work..." in output
    assert "[1/4] Activating target account in Claude live auth state..." in output
    assert "[2/4] Running `claude -p 'ping'` to trigger Claude-side refresh..." in output
    assert "[3/4] Syncing refreshed live auth state back into the registry..." in output
    assert "[4/4]" in output
    assert "Refreshed work via `claude -p`." in output
    assert "Probe output: pong" in output
    assert fake_auth_backend.print_prompts == ["ping"]


def test_cli_refresh_without_targets(
    monkeypatch, capsys, registry, fake_auth_backend, fake_usage_provider
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    monkeypatch.setattr(cli, "AuthManager", lambda: manager)

    assert cli.main(["refresh"]) == 0

    output = capsys.readouterr().out
    assert "No CLI accounts currently need refresh." in output


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


def test_cli_version(capsys):
    try:
        cli.main(["--version"])
    except SystemExit as exc:
        assert exc.code == 0

    output = capsys.readouterr().out
    assert output.startswith("claude-select ")

    try:
        cli.main(["-V"])
    except SystemExit as exc:
        assert exc.code == 0

    output = capsys.readouterr().out
    assert output.startswith("claude-select ")


def test_cli_version_subcommand(capsys):
    assert cli.main(["version"]) == 0
    assert cli.main(["v"]) == 0

    output = capsys.readouterr().out
    lines = [line for line in output.splitlines() if line.strip()]
    assert len(lines) == 2
    assert all(line.startswith("claude-select ") for line in lines)


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
    assert "auth method: claude.ai" in output
    assert manager.get_account("work").record.expires_at == 4102448400000

    assert cli.main(["whoami", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["matched_alias"] == "work"
    assert payload["quota_5h_left"] == "76.0%"
    assert payload["auth_method"] == "claude.ai"


def test_cli_command_aliases(monkeypatch, capsys, registry, fake_auth_backend, fake_usage_provider):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )
    manager.capture_current_account("work")
    monkeypatch.setattr(cli, "AuthManager", lambda: manager)

    assert cli.main(["ls"]) == 0
    assert cli.main(["use", "work"]) == 0
    assert cli.main(["cur"]) == 0
    assert cli.main(["sync"]) == 0
    assert cli.main(["rm", "work"]) == 0

    output = capsys.readouterr().out
    assert "work@example.com" in output
    assert "Selected work <work@example.com> [Example Org]." in output
    assert "work" in output
    assert "Removed work." in output


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


def test_wait_for_login_and_choose_alias_edge_cases(
    monkeypatch, capsys, registry, fake_auth_backend, fake_usage_provider
):
    manager = AuthManager(
        registry=registry,
        auth_backend=fake_auth_backend,
        usage_provider=fake_usage_provider,
    )

    with pytest.raises(ClaudeSelectError):
        manager.choose_alias_interactively()

    original_run_auth_login = fake_auth_backend.run_auth_login

    def run_auth_login_with_new_credentials():
        result = original_run_auth_login()
        fake_auth_backend.snapshot.credentials["claudeAiOauth"]["accessToken"] = "access-2"
        return result

    monkeypatch.setattr(fake_auth_backend, "run_auth_login", run_auth_login_with_new_credentials)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")
    manager.wait_for_login(True)
    manager.wait_for_login(False)
    assert fake_auth_backend.login_attempts == 1

    manager.add_token_account("work-sdk", "token", email="sdk@example.com")
    monkeypatch.setattr("builtins.input", lambda _prompt="": "work-sdk")
    with pytest.raises(ClaudeSelectError):
        manager.choose_alias_interactively()

    text = capsys.readouterr().out
    assert "Launching `claude auth login` in this terminal." in text
    assert "Run `claude auth login` in another shell" in text


def test_cli_export_env_plain_and_setup_token_guidance(monkeypatch, capsys):
    monkeypatch.setattr(cli.shutil, "which", lambda _name: None)

    cli._run_setup_token(False)
    cli._run_setup_token(True)

    output = capsys.readouterr().out
    assert "Run `claude setup-token`, copy the token, then return here." in output
    assert "`claude` was not found in PATH." in output
