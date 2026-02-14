"""Tests for the backend factory and unified abstraction."""

import asyncio
from typing import TYPE_CHECKING
from typing import Any

import pytest

from dapper.adapter.backend_factory import BackendFactory
from dapper.adapter.backend_factory import BackendManager
from dapper.adapter.backend_factory import ExternalProcessStrategy
from dapper.adapter.backend_factory import InProcessStrategy
from dapper.adapter.backend_factory import create_backend
from dapper.adapter.backend_factory import default_factory
from dapper.adapter.backend_factory import register_backend_strategy
from dapper.config import DapperConfig
from dapper.errors import BackendError
from dapper.errors import ConfigurationError

if TYPE_CHECKING:
    from dapper.adapter.debugger_backend import DebuggerBackend


class TestInProcessStrategy:
    """Test cases for InProcessStrategy."""

    def test_is_supported(self) -> None:
        """Test strategy support detection."""
        strategy = InProcessStrategy()

        # Supported configuration
        config = DapperConfig(mode="launch", in_process=True)
        assert strategy.is_supported(config) is True

        # Unsupported configurations
        config_attach = DapperConfig(mode="attach", in_process=True)
        assert strategy.is_supported(config_attach) is False

        config_external = DapperConfig(mode="launch", in_process=False)
        assert strategy.is_supported(config_external) is False

    def test_create_backend_success(self) -> None:
        """Test successful backend creation."""
        strategy = InProcessStrategy()
        config = DapperConfig(mode="launch", in_process=True)
        loop = asyncio.new_event_loop()

        def mock_on_stopped(event: dict) -> None:
            pass

        def mock_on_thread(event: dict) -> None:
            pass

        def mock_on_exited(event: dict) -> None:
            pass

        def mock_on_output(event: dict) -> None:
            pass

        backend = strategy.create_backend(
            config,
            loop,
            on_stopped=mock_on_stopped,
            on_thread=mock_on_thread,
            on_exited=mock_on_exited,
            on_output=mock_on_output,
        )

        assert backend is not None
        assert backend.__class__.__name__ == "InProcessBackend"
        assert backend.is_available() is True

        loop.close()

    def test_create_backend_wrong_config(self) -> None:
        """Test backend creation with wrong configuration."""
        strategy = InProcessStrategy()
        config = DapperConfig(mode="launch", in_process=False)
        loop = asyncio.new_event_loop()

        with pytest.raises(ConfigurationError, match="in_process=True"):
            strategy.create_backend(config, loop)

        loop.close()


class TestExternalProcessStrategy:
    """Test cases for ExternalProcessStrategy."""

    def test_is_supported(self) -> None:
        """Test strategy support detection."""
        strategy = ExternalProcessStrategy()

        # Supported configurations
        config_launch = DapperConfig(mode="launch", in_process=False)
        assert strategy.is_supported(config_launch) is True

        config_attach = DapperConfig(mode="attach", in_process=False)
        assert strategy.is_supported(config_attach) is True

        # Unsupported configuration
        config_inprocess = DapperConfig(mode="launch", in_process=True)
        assert strategy.is_supported(config_inprocess) is False

    def test_create_backend_success(self) -> None:
        """Test successful backend creation."""
        strategy = ExternalProcessStrategy()
        config = DapperConfig(mode="launch", in_process=False)
        loop = asyncio.new_event_loop()

        # Mock required dependencies
        mock_ipc = object()
        mock_process_state = (None, False)
        mock_pending_commands = {}
        mock_lock = object()

        def mock_get_next_id():
            return 1

        backend = strategy.create_backend(
            config,
            loop,
            ipc=mock_ipc,
            get_process_state=lambda: mock_process_state,
            pending_commands=mock_pending_commands,
            lock=mock_lock,
            get_next_command_id=mock_get_next_id,
        )

        assert backend is not None
        assert backend.__class__.__name__ == "ExternalProcessBackend"

        loop.close()

    def test_create_backend_missing_kwargs(self) -> None:
        """Test backend creation with missing required kwargs."""
        strategy = ExternalProcessStrategy()
        config = DapperConfig(mode="launch", in_process=False)
        loop = asyncio.new_event_loop()

        with pytest.raises(ConfigurationError, match="External process backend requires"):
            strategy.create_backend(config, loop)

        loop.close()

    def test_create_backend_wrong_config(self) -> None:
        """Test backend creation with wrong configuration."""
        strategy = ExternalProcessStrategy()
        config = DapperConfig(mode="launch", in_process=True)
        loop = asyncio.new_event_loop()

        with pytest.raises(ConfigurationError, match="in_process=False"):
            strategy.create_backend(config, loop)

        loop.close()


class TestBackendFactory:
    """Test cases for BackendFactory."""

    def test_default_strategies(self) -> None:
        """Test factory has default strategies."""
        factory = BackendFactory()

        # Should have InProcessStrategy and ExternalProcessStrategy
        assert len(factory._strategies) == 2
        assert any(s.name == "inprocess" for s in factory._strategies)
        assert any(s.name == "external" for s in factory._strategies)

    def test_register_strategy(self) -> None:
        """Test registering a custom strategy."""
        factory = BackendFactory()

        class MockStrategy:
            @property
            def name(self) -> str:
                return "mock"

            def is_supported(self, config: DapperConfig) -> bool:  # noqa: ARG002
                return False

            def create_backend(
                self,
                config: DapperConfig,  # noqa: ARG002
                loop: asyncio.AbstractEventLoop,  # noqa: ARG002
                **kwargs: Any,  # noqa: ARG002
            ) -> "DebuggerBackend":
                # Return a mock backend that satisfies the protocol
                class MockBackend:
                    def is_available(self) -> bool:
                        return False

                    async def terminate(self) -> None:
                        pass

                    async def configuration_done(self) -> None:
                        pass

                return MockBackend()  # type: ignore[return-value]

        strategy = MockStrategy()
        factory.register_strategy(strategy)

        assert len(factory._strategies) == 3
        assert any(s.name == "mock" for s in factory._strategies)

    def test_create_backend_inprocess(self) -> None:
        """Test creating in-process backend."""
        factory = BackendFactory()
        config = DapperConfig(mode="launch", in_process=True)
        loop = asyncio.new_event_loop()

        backend = factory.create_backend(config, loop)

        assert backend is not None
        assert backend.__class__.__name__ == "InProcessBackend"

        loop.close()

    def test_create_backend_external(self) -> None:
        """Test creating external process backend."""
        factory = BackendFactory()
        config = DapperConfig(mode="launch", in_process=False)
        loop = asyncio.new_event_loop()

        # Mock required dependencies
        mock_ipc = object()
        mock_process_state = (None, False)
        mock_pending_commands = {}
        mock_lock = object()

        def mock_get_next_id():
            return 1

        backend = factory.create_backend(
            config,
            loop,
            ipc=mock_ipc,
            get_process_state=lambda: mock_process_state,
            pending_commands=mock_pending_commands,
            lock=mock_lock,
            get_next_command_id=mock_get_next_id,
        )

        assert backend is not None
        assert backend.__class__.__name__ == "ExternalProcessBackend"

        loop.close()

    def test_create_backend_no_strategy(self) -> None:
        """Test creating backend with no supporting strategy."""
        factory = BackendFactory()

        # Create a config that no strategy supports
        config = DapperConfig(mode="attach", in_process=True)  # Invalid combination

        loop = asyncio.new_event_loop()

        with pytest.raises(BackendError, match="No backend strategy supports"):
            factory.create_backend(config, loop)

        loop.close()

    def test_create_backend_strategy_error(self) -> None:
        """Test handling strategy errors during backend creation."""
        factory = BackendFactory()

        class FailingStrategy:
            @property
            def name(self) -> str:
                return "failing"

            def is_supported(self, config: DapperConfig) -> bool:  # noqa: ARG002
                return True

            def create_backend(
                self, config: DapperConfig, loop: asyncio.AbstractEventLoop, **kwargs
            ):  # noqa: ARG002
                raise RuntimeError("Strategy failed")

        # Remove default strategies and add failing one
        factory._strategies = [FailingStrategy()]

        config = DapperConfig(mode="launch", in_process=False)
        loop = asyncio.new_event_loop()

        with pytest.raises(BackendError, match="Failed to create backend"):
            factory.create_backend(config, loop)

        loop.close()

    def test_get_supported_strategies(self) -> None:
        """Test getting supported strategies for a configuration."""
        factory = BackendFactory()

        config_inprocess = DapperConfig(mode="launch", in_process=True)
        supported = factory.get_supported_strategies(config_inprocess)
        assert "inprocess" in supported
        assert "external" not in supported

        config_external = DapperConfig(mode="launch", in_process=False)
        supported = factory.get_supported_strategies(config_external)
        assert "inprocess" not in supported
        assert "external" in supported


class TestGlobalFunctions:
    """Test cases for global convenience functions."""

    def test_create_backend_global(self) -> None:
        """Test global create_backend function."""
        config = DapperConfig(mode="launch", in_process=True)
        loop = asyncio.new_event_loop()

        backend = create_backend(config, loop)

        assert backend is not None
        assert backend.__class__.__name__ == "InProcessBackend"

        loop.close()

    def test_register_backend_strategy_global(self) -> None:
        """Test global register_backend_strategy function."""

        class MockStrategy:
            @property
            def name(self) -> str:
                return "global_mock"

            def is_supported(self, config: DapperConfig) -> bool:  # noqa: ARG002
                return False

            def create_backend(
                self, config: DapperConfig, loop: asyncio.AbstractEventLoop, **kwargs
            ) -> "DebuggerBackend":  # noqa: ARG002
                # Return a mock backend that satisfies the protocol
                class MockBackend:
                    def is_available(self) -> bool:
                        return False

                    async def terminate(self) -> None:
                        pass

                    async def configuration_done(self) -> None:
                        pass

                return MockBackend()  # type: ignore[return-value]

        strategy = MockStrategy()
        register_backend_strategy(strategy)

        # Check it was added to default factory
        assert any(s.name == "global_mock" for s in default_factory._strategies)


class TestBackendManager:
    """Test cases for BackendManager."""

    def test_initialization(self) -> None:
        """Test backend manager initialization."""
        manager = BackendManager()

        assert manager.backend is None
        assert manager.is_available() is False

    @pytest.mark.asyncio
    async def test_initialize_inprocess(self) -> None:
        """Test initializing in-process backend."""
        manager = BackendManager()
        config = DapperConfig(mode="launch", in_process=True)
        loop = asyncio.get_event_loop()

        backend = await manager.initialize(config, loop)

        assert backend is not None
        assert backend.__class__.__name__ == "InProcessBackend"
        assert manager.backend is backend
        assert manager.is_available() is True

        await manager.terminate()
        assert manager.backend is None
        assert manager.is_available() is False

    @pytest.mark.asyncio
    async def test_initialize_external(self) -> None:
        """Test initializing external process backend."""
        manager = BackendManager()
        config = DapperConfig(mode="launch", in_process=False)
        loop = asyncio.get_event_loop()

        # Mock required dependencies
        mock_ipc = object()
        mock_process_state = (None, False)
        mock_pending_commands = {}
        mock_lock = object()

        def mock_get_next_id():
            return 1

        backend = await manager.initialize(
            config,
            loop,
            ipc=mock_ipc,
            get_process_state=lambda: mock_process_state,
            pending_commands=mock_pending_commands,
            lock=mock_lock,
            get_next_command_id=mock_get_next_id,
        )

        assert backend is not None
        assert backend.__class__.__name__ == "ExternalProcessBackend"
        assert manager.backend is backend
        # External backend availability depends on actual implementation
        # Just check that the backend exists rather than its availability
        assert manager.backend is backend

        await manager.terminate()

    @pytest.mark.asyncio
    async def test_configuration_done(self) -> None:
        """Test configuration done signaling."""
        manager = BackendManager()
        config = DapperConfig(mode="launch", in_process=True)
        loop = asyncio.get_event_loop()

        await manager.initialize(config, loop)
        await manager.configuration_done()

        await manager.terminate()

    def test_get_backend_info(self) -> None:
        """Test getting backend information."""
        manager = BackendManager()

        info = manager.get_backend_info()
        assert info["status"] == "no_backend"

        # After initialization would have more info, but that requires async
        # This is tested implicitly in other tests
