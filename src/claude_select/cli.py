"""Command line interface for claude-select."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from claude_select.exceptions import ClaudeSelectError
from claude_select.manager import AuthManager

TOKEN_RE = re.compile(r"(sk-ant-oat[0-9A-Za-z._-]+)")


def _account_display(manager: AuthManager, account: dict[str, Any]) -> str:
    """Render one account for success messages."""
    return manager.format_account_label(account)


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser."""
    parser = argparse.ArgumentParser(
        prog="claude-select",
        description="Manage multiple Claude auth snapshots for CLI and SDK usage.",
        epilog=(
            "Typical flow:\n"
            "  1. claude-select init\n"
            "  2. claude-select list\n"
            "  3. claude-select select work\n"
            "  4. Use AuthManager().build_sdk_env('work') in Python"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_package_version()}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser(
        "init",
        help="Bootstrap multiple Claude accounts interactively.",
        description=(
            "Capture multiple Claude CLI login snapshots into the local registry.\n"
            "By default, this command launches `claude` in the current terminal for\n"
            "each account so the user can run `/login` immediately."
        ),
        epilog="Examples:\n  claude-select init\n  claude-select init --no-launch",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    init.add_argument(
        "--no-launch",
        action="store_false",
        dest="launch",
        help="Do not launch `claude` automatically before each capture.",
    )
    init.set_defaults(launch=True)

    add = subparsers.add_parser(
        "add",
        help="Capture one Claude account into the local registry.",
        description=(
            "Capture the current Claude CLI login snapshot under one alias.\n"
            "By default, this command launches `claude` in the current terminal\n"
            "before waiting for the login to complete."
        ),
        epilog="Examples:\n  claude-select add work\n  claude-select add personal --no-launch",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add.add_argument("alias", nargs="?", help="Alias to store, for example `work` or `personal`.")
    add.add_argument(
        "--no-launch",
        action="store_false",
        dest="launch",
        help="Do not launch `claude` automatically before capture.",
    )
    add.set_defaults(launch=True)

    add_token = subparsers.add_parser(
        "add-token",
        help="Capture a long-lived token for SDK and program use.",
        description=(
            "Guide the user through `claude setup-token`, then store the resulting\n"
            "long-lived token under one alias for SDK/program usage."
        ),
        epilog=(
            "Examples:\n"
            "  claude-select add-token work-sdk\n"
            "  claude-select add-token local-bot --no-launch"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_token.add_argument(
        "alias",
        nargs="?",
        help="Alias to store for this long-lived token.",
    )
    add_token.add_argument(
        "--no-launch",
        action="store_false",
        dest="launch",
        help="Do not launch `claude setup-token` automatically before prompting for the token.",
    )
    add_token.set_defaults(launch=True)

    relogin = subparsers.add_parser(
        "relogin",
        help="Recapture an existing alias after the user logs in again.",
        description=(
            "Overwrite one stored account with a newly captured Claude CLI login snapshot.\n"
            "Use this when an account is expired or close to expiry."
        ),
        epilog=(
            "Examples:\n"
            "  claude-select relogin work\n"
            "  claude-select relogin personal --no-launch"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    relogin.add_argument("alias", help="Existing alias to overwrite.")
    relogin.add_argument(
        "--no-launch",
        action="store_false",
        dest="launch",
        help="Do not launch `claude` automatically before capture.",
    )
    relogin.set_defaults(launch=True)

    subparsers.add_parser(
        "list",
        help="Show all stored accounts as a table.",
        description="List the local auth registry with status, expiry, and last-selected time.",
    ).add_argument(
        "--usage",
        action="store_true",
        help="Fetch and display 5h/7d quota usage for each stored alias.",
    )

    watch = subparsers.add_parser(
        "watch",
        help="Continuously redraw the account table.",
        description="Refresh the registry table on an interval until interrupted.",
    )
    watch.add_argument("--interval", type=int, default=30, help="Refresh interval in seconds.")
    watch.add_argument(
        "--sync-interval",
        type=int,
        default=60,
        help="How often to sync the current Claude live auth state back into the registry.",
    )
    watch.add_argument(
        "--iterations",
        type=int,
        default=0,
        help="Number of refresh cycles before exiting. Use 0 to run until interrupted.",
    )

    select = subparsers.add_parser(
        "select",
        help="Write one stored account back into Claude's live auth state.",
        description=(
            "Select one stored alias and copy its auth snapshot into Claude's current\n"
            "live auth backend. On macOS this updates Keychain-backed credentials;\n"
            "on Linux and Windows this updates Claude's file-backed credentials."
        ),
        epilog="Examples:\n  claude-select select work\n  claude-select select",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    select.add_argument(
        "alias",
        nargs="?",
        help="Alias to select. If omitted, claude-select prompts interactively.",
    )

    remove = subparsers.add_parser(
        "remove",
        help="Delete one stored account.",
        description="Remove one alias and its captured auth snapshot from the local registry.",
    )
    remove.add_argument("alias", help="Alias to delete.")

    export_env = subparsers.add_parser(
        "export-env",
        help="Print environment variables for Claude Agent SDK usage.",
        description=(
            "Read one stored account from the local registry and print the environment\n"
            "variables needed for Claude Agent SDK usage."
        ),
        epilog="Examples:\n  claude-select export-env work\n  claude-select export-env work --json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    export_env.add_argument("alias", help="Alias to export for SDK usage.")
    export_env.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Print a JSON object instead of KEY=value lines.",
    )

    current = subparsers.add_parser(
        "current",
        help="Show the last alias selected for CLI usage.",
        description="Print the last alias selected with `claude-select select`.",
    )
    current.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Print a JSON object instead of plain text.",
    )

    whoami = subparsers.add_parser(
        "whoami",
        help="Show the current Claude live auth state.",
        description=(
            "Read Claude's current live auth state from its active config and credential backend,\n"
            "then display the current email, organization, expiry, and best-effort matched alias."
        ),
    )
    whoami.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Print a JSON object instead of plain text.",
    )

    sync_current = subparsers.add_parser(
        "sync-current",
        help="Sync the current Claude live auth state back into the local registry.",
        description=(
            "Read Claude's current live auth state, match it against the local registry,\n"
            "and update the matching stored alias when the live snapshot has changed."
        ),
    )
    sync_current.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Print a JSON object instead of plain text.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)
    manager = AuthManager()

    try:
        if args.command == "init":
            return _run_init(manager, launch=args.launch)
        if args.command == "add":
            alias = args.alias or input("Alias: ").strip()
            manager.wait_for_login(args.launch)
            account = manager.capture_current_account(alias, overwrite=True)
            _print_capture_feedback(manager, account, verb="Captured")
            return 0
        if args.command == "add-token":
            alias = args.alias or input("Alias: ").strip()
            token_payload = _prompt_for_token_capture(manager, launch=args.launch)
            account = manager.add_token_account(alias, **token_payload, overwrite=True)
            _print_capture_feedback(manager, account, verb="Captured")
            return 0
        if args.command == "relogin":
            manager.wait_for_login(args.launch)
            account = manager.relogin_account(args.alias)
            _print_capture_feedback(manager, account, verb="Updated")
            return 0
        if args.command == "list":
            _best_effort_sync_current(manager)
            print(manager.render_table(include_usage=args.usage))
            return 0
        if args.command == "watch":
            return _run_watch(manager, args.interval, args.sync_interval, args.iterations)
        if args.command == "select":
            alias = args.alias or manager.choose_alias_interactively()
            account = manager.select_account(alias)
            print(f"Selected {_account_display(manager, account)}.")
            print("Updated Claude live auth state:")
            for target in manager.auth_backend.describe_targets():
                print(f"  - {target}")
            print(f"Current CLI alias: {account['alias']}")
            return 0
        if args.command == "remove":
            manager.remove_account(args.alias)
            print(f"Removed {args.alias}.")
            return 0
        if args.command == "export-env":
            env = manager.build_sdk_env(args.alias, base_env={})
            if args.as_json:
                print(json.dumps(env, indent=2, sort_keys=True))
            else:
                for key, value in sorted(env.items()):
                    print(f"{key}={value}")
            return 0
        if args.command == "current":
            payload: dict[str, Any] = {"current_alias": manager.current_alias()}
            if args.as_json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(payload["current_alias"] or "None")
            return 0
        if args.command == "whoami":
            _best_effort_sync_current(manager)
            payload = manager.current_live_account()
            if args.as_json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(manager.render_current_live_account())
            return 0
        if args.command == "sync-current":
            payload = manager.sync_current_account()
            if args.as_json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(payload["message"])
                if payload.get("record"):
                    print()
                    print("Current registry:")
                    print(manager.render_table())
            return 0
    except ClaudeSelectError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 2


def _run_init(manager: AuthManager, *, launch: bool) -> int:
    """Interactive multi-account bootstrap."""
    print("Claude account bootstrap")
    print("Add accounts one by one. Complete /login for each account before capture.")
    while True:
        alias = input("Alias (blank to finish): ").strip()
        if not alias:
            break
        manager.wait_for_login(launch)
        account = manager.capture_current_account(alias, overwrite=True)
        _print_capture_feedback(manager, account, verb="Captured")
        if input("Add another account? [Y/n] ").strip().lower() in {"n", "no"}:
            break
    if input("Add a long-lived token for SDK/program use? [y/N] ").strip().lower() in {"y", "yes"}:
        while True:
            alias = input("Token alias (blank to finish): ").strip()
            if not alias:
                break
            token_payload = _prompt_for_token_capture(manager, launch=launch)
            account = manager.add_token_account(alias, **token_payload, overwrite=True)
            _print_capture_feedback(manager, account, verb="Captured")
            if input("Add another token? [Y/n] ").strip().lower() in {"n", "no"}:
                break
    print()
    print(manager.render_table())
    return 0


def _print_capture_feedback(manager: AuthManager, account: dict[str, Any], *, verb: str) -> None:
    """Print a stronger success summary after capture-like actions."""
    print(f"{verb} {_account_display(manager, account)}.")
    print(f"Status: {account['status']}")
    print(f"Expires in: {account['expires_in']}")
    print()
    print("Current registry:")
    print(manager.render_table())


def _best_effort_sync_current(manager: AuthManager) -> dict[str, Any] | None:
    """Try to sync the current live auth state without breaking read-only commands."""
    try:
        return manager.sync_current_account()
    except ClaudeSelectError:
        return None


def _prompt_for_token_capture(manager: AuthManager, *, launch: bool) -> dict[str, str]:
    """Guide the user through setup-token and collect token metadata."""
    setup_output = _run_setup_token(launch)
    token = _extract_token_from_output(setup_output)
    if token:
        print("Detected the long-lived token from setup-token output.")
    else:
        token = input("Paste the long-lived token: ").strip()

    probe = manager.probe_token(token)
    if probe["valid"]:
        print("Validated token for SDK/program use.")
        if probe.get("warning"):
            print(probe["warning"])
    else:
        print("Could not validate the token automatically.")
        if probe["error"]:
            print(f"Reason: {probe['error']}")

    resolved = dict(probe["metadata"])
    if resolved:
        print("Detected account metadata:")
        print(f"  email: {resolved.get('email', '-') or '-'}")
        print(f"  organization: {resolved.get('organization_name', '-') or '-'}")
    payload = {
        "token": token,
        "email": resolved.get("email", ""),
        "organization_name": resolved.get("organization_name", ""),
        "organization_id": resolved.get("organization_id", ""),
        "account_uuid": resolved.get("account_uuid", ""),
    }
    if not payload["email"]:
        payload["email"] = input("Email: ").strip()
    if not payload["organization_name"]:
        payload["organization_name"] = input("Organization (optional): ").strip()
    return payload


def _run_setup_token(launch: bool) -> str:
    """Guide the user through `claude setup-token`."""
    if launch:
        claude_path = shutil.which("claude")
        if claude_path:
            print("Launching `claude setup-token` in this terminal.")
            print("Complete authorization. When the token is printed, copy it and return here.")
            return _stream_and_capture_command([claude_path, "setup-token"])
        else:
            print("`claude` was not found in PATH.")
            print("Run `claude setup-token`, copy the token, then return here.")
    else:
        print("Run `claude setup-token`, copy the token, then return here.")
    return ""


def _stream_and_capture_command(command: list[str]) -> str:
    """Run one interactive command, echoing output while capturing it."""
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=None,
        text=True,
        bufsize=1,
    )
    output: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="")
        output.append(line)
    process.wait()
    return "".join(output)


def _extract_token_from_output(output: str) -> str | None:
    """Best-effort token extraction from `claude setup-token` terminal output."""
    lines = output.splitlines()
    for index, line in enumerate(lines):
        match = TOKEN_RE.search(line)
        if not match:
            continue
        token = match.group(1)
        follow_index = index + 1
        while follow_index < len(lines):
            chunk = lines[follow_index].strip()
            if not chunk or not re.fullmatch(r"[0-9A-Za-z._-]+", chunk):
                break
            token += chunk
            follow_index += 1
        return token
    return None


def _package_version() -> str:
    """Read the installed package version for --version output."""
    try:
        return version("claude-select")
    except PackageNotFoundError:
        return "unknown"


def _run_watch(manager: AuthManager, interval: int, sync_interval: int, iterations: int) -> int:
    """Render the account table repeatedly with a live terminal view."""
    count = 0
    last_sync_monotonic = 0.0
    console = Console()
    with Live(console=console, auto_refresh=False) as live:
        while True:
            now = time.monotonic()
            if now - last_sync_monotonic >= max(sync_interval, 1):
                _best_effort_sync_current(manager)
                last_sync_monotonic = now
            live.update(_build_watch_renderable(manager), refresh=True)
            count += 1
            if iterations and count >= iterations:
                return 0
            time.sleep(max(interval, 1))


def _build_watch_renderable(manager: AuthManager) -> Group:
    """Build the live watch layout."""
    return Group(
        _build_current_account_panel(manager),
        _build_accounts_table(manager),
    )


def _build_current_account_panel(manager: AuthManager) -> Panel:
    """Render the current Claude live auth state."""
    try:
        current = manager.current_live_account()
    except ClaudeSelectError as exc:
        return Panel(
            f"Current live auth state is unavailable.\n{exc}",
            title="Current Claude live account",
            expand=True,
        )
    lines = [
        f"matched alias: {current['matched_alias'] or '-'}",
        f"email: {current['email'] or '-'}",
        f"organization: {current['organization_name'] or '-'}",
        f"expires in: {current['expires_in']}",
    ]
    for target in current["targets"]:
        lines.append(f"target: {target}")
    return Panel("\n".join(lines), title="Current Claude live account", expand=True)


def _build_accounts_table(manager: AuthManager) -> Table | Panel:
    """Render the local registry as a rich table."""
    rows = manager.list_accounts(include_usage=True)
    if not rows:
        return Panel("No accounts have been captured yet.", title="Registry", expand=True)
    table = Table(title="Local account registry", expand=True)
    table.add_column("Alias")
    table.add_column("Kind")
    table.add_column("Email")
    table.add_column("Organization")
    table.add_column("Status")
    table.add_column("Expires In")
    table.add_column("Last Selected")
    table.add_column("5h Left")
    table.add_column("5h Reset")
    table.add_column("7d Left")
    table.add_column("7d Reset")
    for row in rows:
        table.add_row(
            row["alias"],
            manager._display_auth_kind(row["auth_kind"]),
            row["email"],
            row["organization_name"] or "-",
            row["status"],
            row["expires_in"],
            manager._format_last_selected(row["last_selected_at"]),
            row["quota_5h_left"],
            row["quota_5h_reset"],
            row["quota_7d_left"],
            row["quota_7d_reset"],
        )
    return table
