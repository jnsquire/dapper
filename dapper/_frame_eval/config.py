"""Configuration for frame evaluation."""

from dataclasses import dataclass
from enum import Enum
from typing import Any
from typing import ClassVar


@dataclass(frozen=False)  # Make it mutable for updates
class FrameEvalConfig:
    """Configuration for frame evaluation.

    Attributes:
        enabled: Whether frame evaluation is enabled
        fallback_to_tracing: Whether to fall back to tracing if frame evaluation fails
        debug: Whether to enable debug mode (more verbose logging)
        cache_size: Size of the frame evaluation cache
        optimize: Whether to optimize bytecode
        timeout: Operation timeout in seconds
        conditional_breakpoints_enabled: When ``True``, breakpoints with a
            ``condition`` expression are evaluated in the frame's context
            before dispatching to the debugger; frames where the condition is
            falsy are skipped cheaply.  Defaults to ``True``.
        condition_budget_s: Soft wall-clock budget (seconds) for evaluating a
            single condition expression.  If exceeded, a telemetry reason code
            is recorded and a warning is logged.  Defaults to ``0.1``.
    """

    # Default values
    enabled: bool = False
    fallback_to_tracing: bool = True
    debug: bool = False
    cache_size: int = 1000
    optimize: bool = True
    timeout: float = 30.0
    conditional_breakpoints_enabled: bool = True
    condition_budget_s: float = 0.1

    # Tracing backend selection: AUTO will choose sys.monitoring on
    # supported interpreters (Python 3.12+), otherwise fall back to
    # the settrace-based backend.
    class TracingBackendKind(Enum):
        AUTO = "auto"
        SETTRACE = "settrace"
        SYS_MONITORING = "sys_monitoring"

    tracing_backend: TracingBackendKind = TracingBackendKind.AUTO

    def __post_init__(self):
        """Initialize the configuration and handle any unknown fields."""
        # This method will be called by dataclass after __init__
        # We can use it to handle any initialization logic

    # Default instance for convenience
    DEFAULT: ClassVar["FrameEvalConfig"]

    def to_dict(self) -> dict[str, Any]:
        """Convert the config to a dictionary."""
        return {
            "enabled": self.enabled,
            "fallback_to_tracing": self.fallback_to_tracing,
            "debug": self.debug,
            "cache_size": self.cache_size,
            "optimize": self.optimize,
            "timeout": self.timeout,
            "conditional_breakpoints_enabled": self.conditional_breakpoints_enabled,
            "condition_budget_s": self.condition_budget_s,
            "tracing_backend": self.tracing_backend.name,
        }

    @classmethod
    def from_dict(cls, config_dict: dict[str, Any]) -> "FrameEvalConfig":
        """Create a config from a dictionary.

        Args:
            config_dict: Dictionary containing configuration values

        Returns:
            A new FrameEvalConfig instance with values from the dictionary

        Note:
            Unknown keys in the input dictionary will be ignored
        """
        # Get the list of valid field names from the dataclass
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}

        # Only include keys that are valid field names
        filtered_dict = {k: v for k, v in config_dict.items() if k in valid_fields}

        # Handle tracing_backend enum if present
        if "tracing_backend" in filtered_dict:
            val = filtered_dict["tracing_backend"]
            try:
                filtered_dict["tracing_backend"] = cls.TracingBackendKind[val]
            except Exception:
                # Accept either name or direct enum value; ignore invalid
                try:
                    filtered_dict["tracing_backend"] = cls.TracingBackendKind(val)
                except Exception:
                    filtered_dict.pop("tracing_backend", None)

        return cls(**filtered_dict)

    def reset(self) -> None:
        """Reset all configuration values to their defaults."""
        default = FrameEvalConfig()
        for field in self.__dataclass_fields__:
            setattr(self, field, getattr(default, field))

    def update(self, updates: dict[str, Any]) -> None:
        """Update the configuration with new values."""
        if not isinstance(updates, dict):
            raise TypeError("Updates must be a dictionary")

        for key, value in updates.items():
            if hasattr(self, key):
                setattr(self, key, value)


# Initialize the default config
# Set the default instance
FrameEvalConfig.DEFAULT = FrameEvalConfig()

# For backward compatibility
DEFAULT_CONFIG = FrameEvalConfig.DEFAULT
