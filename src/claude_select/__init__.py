"""Public package interface for claude-select."""

from claude_select.manager import AuthManager, build_sdk_env, build_sdk_env_auto

__all__ = ["AuthManager", "build_sdk_env", "build_sdk_env_auto"]
