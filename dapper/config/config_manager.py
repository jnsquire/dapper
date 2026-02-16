"""Global configuration management for Dapper debug adapter.

This module provides centralized configuration management with thread-safe
access and configuration validation.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    import types

from dapper.config.dapper_config import DEFAULT_CONFIG
from dapper.config.dapper_config import DapperConfig

logger = logging.getLogger(__name__)


class ConfigManager:
    """Thread-safe manager for process-wide configuration state."""

    def __init__(self, default_config: DapperConfig) -> None:
        self._lock = threading.RLock()
        self._default_config = default_config
        self._current_config = default_config

    def _assign_current_config(self, value: DapperConfig) -> None:
        self._current_config = value

    def get_config(self) -> DapperConfig:
        """Get the current configuration in a thread-safe manner."""
        with self._lock:
            return self._current_config

    def set_config(self, config: DapperConfig) -> None:
        """Set the current configuration in a thread-safe manner."""
        with self._lock:
            config.validate()
            self._assign_current_config(config)

    def update_config(self, **kwargs: Any) -> None:
        """Update the current configuration with new values."""
        with self._lock:
            current = self.get_config()

            allowed_keys = {"log_level", "enable_metrics", "timeout_seconds"}
            unknown_keys = sorted(set(kwargs) - allowed_keys)
            if unknown_keys:
                logger.warning("Ignoring unknown config key(s): %s", ", ".join(unknown_keys))

            if "log_level" in kwargs:
                current.log_level = kwargs["log_level"]
            if "enable_metrics" in kwargs:
                current.enable_metrics = kwargs["enable_metrics"]
            if "timeout_seconds" in kwargs:
                current.timeout_seconds = kwargs["timeout_seconds"]

            current.validate()
            self._assign_current_config(current)

    def reset_config(self) -> None:
        """Reset configuration to defaults."""
        with self._lock:
            self._assign_current_config(self._default_config)

    def apply_context_changes(self, changes: dict[str, Any]) -> tuple[DapperConfig, DapperConfig]:
        """Apply temporary configuration changes atomically.

        Returns:
            Tuple of (original_config, new_config).
        """
        with self._lock:
            original = self._current_config

            new_config = DapperConfig(
                mode=original.mode,
                in_process=original.in_process,
                ipc=original.ipc,
                debuggee=original.debuggee,
                log_level=changes.get("log_level", original.log_level),
                enable_metrics=changes.get("enable_metrics", original.enable_metrics),
                timeout_seconds=changes.get("timeout_seconds", original.timeout_seconds),
            )

            for key, value in changes.items():
                if hasattr(new_config, key):
                    setattr(new_config, key, value)

            new_config.validate()
            self._assign_current_config(new_config)
            return original, new_config

    def restore_config(self, config: DapperConfig) -> None:
        """Restore a previously captured configuration."""
        with self._lock:
            self._assign_current_config(config)

    def create_context(self, **kwargs: Any) -> ConfigContext:
        """Create a context manager for temporary configuration changes."""
        return ConfigContext(**kwargs)


_config_manager = ConfigManager(DEFAULT_CONFIG)


def get_config() -> DapperConfig:
    """Get the current configuration in a thread-safe manner.

    Returns:
        The current DapperConfig instance
    """
    return _config_manager.get_config()


def set_config(config: DapperConfig) -> None:
    """Set the current configuration in a thread-safe manner.

    Args:
        config: The new configuration to set
    """
    _config_manager.set_config(config)


def update_config(**kwargs: Any) -> None:
    """Update the current configuration with new values.

    Args:
        **kwargs: Configuration values to update
    """
    _config_manager.update_config(**kwargs)


def reset_config() -> None:
    """Reset configuration to defaults."""
    _config_manager.reset_config()


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
        self._manager = _config_manager
        self._changes = kwargs
        self._original_config: DapperConfig | None = None

    def __enter__(self) -> DapperConfig:
        """Apply temporary configuration changes."""
        self._original_config, new_config = self._manager.apply_context_changes(self._changes)
        return new_config

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Restore original configuration."""
        if self._original_config is not None:
            self._manager.restore_config(self._original_config)


def config_context(**kwargs: Any) -> ConfigContext:
    """Create a context manager for temporary configuration changes."""
    return _config_manager.create_context(**kwargs)
