"""Configuration for frame evaluation."""

from dataclasses import dataclass
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
    """
    
    # Default values
    enabled: bool = False
    fallback_to_tracing: bool = True
    debug: bool = False
    cache_size: int = 1000
    optimize: bool = True
    timeout: float = 30.0
    
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
            "timeout": self.timeout
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
        filtered_dict = {
            k: v for k, v in config_dict.items() 
            if k in valid_fields
        }
        
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
