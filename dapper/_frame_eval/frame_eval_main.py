"""
Main entry point for Dapper frame evaluation system.

This module provides the primary interface for setting up and configuring
frame evaluation, handling compatibility checks, and managing the overall
frame evaluation lifecycle.
"""

from __future__ import annotations

from enum import Enum
import logging
import os
import platform
import sys
import threading
from typing import TYPE_CHECKING
from typing import Any
from typing import ClassVar

if TYPE_CHECKING:
    # Avoid circular import when the module is first loaded
    from dapper._frame_eval.backend import FrameEvalBackend

from dapper._frame_eval.cache_manager import clear_all_caches
from dapper._frame_eval.cache_manager import configure_caches
from dapper._frame_eval.compatibility_policy import FrameEvalCompatibilityPolicy
from dapper._frame_eval.condition_evaluator import get_condition_evaluator
from dapper._frame_eval.config import FrameEvalConfig
from dapper._frame_eval.modify_bytecode import set_optimization_enabled
from dapper._frame_eval.runtime import FrameEvalRuntime

if TYPE_CHECKING:
    from typing_extensions import Self

    from dapper._frame_eval.tracing_backend import TracingBackend


class FrameEvalManager:
    """
    Manages frame evaluation state and operations.

    This class provides a clean interface for managing frame evaluation state
    and operations, eliminating the need for global variables.
    """

    # Module constants
    COMPATIBLE_PYTHON_VERSIONS: ClassVar[list[str]] = [
        "3.9",
        "3.10",
        "3.11",
        "3.12",
        "3.13",
    ]
    SUPPORTED_PLATFORMS: ClassVar[list[str]] = ["Windows", "Linux", "Darwin"]
    SUPPORTED_ARCHITECTURES: ClassVar[list[str]] = ["64bit", "32bit"]
    INCOMPATIBLE_DEBUGGERS: ClassVar[list[str]] = ["pydevd", "pdb", "ipdb"]
    INCOMPATIBLE_ENVIRONMENT_VARS: ClassVar[list[str]] = ["PYCHARM_HOSTED", "VSCODE_PID"]
    INCOMPATIBLE_COVERAGE_TOOLS: ClassVar[list[str]] = ["coverage", "pytest_cov"]

    # Singleton instance
    _instance: Self | None = None
    _initialization_lock = threading.Lock()

    def __new__(cls) -> Self:
        """Ensure only one instance of FrameEvalManager exists."""
        if cls._instance is None:
            with cls._initialization_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance.initialize()
        return cls._instance

    def initialize(self) -> None:
        """Initialize the frame evaluation manager."""
        self._frame_eval_config = FrameEvalConfig()
        self._compatibility_policy = FrameEvalCompatibilityPolicy(
            min_python=(3, 9),
            max_python=(3, 14),
            supported_platforms=tuple(self.SUPPORTED_PLATFORMS),
            supported_architectures=tuple(self.SUPPORTED_ARCHITECTURES),
            incompatible_debuggers=tuple(self.INCOMPATIBLE_DEBUGGERS),
            incompatible_environment_vars=tuple(self.INCOMPATIBLE_ENVIRONMENT_VARS),
            incompatible_coverage_tools=tuple(self.INCOMPATIBLE_COVERAGE_TOOLS),
        )
        self._is_initialized = False
        self._runtime = FrameEvalRuntime(self._frame_eval_config)
        # The currently active backend, which may be a tracing-based
        # backend or (eventually) an eval-frame backend.  We use the more
        # general ``FrameEvalBackend`` protocol for typing, but because all
        # existing backends subclass ``TracingBackend`` this change is
        # backwards-compatible.
        # ``FrameEvalBackend`` is imported lazily to avoid a circular
        # import during module initialization.  The type-checker needs to see
        # it so we re-import under TYPE_CHECKING at the top of the module.

        self._active_backend: FrameEvalBackend | None = None
        self._compatibility_cache: dict[tuple, dict[str, Any]] = {}
        self._logger = logging.getLogger(__name__)

        # Initialize default configuration
        self._frame_eval_config.enabled = True
        self._frame_eval_config.debug = False
        self._frame_eval_config.optimize = True
        self._frame_eval_config.cache_size = 1000
        self._frame_eval_config.timeout = 30.0

    @property
    def active_backend(self) -> FrameEvalBackend | None:
        """The currently active backend (tracing or eval-frame), or ``None`` if
        none has been created yet."""
        return self._active_backend

    def _create_backend(self, config: FrameEvalConfig) -> FrameEvalBackend:
        """Factory: instantiate the correct backend for *config*.

        Prior to Phase 1, only tracing backends existed.  We now support two
        backend families:

        * ``TRACING`` - the traditional settrace/sys.monitoring path.
        * ``EVAL_FRAME`` - an interpreter hook that may bypass tracing
          entirely.  (Currently only a stub.)

        The ``AUTO`` mode will pick eval-frame when it is reported as
        available by the compatibility policy, falling back to tracing
        otherwise.  Explicit ``TRACING`` or ``EVAL_FRAME`` choices are honored
        unless the requested backend is not supported, in which case the
        fallback is tracing.
        """
        can_use_eval_frame, eval_frame_reason = self._compatibility_policy.can_use_eval_frame(
            version_info=sys.version_info,
            platform_system=platform.system(),
            architecture=platform.architecture()[0],
            implementation=platform.python_implementation(),
            modules=sys.modules,
            environ=os.environ,
        )

        # Local aliases for readability
        bk = FrameEvalConfig.BackendKind

        # Choose helper according to backend field
        if config.backend is bk.AUTO:
            if can_use_eval_frame:
                try:
                    return self._create_eval_frame_backend(config)
                except Exception:
                    # if creation fails for some reason, fall through
                    self._logger.warning(
                        "Eval-frame backend requested but failed to initialize; falling back to tracing",
                    )
            elif eval_frame_reason:
                self._logger.info(
                    "Eval-frame AUTO selection fell back to tracing: %s",
                    eval_frame_reason,
                )
            # default to tracing
            return self._create_tracing_backend(config)

        if config.backend is bk.EVAL_FRAME:
            if can_use_eval_frame:
                try:
                    return self._create_eval_frame_backend(config)
                except Exception:
                    self._logger.warning(
                        "Eval-frame backend requested but failed to initialize; falling back to tracing",
                    )
                    if not config.fallback_to_tracing:
                        raise RuntimeError(
                            "Eval-frame backend initialization failed and tracing fallback is disabled",
                        ) from None
            else:
                if not config.fallback_to_tracing:
                    message = (
                        "Eval-frame backend explicitly requested but unavailable: "
                        f"{eval_frame_reason}"
                    )
                    raise RuntimeError(
                        message,
                    )
                self._logger.warning(
                    "Eval-frame backend explicitly requested but unavailable; using tracing instead: %s",
                    eval_frame_reason,
                )
            return self._create_tracing_backend(config)

        # TRACING or any other value
        return self._create_tracing_backend(config)

    def _create_tracing_backend(self, config: FrameEvalConfig) -> TracingBackend:
        """Instantiate the appropriate tracing backend.  Extracted from the
        original ``_create_backend`` implementation to keep the new logic
        cleaner.
        """
        kind = config.tracing_backend
        backend_kind = FrameEvalConfig.TracingBackendKind  # local alias

        # SettraceBackend is always available
        from dapper._frame_eval.settrace_backend import SettraceBackend  # noqa: PLC0415

        if kind is backend_kind.SETTRACE:
            return SettraceBackend()

        if kind is backend_kind.SYS_MONITORING:
            try:
                from dapper._frame_eval.monitoring_backend import (  # noqa: PLC0415
                    SysMonitoringBackend,
                )

                return SysMonitoringBackend()
            except ImportError:
                self._logger.warning(
                    "SysMonitoringBackend not available; falling back to SettraceBackend",
                )
                return SettraceBackend()

        # AUTO: pick monitoring when supported, settrace otherwise
        if self._compatibility_policy.supports_sys_monitoring():
            try:
                from dapper._frame_eval.monitoring_backend import (  # noqa: PLC0415
                    SysMonitoringBackend,
                )

                return SysMonitoringBackend()
            except ImportError:
                pass

        return SettraceBackend()

    def _create_eval_frame_backend(self, config: FrameEvalConfig) -> FrameEvalBackend:  # noqa: ARG002
        """Instantiate (or stub) an eval-frame implementation.

        In Phase 1 this is only a placeholder that may raise or log; once the
        low-level eval-frame hook is implemented we will populate this with a
        real backend.
        """
        from dapper._frame_eval.eval_frame_backend import EvalFrameBackend  # noqa: PLC0415

        return EvalFrameBackend()

    @property
    def is_initialized(self) -> bool:
        """Check if frame evaluation is initialized."""
        return self._is_initialized

    @property
    def config(self) -> FrameEvalConfig:
        """Get the current frame evaluation configuration."""
        return self._frame_eval_config

    @staticmethod
    def _coerce_enum_update(current_value: Any, candidate_value: Any) -> Any:
        """Coerce string-like config updates to the enum type of the current value."""
        if not isinstance(current_value, Enum) or isinstance(candidate_value, Enum):
            return candidate_value

        enum_type = type(current_value)
        try:
            return enum_type[candidate_value]
        except Exception:
            try:
                return enum_type(candidate_value)
            except Exception:
                return candidate_value

    def update_config(self, updates: dict[str, Any]) -> bool:
        """
        Update the frame evaluation configuration.

        Args:
            updates: Dictionary of configuration updates

        Returns:
            bool: True if update was successful, False otherwise
        """
        if not isinstance(updates, dict):
            self._logger.warning("Configuration updates must be a dictionary")
            return False

        if not updates:  # No updates to apply
            return True

        try:
            # Create a copy of the current config
            current_config = self._frame_eval_config

            # First, validate the updates without modifying the config
            temp_config = FrameEvalConfig.from_dict(current_config.to_dict())

            # Check which updates are valid and apply them to the temp config
            valid_updates = {}
            for key, value in updates.items():
                if hasattr(temp_config, key):
                    current_value = getattr(temp_config, key)
                    coerced_value = self._coerce_enum_update(current_value, value)

                    if coerced_value != current_value:  # Only update if value is different
                        setattr(temp_config, key, coerced_value)
                        valid_updates[key] = coerced_value

            if not valid_updates:  # No valid updates
                self._logger.warning("No valid configuration updates provided")
                return False

            # If _validate_config is mocked, it will return the value we set in the test
            # Otherwise, it will perform the actual validation
            if hasattr(self, "_validate_config"):
                # Get the validation result (will be the mocked return value in tests)
                is_valid = self._validate_config(temp_config)
                if not is_valid:
                    self._logger.warning("Invalid configuration updates")
                    return False

            # If we get here, validation passed - apply the updates to the real config
            for key, value in valid_updates.items():
                setattr(self._frame_eval_config, key, value)

            self._apply_config_side_effects(set(valid_updates))
            self._runtime.initialize(self._frame_eval_config)

            self._logger.debug("Updated frame evaluation config: %s", valid_updates)
        except Exception as e:
            self._logger.warning("Failed to update configuration: %s", e)
            return False
        else:
            return True

    def _apply_config_side_effects(self, updated_keys: set[str]) -> None:
        """Propagate config changes to caches, bytecode state, and condition evaluation."""
        if not updated_keys:
            return

        if "cache_size" in updated_keys:
            configure_caches(func_code_max_size=self._frame_eval_config.cache_size)

        if "optimize" in updated_keys:
            set_optimization_enabled(self._frame_eval_config.optimize)

        if {
            "conditional_breakpoints_enabled",
            "condition_budget_s",
        } & updated_keys:
            evaluator = get_condition_evaluator()
            evaluator.enabled = self._frame_eval_config.conditional_breakpoints_enabled
            evaluator._budget_s = self._frame_eval_config.condition_budget_s  # noqa: SLF001
            if "conditional_breakpoints_enabled" in updated_keys:
                evaluator.clear_cache()

        if {"cache_size", "optimize", "conditional_breakpoints_enabled"} & updated_keys:
            clear_all_caches(reason="config_change")

    def _validate_config(self, config: FrameEvalConfig) -> bool:
        """
        Validate the frame evaluation configuration.

        Args:
            config: Configuration to validate

        Returns:
            bool: True if configuration is valid, False otherwise
        """
        try:
            # Basic type checking
            if not isinstance(config, FrameEvalConfig):
                self._logger.warning("Configuration must be a FrameEvalConfig instance")
                return False

            # Define validation rules as (attribute, type, error_message, additional_check) tuples
            validations = [
                ("enabled", bool, "'enabled' must be a boolean", None),
                ("debug", bool, "'debug' must be a boolean", None),
                ("optimize", bool, "'optimize' must be a boolean", None),
                ("cache_size", int, "'cache_size' must be an integer", lambda x: x >= 0),
                ("timeout", (int, float), "'timeout' must be a number", lambda x: x >= 0),
            ]

            # Apply all validations
            for attr, expected_type, error_msg, additional_check in validations:
                value = getattr(config, attr, None)
                if not isinstance(value, expected_type):
                    self._logger.warning(error_msg)
                    return False
                if additional_check and not additional_check(value):
                    self._logger.warning(error_msg)
                    return False
        except Exception as e:
            self._logger.warning("Configuration validation failed: %s", e)
            return False
        else:
            return True

    def _is_incompatible_environment(self) -> bool:
        """
        Check if running in known incompatible environment.

        Returns:
            bool: True if running in incompatible environment
        """
        return self._compatibility_policy.is_incompatible_environment(sys.modules, os.environ)

    def check_environment_compatibility(self) -> dict[str, Any]:
        """
        Check if the current environment is compatible with frame evaluation.

        Returns:
            dict: Compatibility information with 'compatible' boolean key
        """
        # Use cache if available
        cache_key = (sys.version_info, platform.platform(), sys.platform)
        if cache_key in self._compatibility_cache:
            return self._compatibility_cache[cache_key]

        compatibility = self._compatibility_policy.evaluate_environment(
            version_info=sys.version_info,
            platform_name=platform.platform(),
            platform_system=platform.system(),
            architecture=platform.architecture()[0],
            implementation=platform.python_implementation(),
            modules=sys.modules,
            environ=os.environ,
        )

        self._compatibility_cache[cache_key] = compatibility
        return compatibility

    def _check_platform_compatibility(self) -> bool:
        """
        Check platform-specific compatibility.

        Returns:
            bool: True if current platform is supported
        """
        current_platform = platform.system()
        arch = platform.architecture()[0]
        return self._compatibility_policy.is_supported_platform(current_platform, arch)

    def setup_frame_eval(self, config: dict[str, Any]) -> bool:  # noqa: PLR0911
        """
        Set up frame evaluation with the provided configuration.

        Args:
            config: Configuration dictionary with frame evaluation settings

        Returns:
            bool: True if setup was successful, False otherwise
        """
        if not isinstance(config, dict):
            self._logger.warning("Configuration must be a dictionary")
            return False

        # Convert dict to FrameEvalConfig for validation
        try:
            frame_eval_config = FrameEvalConfig.from_dict(config)
        except Exception as e:
            self._logger.warning("Invalid configuration: %s", e)
            return False

        # Validate the configuration
        if not self._validate_config(frame_eval_config):
            return False

        # Apply the validated configuration to the manager state.  We use
        # :meth:`update_config` here so that any existing validation hooks are
        # exercised and downstream code always sees the same ``FrameEvalConfig``
        # instance that callers manipulated.
        if not self.update_config(config):
            return False

        # Initialize components now that the config has been applied.  This ensures
        # backend selection sees the desired settings (e.g. ``backend``/``tracing_backend``).
        try:
            self._initialize_components()
        except Exception:
            self._logger.exception("Failed to initialize frame evaluation components")
            return False

        # Keep runtime configuration in sync with validated manager config
        if not self._runtime.initialize(self._frame_eval_config.to_dict()):
            self._logger.warning("Failed to initialize frame evaluation runtime")
            return False

        self._is_initialized = True
        return True

    def shutdown_frame_eval(self) -> None:
        """Shut down frame evaluation and clean up resources."""
        if not self._is_initialized:
            return

        try:
            self._cleanup_components()
            self._is_initialized = False
            # Reset to default config
            self._frame_eval_config = FrameEvalConfig()
            self._logger.info("Frame evaluation shutdown complete")
        except Exception:
            self._logger.exception("Error during frame evaluation shutdown")
            raise

    def get_debug_info(self) -> dict[str, Any]:
        """
        Get debug information about frame evaluation setup.

        Returns:
            dict: Debug information including configuration and status
        """
        python_version = (
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        )

        return {
            "frame_eval_initialized": self._is_initialized,
            "frame_eval_config": self._frame_eval_config,
            "runtime_status": self._runtime.status(),
            "python_version": python_version,
            "platform": platform.system(),
            "architecture": platform.architecture()[0],
            "implementation": platform.python_implementation(),
            "compatibility": self.check_environment_compatibility(),
        }

    def _initialize_components(self) -> bool:
        """Initialize frame evaluation components.

        Returns:
            bool: True if initialization was successful
        """
        try:
            # Delegate component lifecycle to the runtime composition root.
            if not self._runtime.initialize(self._frame_eval_config.to_dict()):
                self._logger.warning("Runtime initialization returned False")
                return False

            # Create and store the active backend (tracing or eval-frame).
            self._active_backend = self._create_backend(self._frame_eval_config)
            self._logger.debug("Backend selected: %s", type(self._active_backend).__name__)
            self._logger.debug("Initializing frame evaluation components")
        except Exception:
            self._runtime.shutdown()
            self._active_backend = None
            self._logger.exception("Failed to initialize frame evaluation components")
            return False
        else:
            return True

    def _cleanup_components(self) -> None:
        """
        Clean up frame evaluation components.

        This method handles cleanup of all frame evaluation components
        and ensures proper resource deallocation.
        """
        try:
            # Shut down the active tracing backend first.
            if self._active_backend is not None:
                self._active_backend.shutdown()
                self._active_backend = None

            # Delegate component cleanup to the runtime composition root.
            self._runtime.shutdown()
            self._logger.debug("Cleaning up frame evaluation components")
        except Exception:
            self._logger.exception("Error during cleanup of frame evaluation components")
            raise


# Create the singleton instance
frame_eval_manager = FrameEvalManager()


def setup_frame_eval(config: dict[str, Any]) -> bool:
    """
    Set up frame evaluation with the provided configuration.

    This is the main entry point for initializing frame evaluation
    in Dapper. It handles compatibility checks, configuration validation,
    and initialization of all required components.

    Args:
        config: Configuration dictionary with frame evaluation settings

    Returns:
        bool: True if setup was successful, False otherwise
    """
    return frame_eval_manager.setup_frame_eval(config)


def check_environment_compatibility() -> dict[str, Any]:
    """
    Check if the current environment is compatible with frame evaluation.

    This is a legacy function that forwards to the FrameEvalManager instance.

    Returns:
        dict: Compatibility information with 'compatible' boolean key
    """
    return frame_eval_manager.check_environment_compatibility()


def shutdown_frame_eval() -> None:
    """Shut down frame evaluation and clean up resources."""
    frame_eval_manager.shutdown_frame_eval()


def get_debug_info() -> dict[str, Any]:
    """
    Get debug information about frame evaluation setup.

    Returns:
        dict: Debug information
    """
    return frame_eval_manager.get_debug_info()
