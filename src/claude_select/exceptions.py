"""Project-specific exceptions for claude-select."""


class ClaudeSelectError(Exception):
    """Base error for the package."""


class ConfigError(ClaudeSelectError):
    """Raised when Claude live auth state is missing or invalid."""


class AccountNotFoundError(ClaudeSelectError):
    """Raised when an alias does not exist in the registry."""


class AccountExistsError(ClaudeSelectError):
    """Raised when an alias already exists and overwrite is not allowed."""


class AccountSelectionError(ClaudeSelectError):
    """Raised when account selection input is invalid."""


class AuthExpiredError(ClaudeSelectError):
    """Raised when a requested account is already expired."""


class LockTimeoutError(ClaudeSelectError):
    """Raised when the registry lock cannot be acquired."""
