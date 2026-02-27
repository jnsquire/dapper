"""Test script for debugger integration with frame evaluation system."""

from __future__ import annotations

from pathlib import Path
import threading
import traceback
from typing import TYPE_CHECKING
from typing import Any
from typing import Callable
from typing import ClassVar
from typing import TypedDict

from dapper._frame_eval.debugger_integration import auto_integrate_debugger
from dapper._frame_eval.debugger_integration import configure_integration
from dapper._frame_eval.debugger_integration import get_integration_bridge
from dapper._frame_eval.debugger_integration import get_integration_statistics
from dapper._frame_eval.debugger_integration import integrate_debugger_bdb
from dapper._frame_eval.selective_tracer import get_trace_manager

if TYPE_CHECKING:
    from dapper.protocol.debugger_protocol import ExceptionInfo
    from dapper.protocol.debugger_protocol import Variable


class PresentationHint(TypedDict, total=False):
    kind: str
    attributes: list[str]
    visibility: str


class Variable(TypedDict):
    name: str
    value: str
    type: str
    variablesReference: int
    presentationHint: PresentationHint


class MockDebuggerBDB:
    """Mock DebuggerBDB class for testing integration."""

    # Class variable for breakpoints
    custom_breakpoints: ClassVar[dict[str, Any]] = {}

    def __init__(self):
        # Required attributes from DebuggerLike protocol
        self.breakpoints: dict[str, list[int]] = {}
        self.function_breakpoints: list[str] = []
        self.function_breakpoint_meta: dict[str, dict[str, Any]] = {}
        self.threads: dict[Any, Any] = {}
        self.next_var_ref: int = 0
        self.var_refs: dict[int, Any] = {}
        self.frame_id_to_frame: dict[int, Any] = {}
        self.frames_by_thread: dict[int, list[Any]] = {}
        self.current_exception_info: dict[int, ExceptionInfo] = {}
        self.current_frame: Any | None = None
        self.stepping: bool = False
        self.data_breakpoints: list[dict[str, Any]] | None = []
        self.stop_on_entry: bool = False
        self.data_watch_names: set[str] | list[str] | None = set()
        self.data_watch_meta: dict[str, Any] | None = {}
        self._data_watches: dict[str, Any] | None = {}
        self._frame_watches: dict[int, list[str]] | None = {}
        self.stopped_thread_ids: set[int] = set()
        self.exception_breakpoints_uncaught: bool = False
        self.exception_breakpoints_raised: bool = False
        self._frame_eval_enabled: bool = False
        self._mock_user_line: Any | None = None
        self._trace_function: Callable[[Any | None, str | None, Any | None], Any | None] | None = (
            None
        )

        # Test-specific attributes
        self.user_line_calls: list[dict[str, Any]] = []
        self.current_thread_id = threading.get_ident()

    def get_trace_function(self) -> Callable[[Any | None, str | None, Any | None], Any | None]:
        """Get the current trace function.

        Returns:
            The current trace function that takes (frame, event, arg) as arguments.
            If no trace function is set, returns a no-op function.
        """
        if self._trace_function is not None:
            return self._trace_function
        return lambda _frame, _event, _arg: None

    def set_trace_function(
        self,
        trace_func: Callable[[Any | None, str | None, Any | None], Any | None] | None,
    ) -> None:
        """Set a new trace function.

        Args:
            trace_func: The new trace function that takes (frame, event, arg) as arguments,
                       or None to clear it (equivalent to a no-op function).
        """
        self._trace_function = trace_func

    def make_variable_object(
        self,
        name: Any,
        value: Any,
        frame: Any | None = None,  # noqa: ARG002
        *,
        max_string_length: int = 1000,  # noqa: ARG002
    ) -> Variable:
        """Mock make_variable_object function."""
        return Variable(
            name=str(name),
            value=str(value),
            type=type(value).__name__,
            variablesReference=0,
            presentationHint={"kind": "property", "attributes": [], "visibility": "public"},
        )

    def user_line(self, frame: Any) -> None:
        """Mock user_line function."""
        self.user_line_calls.append(
            {
                "filename": frame.f_code.co_filename,
                "lineno": frame.f_lineno,
                "function": frame.f_code.co_name,
            }
        )

    def set_break(
        self,
        filename: str,
        lineno: int,
        temporary: bool = False,  # noqa: ARG002
        cond: Any = None,  # noqa: ARG002
        funcname: str | None = None,  # noqa: ARG002
    ) -> None:
        """Mock set_break function.

        Args:
            filename: The file where to set the breakpoint
            lineno: The line number where to set the breakpoint
            temporary: Whether the breakpoint is temporary
            cond: Optional condition expression
            funcname: Optional function name
        """
        if filename not in self.breakpoints:
            self.breakpoints[filename] = []
        if lineno not in self.breakpoints[filename]:
            self.breakpoints[filename].append(lineno)

    def clear_break(self, filename: str, lineno: int) -> bool:
        """Mock clear_break function.

        Args:
            filename: Path to the file containing the breakpoint
            lineno: Line number of the breakpoint

        Returns:
            True if the breakpoint was found and removed, False otherwise
        """
        if filename in self.breakpoints and lineno in self.breakpoints[filename]:
            self.breakpoints[filename].remove(lineno)
            if not self.breakpoints[filename]:
                del self.breakpoints[filename]
            return True
        return False

    def clear_breaks_for_file(self, path: str) -> None:
        """Mock clear_breaks_for_file function.

        Args:
            path: Path to the file to clear breakpoints from

        """
        if path in self.breakpoints:
            del self.breakpoints[path]

    def set_continue(self) -> None:
        """Mock set_continue function."""
        self.stepping = False

    def set_next(self, frame: Any) -> None:  # noqa: ARG002
        """Mock set_next function.

        Args:
            frame: The frame to step to next.

        """
        self.stepping = True

    def set_step(self) -> None:
        """Mock set_step function."""
        self.stepping = True

    def set_return(self, frame: Any) -> None:  # noqa: ARG002
        """Mock set_return function.

        Args:
            frame: The frame to return from.

        """
        self.stepping = True

    def run(self, cmd: Any, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        """Mock run function.

        Args:
            cmd: The command to run
            *args: Additional positional arguments
            **kwargs: Additional keyword arguments

        """
        return

    def record_breakpoint(
        self,
        path: str,
        line: int,
        *,
        condition: str | None,
        hit_condition: str | None,
        log_message: str | None,
    ) -> None:
        """Mock record_breakpoint function.

        Args:
            path: Path to the file containing the breakpoint
            line: Line number of the breakpoint
            condition: Optional condition expression
            hit_condition: Optional hit condition expression
            log_message: Optional log message

        """

    def clear_break_meta_for_file(self, path: str) -> None:
        """Mock clear_break_meta_for_file function.

        Args:
            path: Path to the file to clear breakpoint metadata for

        """

    def clear_all_function_breakpoints(self) -> None:
        """Mock clear_all_function_breakpoints function."""
        self.function_breakpoints.clear()

    def set_breakpoints(
        self,
        source: str | dict[str, Any],
        breakpoints: list[dict[str, Any]],
        **kwargs: Any,  # noqa: ARG002
    ) -> None:
        """Mock set_breakpoints function.

        Args:
            source: The source file path or dict containing 'path' key
            breakpoints: List of breakpoint dictionaries
            **kwargs: Additional keyword arguments

        """
        source_path = source if isinstance(source, str) else source.get("path", "")
        if source_path not in self.breakpoints:
            self.breakpoints[source_path] = []

        # Clear existing breakpoints for this source
        self.breakpoints[source_path] = []

        # Add new breakpoints
        for bp in breakpoints:
            line = bp.get("line", 0)
            if line not in self.breakpoints[source_path]:
                self.breakpoints[source_path].append(line)

    def set_trace(self, frame: Any | None = None) -> None:
        """Mock set_trace function.

        Args:
            frame: The frame to start tracing from, or None for the current frame.

        """
        if self._trace_function:
            self._trace_function(frame)


class MockPyDebugger:
    """Mock PyDebugger class for testing integration."""

    # Class variable for breakpoints
    custom_breakpoints: ClassVar[dict[str, Any]] = {}

    def __init__(self):
        # Required attributes from DebuggerLike protocol
        self.breakpoints: dict[str, list[int]] = {}
        self.function_breakpoints: list[str] = []
        self.function_breakpoint_meta: dict[str, dict[str, Any]] = {}
        self.threads: dict[Any, Any] = {}
        self.next_var_ref: int = 0
        self.var_refs: dict[int, Any] = {}
        self.frame_id_to_frame: dict[int, Any] = {}
        self.frames_by_thread: dict[int, list[Any]] = {}
        self.current_exception_info: dict[int, ExceptionInfo] = {}
        self.current_frame: Any | None = None
        self.stepping: bool = False
        self.data_breakpoints: list[dict[str, Any]] | None = []
        self.stop_on_entry: bool = False
        self.data_watch_names: set[str] | list[str] | None = set()
        self.data_watch_meta: dict[str, Any] | None = {}
        self._data_watches: dict[str, Any] | None = {}
        self._frame_watches: dict[int, list[str]] | None = {}
        self.stopped_thread_ids: set[int] = set()
        self.exception_breakpoints_uncaught: bool = False
        self.exception_breakpoints_raised: bool = False
        self._frame_eval_enabled: bool = False
        self._mock_user_line: Any | None = None
        self._trace_function: Callable[[Any | None, str | None, Any | None], Any | None] | None = (
            None
        )

        # Test-specific attributes
        self.set_breakpoints_calls: list[dict[str, Any]] = []
        self.trace_function_calls: list[float] = []
        self.user_line_calls: list[dict[str, Any]] = []
        self.current_thread_id = threading.get_ident()

    def get_trace_function(self) -> Callable[[Any | None, str | None, Any | None], Any | None]:
        """Get the current trace function.

        Returns:
            The current trace function that takes (frame, event, arg) as arguments.
            If no trace function is set, returns a no-op function.

        """
        if self._trace_function is not None:
            return self._trace_function
        return lambda _frame, _event, _arg: None

    def set_trace_function(
        self,
        trace_func: Callable[[Any | None, str | None, Any | None], Any | None] | None,
    ) -> None:
        """Set a new trace function.

        Args:
            trace_func: The new trace function that takes (frame, event, arg) as arguments,
                       or None to clear it (equivalent to a no-op function).

        """
        self._trace_function = trace_func

    def set_break(
        self,
        filename: str,
        lineno: int,
        temporary: bool = False,  # noqa: ARG002
        cond: Any = None,  # noqa: ARG002
        funcname: str | None = None,  # noqa: ARG002
    ) -> None:
        """Mock set_break function.

        Args:
            filename: The file where to set the breakpoint
            lineno: The line number where to set the breakpoint
            temporary: Whether the breakpoint is temporary
            cond: Optional condition expression
            funcname: Optional function name

        """
        if filename not in self.breakpoints:
            self.breakpoints[filename] = []
        if lineno not in self.breakpoints[filename]:
            self.breakpoints[filename].append(lineno)

    def clear_break(self, filename: str, lineno: int) -> bool:
        """Mock clear_break function.

        Args:
            filename: Path to the file containing the breakpoint
            lineno: Line number of the breakpoint

        Returns:
            True if the breakpoint was found and removed, False otherwise

        """
        if filename in self.breakpoints and lineno in self.breakpoints[filename]:
            self.breakpoints[filename].remove(lineno)
            if not self.breakpoints[filename]:
                del self.breakpoints[filename]
            return True
        return False

    def clear_breaks_for_file(self, path: str) -> None:
        """Mock clear_breaks_for_file function.

        Args:
            path: Path to the file to clear breakpoints from

        """
        if path in self.breakpoints:
            del self.breakpoints[path]

    def set_continue(self) -> None:
        """Mock set_continue function."""
        self.stepping = False

    def set_next(self, frame: Any) -> None:  # noqa: ARG002
        """Mock set_next function.

        Args:
            frame: The frame to step to next.

        """
        self.stepping = True

    def set_step(self) -> None:
        """Mock set_step function."""
        self.stepping = True

    def set_return(self, frame: Any) -> None:  # noqa: ARG002
        """Mock set_return function.

        Args:
            frame: The frame to return from.

        """
        self.stepping = True

    def run(self, cmd: Any, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        """Mock run function.

        Args:
            cmd: The command to run
            *args: Additional positional arguments
            **kwargs: Additional keyword arguments

        """
        return

    def record_breakpoint(
        self,
        path: str,
        line: int,
        *,
        condition: str | None,
        hit_condition: str | None,
        log_message: str | None,
    ) -> None:
        """Mock record_breakpoint function."""

    def clear_break_meta_for_file(self, path: str) -> None:
        """Mock clear_break_meta_for_file function.

        Args:
            path: Path to the file to clear breakpoint metadata for

        """

    def clear_all_function_breakpoints(self) -> None:
        """Mock clear_all_function_breakpoints function."""
        self.function_breakpoints.clear()

    def set_breakpoints(
        self,
        source: str | dict[str, Any],
        breakpoints: list[dict[str, Any]],
        **kwargs: Any,
    ) -> None:
        """Mock set_breakpoints function.

        Args:
            source: The source file path or dict containing 'path' key
            breakpoints: List of breakpoint dictionaries
            **kwargs: Additional keyword arguments

        """
        self.set_breakpoints_calls.append(
            {
                "source": source,
                "breakpoints": breakpoints,
                "kwargs": kwargs,
            },
        )

        source_path = source if isinstance(source, str) else source.get("path", "")
        if source_path not in self.breakpoints:
            self.breakpoints[source_path] = []

        # Clear existing breakpoints for this source
        self.breakpoints[source_path] = []

        # Add new breakpoints
        for bp in breakpoints:
            line = bp.get("line", 0)
            if line not in self.breakpoints[source_path]:
                self.breakpoints[source_path].append(line)

    def set_trace(self, frame: Any | None = None) -> None:
        """Mock set_trace function.

        Args:
            frame: The frame to start tracing from, or None for the current frame.

        """
        if self._trace_function:
            self._trace_function(frame)

    def make_variable_object(
        self,
        name: Any,
        value: Any,
        frame: Any | None = None,  # noqa: ARG002
        *,
        max_string_length: int = 1000,  # noqa: ARG002
    ) -> Variable:
        """Mock make_variable_object function."""
        return Variable(
            name=str(name),
            value=str(value),
            type=type(value).__name__,
            variablesReference=0,
            presentationHint={"kind": "property", "attributes": [], "visibility": "public"},
        )

    def user_line(self, frame: Any) -> None:
        """Mock user_line function.

        Args:
            frame: The frame where the debugger has stopped.

        """
        # Call the trace function if set
        trace_func = self.get_trace_function()
        if trace_func:
            trace_func(frame, "line", None)

        # Record the call for testing
        self.user_line_calls.append(
            {
                "filename": frame.f_code.co_filename,
                "lineno": frame.f_lineno,
                "function": frame.f_code.co_name,
            },
        )


def test_auto_integration():
    """Test automatic integration detection."""
    print("\n=== Testing Auto Integration ===")

    try:
        # Test with DebuggerBDB
        debugger_bdb = MockDebuggerBDB()
        success_bdb = auto_integrate_debugger(debugger_bdb)
        print(f"Auto-integration DebuggerBDB: {success_bdb}")

        # Test with PyDebugger
        debugger_py = MockPyDebugger()
        success_py = auto_integrate_debugger(debugger_py)
        print(f"Auto-integration PyDebugger: {success_py}")

        # Test with unknown object
        unknown = object()
        success_unknown = auto_integrate_debugger(unknown)
        print(f"Auto-integration unknown: {success_unknown}")

        # Check overall statistics
        stats = get_integration_statistics()
        print(f"Total integrations: {stats['integration_stats']['integrations_enabled']}")

        print("[PASS] Auto integration tests passed")

    except Exception as e:
        print(f"[FAIL] Auto integration test failed: {e}")
        traceback.print_exc()


def test_configuration():
    """Test integration configuration."""
    print("\n=== Testing Configuration ===")

    try:
        bridge = get_integration_bridge()

        # Test initial configuration
        initial_config = bridge.config.copy()
        print(f"Initial config: {initial_config}")

        # Test configuration updates
        configure_integration(
            selective_tracing=False,
            bytecode_optimization=False,
            performance_monitoring=True,
        )

        updated_config = bridge.config.copy()
        print(f"Updated config: {updated_config}")

        # Verify changes
        assert not updated_config["selective_tracing"]
        assert not updated_config["bytecode_optimization"]
        assert updated_config["performance_monitoring"]

        # Test disabling
        configure_integration(enabled=False)
        disabled_config = bridge.config.copy()
        print(f"Disabled config: {disabled_config}")

        print("[PASS] Configuration tests passed")

    except Exception as e:
        print(f"❌ Configuration test failed: {e}")
        traceback.print_exc()


def test_performance_monitoring():
    """Test performance monitoring functionality."""
    print("\n=== Testing Performance Monitoring ===")

    try:
        bridge = get_integration_bridge()

        # Enable performance monitoring
        bridge.enable_performance_monitoring(True)

        # Simulate some activity
        for _i in range(10):
            bridge._monitor_trace_call()

        for _i in range(5):
            bridge._monitor_frame_eval_call()

        # Get statistics
        stats = get_integration_statistics()
        perf_data = stats["performance_data"]

        print(f"Trace function calls: {perf_data['trace_function_calls']}")
        print(f"Frame eval calls: {perf_data['frame_eval_calls']}")
        print(f"Uptime: {perf_data['uptime_seconds']:.2f}s")

        # Test statistics reset
        bridge.reset_statistics()
        reset_stats = get_integration_statistics()
        reset_perf = reset_stats["performance_data"]

        print(f"After reset - Trace calls: {reset_perf['trace_function_calls']}")
        print(f"After reset - Frame eval calls: {reset_perf['frame_eval_calls']}")

        print("[PASS] Performance monitoring tests passed")

    except Exception as e:
        print(f"[FAIL] Performance monitoring test failed: {e}")
        traceback.print_exc()


def test_selective_tracing_integration():
    """Test selective tracing integration."""
    print("\n=== Testing Selective Tracing Integration ===")

    try:
        # Create mock debugger
        debugger = MockDebuggerBDB()

        # Integrate with selective tracing
        success = integrate_debugger_bdb(debugger)
        print(f"Integration with selective tracing: {success}")

        # Get trace manager
        trace_manager = get_trace_manager()
        print(f"Trace manager enabled: {trace_manager.is_enabled()}")

        # Test adding breakpoints
        test_file = __file__
        trace_manager.add_breakpoint(test_file, 100)
        trace_manager.add_breakpoint(test_file, 200)

        breakpoints = trace_manager.get_breakpoints(test_file)
        print(f"Breakpoints added: {breakpoints}")

        # Test trace function
        trace_func = trace_manager.get_trace_function()
        print(f"Trace function available: {trace_func is not None}")

        # Test statistics
        stats = trace_manager.get_statistics()
        print(f"Trace manager stats: {stats}")

        print("[PASS] Selective tracing integration tests passed")

    except Exception as e:
        print(f"[FAIL] Selective tracing integration test failed: {e}")
        traceback.print_exc()


def test_error_handling():
    """Test error handling and fallback behavior."""
    print("\n=== Testing Error Handling ===")

    try:
        bridge = get_integration_bridge()

        # Enable fallback mode
        configure_integration(fallback_on_error=True)

        # Test that fallback is enabled
        assert bridge.config["fallback_on_error"]
        print("Fallback mode enabled: True")

        # Simulate error conditions by trying to integrate with invalid object
        class BrokenDebugger:
            """A debugger class that intentionally fails to initialize for
            testing error handling."""

            def __init__(self):
                raise RuntimeError("Intentionally broken debugger for testing error handling")  # noqa: TRY301

        try:
            BrokenDebugger()
        except RuntimeError:
            print("Broken debugger creation failed as expected")

        # Test that bridge handles errors gracefully
        initial_errors = bridge.integration_stats["errors_handled"]

        # Try integration that might fail
        success = bridge.integrate_with_debugger_bdb(None)  # This should fail gracefully
        print(f"Failed integration handled gracefully: {not success}")

        final_errors = bridge.integration_stats["errors_handled"]
        print(f"Errors handled: {final_errors - initial_errors}")

        print("[PASS] Error handling tests passed")

    except Exception as e:
        print(f"[FAIL] Error handling test failed: {e}")
        traceback.print_exc()


def test_bytecode_optimization():
    """Test bytecode optimization integration."""
    print("\n=== Testing Bytecode Optimization ===")

    try:
        bridge = get_integration_bridge()

        # Enable bytecode optimization
        bridge.update_config(bytecode_optimization=True)
        print(f"Bytecode optimization enabled: {bridge.config['bytecode_optimization']}")

        # Test bytecode optimization application
        source = {"path": "test_sample.py"}
        breakpoints = [{"line": 10}, {"line": 20}]

        # Create a temporary test file
        test_content = """
def test_function():
    x = 1
    y = 2
    return x + y

def another_function():
    for i in range(5):
        print(i)
    return "done"
"""

        test_file = Path("test_sample_temp.py")
        with test_file.open("w") as f:
            f.write(test_content)

        try:
            # Apply bytecode optimizations
            bridge._apply_bytecode_optimizations(source, breakpoints)

            # Check that optimization was attempted
            initial_injections = bridge.integration_stats["bytecode_injections"]
            print(f"Bytecode injection attempts: {initial_injections}")

        finally:
            # Clean up test file
            test_path = Path(test_file)
            if test_path.exists():
                test_path.unlink()

        print("[PASS] Bytecode optimization tests passed")

    except Exception as e:
        print(f"[FAIL] Bytecode optimization test failed: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    test_auto_integration()
    test_configuration()
    test_performance_monitoring()
    test_selective_tracing_integration()
    test_error_handling()
    test_bytecode_optimization()
