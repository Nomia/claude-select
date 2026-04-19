"""Command line interface for claude-switch."""

from __future__ import annotations

import argparse
import json
import sys

from claude_switch.exceptions import ClaudeSwitchError
from claude_switch.manager import ProfileManager


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser."""
    parser = argparse.ArgumentParser(description="Manage multiple Claude auth profiles.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture = subparsers.add_parser("capture", help="Capture the current Claude CLI login state.")
    capture.add_argument("profile")

    sync = subparsers.add_parser(
        "sync",
        help="Sync a stored profile from the current Claude CLI login state.",
    )
    sync.add_argument("profile", nargs="?")

    list_cmd = subparsers.add_parser("list", help="List stored profiles.")
    list_cmd.add_argument("--json", action="store_true", dest="as_json")

    current = subparsers.add_parser("current", help="Show current CLI and default SDK profiles.")
    current.add_argument("--json", action="store_true", dest="as_json")

    use = subparsers.add_parser("use", help="Switch Claude CLI live state to a profile.")
    use.add_argument("profile")

    remove = subparsers.add_parser("remove", help="Remove a stored profile.")
    remove.add_argument("profile")

    set_default = subparsers.add_parser("set-default-sdk", help="Set the default SDK profile.")
    set_default.add_argument("profile")

    inspect = subparsers.add_parser("inspect", help="Inspect one stored profile.")
    inspect.add_argument("profile")
    inspect.add_argument("--json", action="store_true", dest="as_json")

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)
    manager = ProfileManager()

    try:
        if args.command == "capture":
            result = manager.capture_cli_profile(args.profile)
            print(f"Captured profile '{result['id']}' for {result['email']}.")
            return 0
        if args.command == "sync":
            result = manager.sync_cli_profile(args.profile)
            print(f"Synchronized profile '{result['id']}'.")
            return 0
        if args.command == "list":
            profiles = manager.list_profiles()
            if args.as_json:
                print(json.dumps(profiles, indent=2, sort_keys=True))
            else:
                for profile in profiles:
                    print(
                        f"{profile['id']}\t{profile['email']}\t{profile['auth_state']}\t"
                        f"{profile['organization_name'] or '-'}"
                    )
            return 0
        if args.command == "current":
            payload = {
                "current_cli_profile": manager.get_current_cli_profile(),
                "default_sdk_profile": manager.get_default_sdk_profile(),
            }
            if args.as_json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(f"current_cli_profile={payload['current_cli_profile']}")
                print(f"default_sdk_profile={payload['default_sdk_profile']}")
            return 0
        if args.command == "use":
            result = manager.switch_cli(args.profile)
            print(f"Switched CLI to profile '{result['id']}'.")
            if result.get("refresh_error"):
                print(
                    f"Profile requires reauthentication: {result['refresh_error']}",
                    file=sys.stderr,
                )
            return 0
        if args.command == "remove":
            manager.remove_profile(args.profile)
            print(f"Removed profile '{args.profile}'.")
            return 0
        if args.command == "set-default-sdk":
            manager.set_default_sdk_profile(args.profile)
            print(f"Default SDK profile set to '{args.profile}'.")
            return 0
        if args.command == "inspect":
            profile = manager.inspect_profile(args.profile)
            if args.as_json:
                print(json.dumps(profile, indent=2, sort_keys=True))
            else:
                print(json.dumps(profile, indent=2, sort_keys=True))
            return 0
    except ClaudeSwitchError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    parser.error(f"Unhandled command: {args.command}")
    return 2
