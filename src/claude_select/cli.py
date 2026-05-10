"""Command line interface for claude-select."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

from claude_select.exceptions import ClaudeSelectError
from claude_select.manager import AuthManager


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser."""
    parser = argparse.ArgumentParser(
        description="Manage multiple Claude auth snapshots for CLI and SDK usage."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Interactively capture multiple Claude accounts.")
    init.add_argument("--launch", action="store_true", help="Launch `claude` before each capture.")

    add = subparsers.add_parser("add", help="Capture the current Claude account into the registry.")
    add.add_argument("alias", nargs="?")
    add.add_argument("--launch", action="store_true", help="Launch `claude` before capture.")

    relogin = subparsers.add_parser(
        "relogin",
        help="Refresh an existing alias by asking the user to log in again.",
    )
    relogin.add_argument("alias")
    relogin.add_argument("--launch", action="store_true", help="Launch `claude` before capture.")

    subparsers.add_parser("list", help="List stored accounts.")

    watch = subparsers.add_parser("watch", help="Continuously refresh the account table.")
    watch.add_argument("--interval", type=int, default=30)
    watch.add_argument("--iterations", type=int, default=0)

    select = subparsers.add_parser(
        "select",
        help="Select an account from the registry and write it into Claude's live auth state.",
    )
    select.add_argument("alias", nargs="?")

    remove = subparsers.add_parser("remove", help="Delete an account from the registry.")
    remove.add_argument("alias")

    export_env = subparsers.add_parser(
        "export-env",
        help="Return env vars for Claude Agent SDK consumption.",
    )
    export_env.add_argument("alias")
    export_env.add_argument("--json", action="store_true", dest="as_json")

    current = subparsers.add_parser("current", help="Show the last CLI-selected alias.")
    current.add_argument("--json", action="store_true", dest="as_json")

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
            print(f"Captured {account['alias']} <{account['email']}>.")
            return 0
        if args.command == "relogin":
            manager.wait_for_login(args.launch)
            account = manager.relogin_account(args.alias)
            print(f"Updated {account['alias']} <{account['email']}>.")
            return 0
        if args.command == "list":
            print(manager.render_table())
            return 0
        if args.command == "watch":
            return _run_watch(manager, args.interval, args.iterations)
        if args.command == "select":
            alias = args.alias or manager.choose_alias_interactively()
            account = manager.select_account(alias)
            print(f"Selected {account['alias']} <{account['email']}>.")
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
        print(f"Captured {account['alias']} <{account['email']}>.")
        if input("Add another account? [Y/n] ").strip().lower() in {"n", "no"}:
            break
    print()
    print(manager.render_table())
    return 0


def _run_watch(manager: AuthManager, interval: int, iterations: int) -> int:
    """Render the account table repeatedly."""
    count = 0
    while True:
        if os.environ.get("TERM"):
            print("\033[2J\033[H", end="")
        print(manager.render_table())
        count += 1
        if iterations and count >= iterations:
            return 0
        time.sleep(max(interval, 1))
