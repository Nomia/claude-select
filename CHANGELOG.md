# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project follows Semantic Versioning.

## [Unreleased]

## [0.4.0] - 2026-05-12

### Added

- Added `--version` to the CLI.
- Improved `add-token` terminal capture to support wrapped `claude setup-token` output lines.

### Changed

- Repositioned long-lived `add-token` entries as simple SDK/program credentials only.
- Removed quota-aware SDK token auto-selection from the supported feature set; compatibility helpers now raise `AccountSelectionError`.
- `list --usage`, Python quota APIs, and watch-style quota views now report `n/a` / unsupported for `token` entries instead of pretending quota is available.
- Improved `add-token` probing so scope-limited inference tokens are treated as valid SDK credentials even when profile metadata cannot be read.
- Rewrote English and Chinese README / Python SDK docs around the simplified model: `cli` entries are fully managed, `token` entries are explicit SDK credentials.

## [0.3.1] - 2026-05-12

### Added

- Added best-effort token capture from `claude setup-token` terminal output plus immediate token probing during `add-token`.

### Changed

- `add-token` now tries to validate the long-lived token and auto-resolve email/organization metadata before falling back to manual prompts.
- Clarified English and Chinese README / Python SDK docs around SDK auto token selection, including the exact trigger point before each Claude Agent SDK call.

## [0.3.0] - 2026-05-12

### Added

- Added quota-aware SDK token orchestration with `pick_sdk_account()` and `build_sdk_env_auto()`.
- Added support for long-lived SDK/program tokens through `add-token` and the `init` token setup phase.
- Added current live-state sync flows through `sync-current`, plus automatic light sync in `list`, `whoami`, and periodic sync in `watch`.
- Added a generated overview architecture image and refreshed English/Chinese README diagrams and examples.

### Changed

- Split registry entries into `cli` and `token` kinds so CLI selection and SDK token usage have separate lifecycle rules.
- Expanded CLI feedback after capture/update to show status, expiry, and the current registry state.
- Enriched `list`, `watch`, `whoami`, and Python SDK quota APIs with current usage and selection context.

## [0.2.1] - 2026-05-11

### Changed

- Made `init`, `add`, and `relogin` launch `claude` in the current terminal by default.
- Replaced the old `--launch` opt-in with `--no-launch` opt-out behavior.
- Updated the English and Chinese README files to describe the current-terminal login flow and fallback guidance.

## [0.2.0] - 2026-05-11

### Changed

- Replaced the original profile-switch architecture with a local auth-registry model.
- Switched the CLI to account capture, relogin, list, watch, select, remove, and SDK env export flows.
- Switched Python integration from profile switching helpers to `AuthManager` plus snapshot-based SDK env generation.
- Removed automatic refresh behavior and now rely on stored `expiresAt` plus explicit relogin.

### Added

- SQLite-backed local account registry.
- Claude live-state read/write backend for selecting a stored account back into the active CLI auth state.
- New unit tests for registry, manager, CLI, live-state handling, locking, models, and module entrypoint.
- Rewritten English and Chinese README files around the new product model.

### Removed

- Old `oauth.py` refresh-oriented implementation.
- Old profile-centric tests and documentation.

## [0.1.0] - 2026-05-10

### Added

- Initial public release.
