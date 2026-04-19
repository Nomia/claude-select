"""Project-specific exceptions."""


class ClaudeSwitchError(Exception):
    """Base error for the package."""


class ConfigError(ClaudeSwitchError):
    """Raised when local Claude configuration is invalid or missing."""


class ProfileNotFoundError(ClaudeSwitchError):
    """Raised when a named profile does not exist."""


class ProfileValidationError(ClaudeSwitchError):
    """Raised when profile input is invalid."""


class ProfileReauthRequired(ClaudeSwitchError):
    """Raised when a profile requires the user to login again."""


class OAuthRefreshError(ClaudeSwitchError):
    """Raised when an OAuth token refresh fails."""


class LockTimeoutError(ClaudeSwitchError):
    """Raised when a store lock cannot be acquired."""
