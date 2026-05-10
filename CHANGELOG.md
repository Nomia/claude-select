# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project follows Semantic Versioning.

## [Unreleased]

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
