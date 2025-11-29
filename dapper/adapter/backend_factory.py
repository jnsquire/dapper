"""Backend factory and unified abstraction for debugger backends.

This module provides a factory pattern for creating debugger backends and
a unified abstraction that simplifies backend selection and management.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from typing import Any
from typing import Protocol
from typing import runtime_checkable

from dapper.errors import BackendError
from dapper.errors import ConfigurationError

if TYPE_CHECKING:
    import asyncio

    from dapper.adapter.debugger_backend import DebuggerBackend
    from dapper.config import DapperConfig

# Import backend classes at top level for strategy implementations
from dapper.adapter.external_backend import ExternalProcessBackend
from dapper.adapter.inprocess_backend import InProcessBackend
from dapper.adapter.inprocess_bridge import InProcessBridge
from dapper.core.inprocess_debugger import InProcessDebugger

logger = logging.getLogger(__name__)


@runtime_checkable
class BackendStrategy(Protocol):
    """Strategy interface for different backend types."""
    
    def create_backend(
        self,
        config: DapperConfig,
        loop: asyncio.AbstractEventLoop,
        **kwargs: Any,
    ) -> DebuggerBackend:
        """Create a backend instance for the given configuration."""
        ...
    
    def is_supported(self, config: DapperConfig) -> bool:
        """Check if this strategy supports the given configuration."""
        ...
    
    @property
    def name(self) -> str:
        """Get the strategy name."""
        ...


class InProcessStrategy:
    """Strategy for in-process debugging."""
    
    def create_backend(
        self,
        config: DapperConfig,
        loop: asyncio.AbstractEventLoop,  # Required by interface but unused in this strategy
        **kwargs: Any,
    ) -> DebuggerBackend:
        """Create an in-process backend."""
        if not config.in_process:
            raise ConfigurationError(
                "In-process backend requires in_process=True",
                config_key="in_process",
            )
        
        # Create the in-process components
        debugger = InProcessDebugger()
        
        # Prepare callbacks with proper defaults
        def default_on_stopped(event: dict[str, Any]) -> None:
            pass
        
        def default_on_thread(event: dict[str, Any]) -> None:
            pass
        
        def default_on_exited(event: dict[str, Any]) -> None:
            pass
        
        def default_on_output(category: str, output: str) -> None:
            pass
        
        bridge = InProcessBridge(
            debugger,
            on_stopped=kwargs.get("on_stopped") or default_on_stopped,
            on_thread=kwargs.get("on_thread") or default_on_thread,
            on_exited=kwargs.get("on_exited") or default_on_exited,
            on_output=kwargs.get("on_output") or default_on_output,
        )
        
        return InProcessBackend(bridge)
    
    def is_supported(self, config: DapperConfig) -> bool:
        """Check if in-process debugging is supported."""
        return config.in_process and config.mode == "launch"
    
    @property
    def name(self) -> str:
        return "inprocess"


class ExternalProcessStrategy:
    """Strategy for external process debugging."""
    
    def create_backend(
        self,
        config: DapperConfig,
        loop: asyncio.AbstractEventLoop,
        **kwargs: Any,
    ) -> DebuggerBackend:
        """Create an external process backend."""
        if config.in_process:
            raise ConfigurationError(
                "External process backend requires in_process=False",
                config_key="in_process",
            )
        
        # Required dependencies for external backend
        required_kwargs = {
            "ipc",
            "get_process_state",
            "pending_commands",
            "lock",
            "get_next_command_id",
        }
        
        missing = required_kwargs - set(kwargs.keys())
        if missing:
            missing_str = ", ".join(missing)
            error_msg = f"External process backend requires: {missing_str}"
            raise ConfigurationError(
                error_msg,
                details={"missing_kwargs": list(missing)},
            )
        
        return ExternalProcessBackend(
            ipc=kwargs["ipc"],
            loop=loop,
            get_process_state=kwargs["get_process_state"],
            pending_commands=kwargs["pending_commands"],
            lock=kwargs["lock"],
            get_next_command_id=kwargs["get_next_command_id"],
        )
    
    def is_supported(self, config: DapperConfig) -> bool:
        """Check if external process debugging is supported."""
        return not config.in_process
    
    @property
    def name(self) -> str:
        return "external"


class BackendFactory:
    """Factory for creating debugger backends based on configuration."""
    
    def __init__(self) -> None:
        """Initialize the factory with default strategies."""
        self._strategies: list[BackendStrategy] = [
            InProcessStrategy(),
            ExternalProcessStrategy(),
        ]
    
    def register_strategy(self, strategy: BackendStrategy) -> None:
        """Register a new backend strategy."""
        self._strategies.append(strategy)
        logger.info(f"Registered backend strategy: {strategy.name}")
    
    def create_backend(
        self,
        config: DapperConfig,
        loop: asyncio.AbstractEventLoop,
        **kwargs: Any,
    ) -> DebuggerBackend:
        """Create a backend instance based on the configuration.
        
        Args:
            config: The debug configuration
            loop: The asyncio event loop
            **kwargs: Additional arguments passed to the strategy
            
        Returns:
            A configured backend instance
            
        Raises:
            BackendError: If no suitable strategy is found
            ConfigurationError: If the configuration is invalid
        """
        for strategy in self._strategies:
            if strategy.is_supported(config):
                logger.info(f"Using backend strategy: {strategy.name}")
                try:
                    return strategy.create_backend(config, loop, **kwargs)
                except Exception as e:
                    error_msg = f"Failed to create backend with strategy {strategy.name}: {e!s}"
                    raise BackendError(
                        error_msg,
                        backend_type=strategy.name,
                        cause=e,
                    ) from e
        
        # No strategy found
        supported_modes = [s.name for s in self._strategies]
        error_msg = f"No backend strategy supports configuration: mode={config.mode}, in_process={config.in_process}"
        raise BackendError(
            error_msg,
            details={
                "config_mode": config.mode,
                "in_process": config.in_process,
                "supported_strategies": supported_modes,
            },
        )
    
    def get_supported_strategies(self, config: DapperConfig) -> list[str]:
        """Get list of strategy names that support the given configuration."""
        return [s.name for s in self._strategies if s.is_supported(config)]


# Global factory instance
default_factory = BackendFactory()


def create_backend(
    config: DapperConfig,
    loop: asyncio.AbstractEventLoop,
    **kwargs: Any,
) -> DebuggerBackend:
    """Create a backend using the default factory.
    
    Args:
        config: The debug configuration
        loop: The asyncio event loop
        **kwargs: Additional arguments passed to the strategy
        
    Returns:
        A configured backend instance
    """
    return default_factory.create_backend(config, loop, **kwargs)


def register_backend_strategy(strategy: BackendStrategy) -> None:
    """Register a backend strategy with the default factory."""
    default_factory.register_strategy(strategy)


class BackendManager:
    """Manager for backend lifecycle and operations."""
    
    def __init__(self, factory: BackendFactory | None = None) -> None:
        """Initialize the backend manager."""
        self._factory = factory or default_factory
        self._backend: DebuggerBackend | None = None
        self._config: DapperConfig | None = None
    
    async def initialize(
        self,
        config: DapperConfig,
        loop: asyncio.AbstractEventLoop,
        **kwargs: Any,
    ) -> DebuggerBackend:
        """Initialize the backend based on configuration.
        
        Args:
            config: The debug configuration
            loop: The asyncio event loop
            **kwargs: Additional arguments passed to the backend factory
            
        Returns:
            The initialized backend
        """
        if self._backend is not None:
            await self.terminate()
        
        self._config = config
        self._backend = self._factory.create_backend(config, loop, **kwargs)
        
        logger.info(f"Initialized backend: {self._backend.__class__.__name__}")
        return self._backend
    
    @property
    def backend(self) -> DebuggerBackend | None:
        """Get the current backend."""
        return self._backend
    
    def is_available(self) -> bool:
        """Check if a backend is available and ready."""
        return self._backend is not None and self._backend.is_available()
    
    async def terminate(self) -> None:
        """Terminate the current backend."""
        if self._backend is not None:
            try:
                await self._backend.terminate()
                logger.info("Backend terminated successfully")
            except Exception:
                logger.exception("Error terminating backend")
            finally:
                self._backend = None
                self._config = None
    
    async def configuration_done(self) -> None:
        """Signal configuration done to the backend."""
        if self._backend is not None:
            await self._backend.configuration_done()
    
    def get_backend_info(self) -> dict[str, Any]:
        """Get information about the current backend."""
        if self._backend is None:
            return {"status": "no_backend"}
        
        return {
            "status": "active",
            "type": self._backend.__class__.__name__,
            "available": self._backend.is_available(),
            "config": self._config.to_launch_kwargs() if self._config else None,
        }
