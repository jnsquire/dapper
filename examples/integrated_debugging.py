"""
Example: Using Dapper AI Debugger from Within a Process

This example demonstrates how to integrate the Dapper AI debugger directly
into a Python program, allowing you to add debugging capabilities without
needing to launch the program through an external debug adapter.

This is useful for:
- Adding debugging to long-running applications
- Creating custom debug interfaces
- Integrating debugging into existing applications
- Testing debugging functionality programmatically

The example shows:
1. Basic debugger integration
2. Setting breakpoints programmatically
3. Handling debug events
4. Inspecting variables during execution
5. Controlling execution flow
"""

import asyncio
import logging
import sys
import time

from dapper.debug_launcher import DebuggerBDB

# Module level logger for examples
logger = logging.getLogger(__name__)

# Named constant to avoid magic numbers in examples
MAGIC_EXCEPTION_INDEX = 2

# Import the debugger components


class DebugEventHandler:
    """
    Example event handler for debug events.
    In a real application, this might send events to a UI or log them.
    """

    def __init__(self):
        self.events = []
        self.breakpoints_hit = 0

    def on_breakpoint_hit(self, frame, filename: str, line: int):
        """Called when a breakpoint is hit"""
        logger = logging.getLogger(__name__)
        logger.debug("Breakpoint hit at %s:%s", filename, line)
        self.breakpoints_hit += 1

        # Get local variables
        locals_info = frame.f_locals
        logger.info(f"   Local variables: {list(locals_info.keys())}")

        # You could inspect specific variables here
        if "counter" in locals_info:
            logger.info(f"   counter = {locals_info['counter']}")

    def on_step(self, _frame, filename: str, line: int):
        """Called when stepping through code"""
        logger = logging.getLogger(__name__)
        logger.info("👣 Step at %s:%s", filename, line)

    def on_function_call(self, _frame, filename: str, line: int, func_name: str):
        """Called when entering a function"""
        logger.info("📞 Function call: %s at %s:%s", func_name, filename, line)

    def on_function_return(self, _frame, filename: str, line: int, func_name: str, return_value):
        """Called when returning from a function"""
        logger.info("↩️ Function return: %s at %s:%s", func_name, filename, line)
        logger.info("   Returned: %r", return_value)

    def on_exception(self, _frame, exc_type, exc_value, filename: str, line: int):
        """Called when an exception occurs"""
        exc_msg = f"{exc_type.__name__}: {exc_value}"
        logger.info(f"💥 Exception at {filename}:{line}: {exc_msg}")


class IntegratedDebugger(DebuggerBDB):
    """
    Extended debugger that integrates with the application.
    """

    def __init__(self, event_handler=None):
        super().__init__()
        self.event_handler = event_handler or DebugEventHandler()

    def set_custom_breakpoint(self, filename: str, line: int, condition=None):
        """Set a breakpoint programmatically"""
        # Use the base class method
        super().set_custom_breakpoint(filename, line, condition)

        bp_msg = f"✓ Set custom breakpoint at {filename}:{line}"
        if condition:
            bp_msg += f" (condition: {condition})"
        logger.info(bp_msg)

    def set_current_file(self, filename: str):
        """Set the current file for filename mapping"""
        self.current_file = filename

    def clear_custom_breakpoint(self, filename: str, line: int):
        """Clear a specific breakpoint"""
        if filename in self.custom_breakpoints and line in self.custom_breakpoints[filename]:
            del self.custom_breakpoints[filename][line]
            logger.info(f"❌ Cleared breakpoint at {filename}:{line}")

            # Also clear from BDB
            self.clear_break(filename, line)

    def clear_all_custom_breakpoints(self):
        """Clear all custom breakpoints"""
        self.custom_breakpoints.clear()
        logger.info("🧹 Cleared all custom breakpoints")

        # Also clear from BDB
        self.clear_all_breaks()

    def continue_execution(self):
        """Continue execution until next breakpoint"""
        logger.info("▶️ Continuing execution...")
        self.set_continue()

    def step_into(self):
        """Step into the next function call"""
        logger.info("👣 Stepping into...")
        self.set_step()

    def step_over(self):
        """Step over to the next line"""
        logger.info("⏭️ Stepping over...")
        if self.current_frame:
            self.set_next(self.current_frame)

    def step_out(self):
        """Step out of the current function"""
        logger.info("↗️ Stepping out...")
        if self.current_frame:
            self.set_return(self.current_frame)

    def start_tracing(self):
        """Start tracing execution"""
        logger.info("🔍 Starting trace...")
        self.set_trace()

    def stop_tracing(self):
        """Stop tracing execution"""
        logger.info("⏹️ Stopping trace...")
        self.set_quit()

    def user_line(self, frame):
        """Override to add custom breakpoint handling"""
        filename = frame.f_code.co_filename
        line = frame.f_lineno

        # Handle filename mapping for code executed as string
        if filename == "<string>":
            # Map <string> back to the actual file path
            if self.current_file:
                filename = self.current_file
            else:
                # Try to find the file from the frame's globals
                main_file = frame.f_globals.get("__file__")
                if main_file:
                    filename = main_file
                    self.current_file = main_file

        # Check if we're at a breakpoint set by BDB
        if self.get_break(filename, line):
            # This is a breakpoint that was hit
            self.event_handler.on_breakpoint_hit(frame, filename, line)
            # Don't call super().user_line() to avoid double processing
            return

        # Check if we're at a custom breakpoint
        if (
            hasattr(self, "custom_breakpoints")
            and filename in self.custom_breakpoints
            and line in self.custom_breakpoints[filename]
        ):
            condition = self.custom_breakpoints[filename][line]
            if condition:
                # Evaluate the condition in the current frame
                try:
                    if eval(condition, frame.f_globals, frame.f_locals):
                        logger.info(
                            "🔴 Conditional breakpoint hit at "
                            f"{filename}:{line} (condition: {condition})"
                        )
                        self.event_handler.on_breakpoint_hit(frame, filename, line)
                        return
                except Exception:
                    # If condition evaluation fails, don't trigger breakpoint
                    pass
            else:
                logger.info(f"🔴 Breakpoint hit at {filename}:{line}")
                self.event_handler.on_breakpoint_hit(frame, filename, line)
                return

        # Call parent implementation for standard debugging
        super().user_line(frame)

    def user_call(self, frame, argument_list=None):
        """Called when entering a function"""
        filename = frame.f_code.co_filename
        line = frame.f_lineno
        func_name = frame.f_code.co_name

        self.event_handler.on_function_call(frame, filename, line, func_name)

        # Call parent implementation
        super().user_call(frame, argument_list)

    def user_return(self, frame, return_value):
        """Called when returning from a function"""
        filename = frame.f_code.co_filename
        line = frame.f_lineno
        func_name = frame.f_code.co_name

        self.event_handler.on_function_return(frame, filename, line, func_name, return_value)

        # Call parent implementation
        super().user_return(frame, return_value)

    def user_exception(self, frame, exc_info):
        """Override to handle exceptions"""
        exc_type, exc_value, _ = exc_info
        filename = frame.f_code.co_filename
        line = frame.f_lineno

        handler = self.event_handler
        handler.on_exception(frame, exc_type, exc_value, filename, line)

        # Call parent implementation
        super().user_exception(frame, exc_info)


def example_function():
    """Example function to debug"""
    logger.info("Starting example function...")

    counter = 0
    data = []

    for i in range(5):
        counter += 1
        data.append(f"item_{i}")
        logger.info(f"Loop iteration {i}, counter = {counter}")

        # Simulate some work
        time.sleep(0.1)

    logger.info(f"Function completed. Final counter: {counter}")
    return data


def complex_example():
    """More complex example with nested functions and error handling"""
    logger.info("Starting complex example...")

    def nested_function(value):
        result = value * 2
        logger.info(f"Nested function: {value} * 2 = {result}")
        return result

    try:
        items = []
        for i in range(3):
            if i == MAGIC_EXCEPTION_INDEX:
                # This will cause an exception
                result = nested_function("not_a_number")  # TypeError
            else:
                result = nested_function(i)
            items.append(result)

        logger.info(f"Complex example completed: {items}")

    except Exception as e:
        logger.info(f"Caught exception: {e}")
        return None

    return items


async def main():
    """
    Main example demonstrating integrated debugging
    """
    logger.info("🚀 Dapper AI Integrated Debugger Example")
    logger.info("=" * 50)

    # Create event handler
    event_handler = DebugEventHandler()

    # Create integrated debugger
    debugger = IntegratedDebugger(event_handler)

    # Set some custom breakpoints
    logger.info("\n📍 Setting custom breakpoints...")

    # Get the current file path for breakpoints
    current_file = __file__

    # Set breakpoint at the start of example_function
    debugger.set_custom_breakpoint(current_file, 244)

    # Set conditional breakpoint in the loop
    debugger.set_custom_breakpoint(current_file, 248, "counter == 3")

    # Set breakpoint in complex_example
    debugger.set_custom_breakpoint(current_file, 263)

    logger.info("\n🔧 Starting debugging session...")

    # Run the first example with debugging
    logger.info("\n%s EXAMPLE 1 %s", "=" * 30, "=" * 30)
    debugger.set_current_file(current_file)
    # Start tracing before calling the function
    debugger.set_trace()
    try:
        example_function()
    finally:
        debugger.set_quit()

    # Run the second example with debugging
    logger.info("\n%s EXAMPLE 2 %s", "=" * 30, "=" * 30)
    debugger.set_current_file(current_file)
    # Start tracing before calling the function
    debugger.set_trace()
    try:
        complex_example()
    finally:
        debugger.set_quit()

    logger.info("\n%s", "=" * 50)
    logger.info("📊 Debug Session Summary:")
    logger.info(f"   Breakpoints hit: {event_handler.breakpoints_hit}")
    logger.info("✅ Debugging session completed!")


def run_without_debugging():
    """
    Run the examples without debugging for comparison
    """
    logger.info("🔧 Running examples WITHOUT debugging...")

    logger.info("\n%s EXAMPLE 1 %s", "=" * 30, "=" * 30)
    result1 = example_function()

    logger.info("\n%s EXAMPLE 2 %s", "=" * 30, "=" * 30)
    result2 = complex_example()

    logger.info(f"\nResults: {result1}, {result2}")


def demo_advanced_features():
    """Demonstrate advanced debugging features"""
    logger.info("🔧 Demonstrating Advanced Debugging Features")
    logger.info("=" * 50)

    # Create event handler and debugger
    event_handler = DebugEventHandler()
    debugger = IntegratedDebugger(event_handler)

    # Set some breakpoints
    current_file = __file__
    debugger.set_custom_breakpoint(current_file, 133)  # example_function
    debugger.set_custom_breakpoint(current_file, 152)  # complex_example

    logger.info("\n📋 Available debugging commands:")
    logger.info("  - debugger.continue_execution() - Continue until next breakpoint")
    logger.info("  - debugger.step_into() - Step into function calls")
    logger.info("  - debugger.step_over() - Step over to next line")
    logger.info("  - debugger.step_out() - Step out of current function")
    logger.info("  - debugger.clear_custom_breakpoint(file, line) - Clear bp")
    logger.info("  - debugger.clear_all_custom_breakpoints() - Clear all bp")
    logger.info("  - debugger.start_tracing() - Start execution tracing")
    logger.info("  - debugger.stop_tracing() - Stop execution tracing")

    logger.info("\n🎯 Running with enhanced debugging...")

    # Run example with enhanced debugging
    debugger.run("example_function()")
    debugger.run("complex_example()")

    logger.info("\n📊 Final Summary:")
    logger.info(f"   Breakpoints hit: {event_handler.breakpoints_hit}")
    logger.info("✅ Enhanced debugging demonstration complete!")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--no-debug":
        # Run without debugging for comparison
        run_without_debugging()
    elif len(sys.argv) > 1 and sys.argv[1] == "--advanced":
        # Run with advanced debugging features
        asyncio.run(main())
    else:
        # Run with integrated debugging
        asyncio.run(main())
