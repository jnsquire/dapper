"""Global configuration management for Dapper debug adapter.

This module provides centralized configuration management with thread-safe
access and configuration validation.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    import types

from dapper.config.dapper_config import DEFAULT_CONFIG
from dapper.config.dapper_config import DapperConfig

# Thread-safe global configuration state
_config_lock = threading.RLock()
_current_config: DapperConfig = DEFAULT_CONFIG


def get_config() -> DapperConfig:
    """Get the current configuration in a thread-safe manner.

    Returns:
        The current DapperConfig instance
    """
    with _config_lock:
        return _current_config


def set_config(config: DapperConfig) -> None:
    """Set the current configuration in a thread-safe manner.

    Args:
        config: The new configuration to set
    """
    global _current_config
    with _config_lock:
        config.validate()
        _current_config = config


def update_config(**kwargs: Any) -> None:
    """Update the current configuration with new values.

    Args:
        **kwargs: Configuration values to update
    """
    global _current_config
    with _config_lock:
        # Create new config with updated values
        current = get_config()

        # Update specific fields based on kwargs
        if "log_level" in kwargs:
            current.log_level = kwargs["log_level"]
        if "enable_metrics" in kwargs:
            current.enable_metrics = kwargs["enable_metrics"]
        if "timeout_seconds" in kwargs:
            current.timeout_seconds = kwargs["timeout_seconds"]

        # Validate and set
        current.validate()
        _current_config = current


def reset_config() -> None:
    """Reset configuration to defaults."""
    global _current_config
    with _config_lock:
        _current_config = DEFAULT_CONFIG


class ConfigContext:
    """Context manager for temporary configuration changes.

    This allows for temporary configuration modifications that are
    automatically reverted when the context exits.
    """

    def __init__(self, **kwargs: Any):
        """Initialize with configuration changes to apply.

        Args:
            **kwargs: Configuration values to temporarily modify
        """
        self._changes = kwargs
        self._original_config: DapperConfig | None = None

    def __enter__(self) -> DapperConfig:
        """Apply temporary configuration changes."""
        global _current_config
        with _config_lock:
            self._original_config = get_config()

            # Create modified config
            new_config = DapperConfig(
                mode=self._original_config.mode,
                in_process=self._original_config.in_process,
                ipc=self._original_config.ipc,
                debuggee=self._original_config.debuggee,
                log_level=self._changes.get("log_level", self._original_config.log_level),
                enable_metrics=self._changes.get(
                    "enable_metrics", self._original_config.enable_metrics
                ),
                timeout_seconds=self._changes.get(
                    "timeout_seconds", self._original_config.timeout_seconds
                ),
            )

            # Apply changes
            for key, value in self._changes.items():
                if hasattr(new_config, key):
                    setattr(new_config, key, value)

            new_config.validate()
            _current_config = new_config
            return new_config

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Restore original configuration."""
        global _current_config
        if self._original_config is not None:
            with _config_lock:
                _current_config = self._original_config
