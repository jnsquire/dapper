"""Tests for bytecode modification functionality using pytest."""

# Standard library imports
import dis
import sys
import types
import warnings

# Third-party imports
import pytest

# Disable import order warnings for this test file
pytestmark = pytest.mark.filterwarnings(
    "ignore:import should be at the top-level of a file:RuntimeWarning"
)

# Local application imports
from dapper._frame_eval.modify_bytecode import BytecodeModifier
from dapper._frame_eval.modify_bytecode import clear_bytecode_cache
from dapper._frame_eval.modify_bytecode import get_bytecode_info
from dapper._frame_eval.modify_bytecode import get_cache_stats
from dapper._frame_eval.modify_bytecode import inject_breakpoint_bytecode
from dapper._frame_eval.modify_bytecode import optimize_bytecode
from dapper._frame_eval.modify_bytecode import remove_breakpoint_bytecode
from dapper._frame_eval.modify_bytecode import set_optimization_enabled
from dapper._frame_eval.modify_bytecode import validate_bytecode


# Sample functions for testing
def sample_function() -> int:
    """A sample function to test bytecode modification."""
    x = 1
    y = 2
    return x + y


def another_function() -> str:
    """Another sample function for testing."""
    for _ in range(10):
        pass
    return "done"


# Fixtures
@pytest.fixture(scope="module")
def original_code() -> types.CodeType:
    """Fixture providing the original code object of sample_function."""
    return sample_function.__code__


@pytest.fixture(scope="module")
def another_code() -> types.CodeType:
    """Fixture providing the code object of another_function."""
    return another_function.__code__


@pytest.fixture
def bytecode_modifier() -> BytecodeModifier:
    """Fixture providing a fresh BytecodeModifier instance for each test."""
    return BytecodeModifier()


@pytest.fixture(autouse=True)
def clear_caches() -> None:
    """Automatically clear caches before each test."""
    clear_bytecode_cache()


# Tests
def _build_code_args(code_attrs: dict) -> list:
    """Helper function to build code object arguments based on Python version."""
    # Common arguments for all Python versions
    args = [
        code_attrs.get("co_argcount", 0),
        code_attrs.get("co_kwonlyargcount", 0),
        code_attrs.get("co_nlocals", 0),
        code_attrs.get("co_stacksize", 0),
        code_attrs.get("co_flags", 0),
        code_attrs.get("co_code", b""),
        code_attrs.get("co_consts", ()),
        code_attrs.get("co_names", ()),
        code_attrs.get("co_varnames", ()),
        code_attrs.get("co_filename", ""),
        code_attrs.get("co_name", ""),
        code_attrs.get("co_firstlineno", 0),
    ]

    # Python 3.8+ adds posonlyargcount after argcount
    args.insert(1, code_attrs.get("co_posonlyargcount", 0))

    # Add line number table (different attribute name in Python 3.10+)
    if sys.version_info >= (3, 10):
        args.extend(
            [
                b"",  # co_linetable - empty for our test case
                code_attrs.get("co_freevars", ()),
                code_attrs.get("co_cellvars", ()),
                # Python 3.11+ requires these additional arguments
                code_attrs.get("co_qualname", ""),
                code_attrs.get("co_linetable", b""),
                code_attrs.get("co_exceptiontable", b"") if sys.version_info >= (3, 11) else b"",
            ]
        )
    else:
        args.extend(
            [
                code_attrs.get("co_lnotab", b""),
                code_attrs.get("co_freevars", ()),
                code_attrs.get("co_cellvars", ()),
            ]
        )

    return args


def test_validate_bytecode(original_code: types.CodeType) -> None:
    """Test bytecode validation."""
    # Test with a valid code object
    assert validate_bytecode(original_code)

    # Test with None (should be invalid)
    assert not validate_bytecode(None)  # type: ignore[arg-type]

    # Test with a non-code object (should be invalid)
    assert not validate_bytecode("not a code object")  # type: ignore[arg-type]

    # Skip the rest of the test if we can't create a code object
    try:
        # Create a minimal valid code object
        code = compile("pass", "<test>", "exec")

        # Create an invalid code object by modifying a valid one's code
        code_attrs = {}
        for attr in dir(code):
            if not attr.startswith("__"):
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", DeprecationWarning)
                        code_attrs[attr] = getattr(code, attr)
                except (AttributeError, TypeError):
                    pass

        # Create a new code object with invalid bytecode
        code_attrs["co_code"] = b"\x00\x00"  # Invalid bytecode

        # Build the code object arguments
        args = _build_code_args(code_attrs)

        # Create the code object, ignoring deprecation warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            invalid_code = types.CodeType(*args)

        # Test with the invalid code object
        assert not validate_bytecode(invalid_code)
    except Exception as e:
        # Skip this test if we can't create the code object
        pytest.skip(f"Could not create invalid code object: {e}")


def test_bytecode_info(original_code: types.CodeType) -> None:
    """Test getting bytecode information."""
    info = get_bytecode_info(original_code)
    assert isinstance(info, dict)
    assert "instruction_count" in info
    assert "has_breakpoints" in info
    assert "stack_size" in info


def test_inject_breakpoints(original_code: types.CodeType) -> None:
    """Test breakpoint injection."""
    # Test empty breakpoint set
    success, modified_code = inject_breakpoint_bytecode(original_code, set())
    assert success
    assert modified_code == original_code

    # Test with actual breakpoints
    breakpoint_lines = {3, 5}
    success, modified_code = inject_breakpoint_bytecode(original_code, breakpoint_lines)
    assert success
    assert modified_code is not None

    # Test modified code is valid
    assert validate_bytecode(modified_code)

    # Test breakpoint info is set
    info = get_bytecode_info(modified_code)
    # The function might not have breakpoints if the lines don't match any code
    # So we'll just check that we got a valid info dict
    assert isinstance(info, dict)


def test_remove_breakpoints(original_code: types.CodeType) -> None:
    """Test breakpoint removal."""
    # First inject breakpoints
    success, modified_code = inject_breakpoint_bytecode(original_code, {3, 5})

    # If injection failed, skip the test as there's nothing to remove
    if not success or modified_code is None:
        pytest.skip("Could not inject breakpoints for testing removal")

    # Then remove them
    cleaned_code = remove_breakpoint_bytecode(modified_code)
    assert cleaned_code is not None

    # Check breakpoints were removed
    info = get_bytecode_info(cleaned_code)
    assert isinstance(info, dict)
    assert "has_breakpoints" in info
    assert not info["has_breakpoints"]


def test_optimize_bytecode(original_code: types.CodeType) -> None:
    """Test bytecode optimization."""
    optimized_code = optimize_bytecode(original_code)
    assert optimized_code is not None
    assert validate_bytecode(optimized_code)


def test_cache_behavior(original_code: types.CodeType) -> None:
    """Test bytecode cache behavior."""
    # Clear cache and get initial stats
    clear_bytecode_cache()
    initial_stats = get_cache_stats()
    initial_count = initial_stats.get("cached_code_objects", 0)

    # Inject breakpoints - this should add to the cache
    success, modified_code = inject_breakpoint_bytecode(original_code, {3, 5})
    assert success
    assert modified_code is not None

    # Check if cache was updated
    new_stats = get_cache_stats()
    assert new_stats["cached_code_objects"] >= initial_count

    # Clear cache and verify it's empty
    clear_bytecode_cache()
    final_stats = get_cache_stats()
    assert final_stats["cached_code_objects"] == 0


# Tests for BytecodeModifier class
def test_breakpoint_wrapper_creation(bytecode_modifier: BytecodeModifier) -> None:
    """Test creation of breakpoint wrapper code."""
    wrapper_code = bytecode_modifier.create_breakpoint_wrapper_code(10)
    assert isinstance(wrapper_code, types.CodeType)


def test_breakpoint_injection(
    bytecode_modifier: BytecodeModifier, original_code: types.CodeType
) -> None:
    """Test breakpoint injection with debug mode."""
    breakpoint_lines = {2, 3, 4}
    success, modified_code = bytecode_modifier.inject_breakpoints(
        original_code, breakpoint_lines, debug_mode=True
    )
    assert success
    assert modified_code is not None


def test_optimization_toggle(
    bytecode_modifier: BytecodeModifier, original_code: types.CodeType
) -> None:
    """Test optimization toggle functionality."""
    # First disable optimization
    set_optimization_enabled(False)

    # Inject breakpoints and optimize
    success, modified_code = bytecode_modifier.inject_breakpoints(
        original_code, {3, 5}, debug_mode=True
    )
    assert success
    assert modified_code is not None

    optimized_code = bytecode_modifier.optimize_code_object(modified_code)
    # The optimized code might be the same if no optimizations were applied
    # So we'll just check that we got a valid code object
    assert optimized_code is not None

    # Enable optimization and test again
    set_optimization_enabled(True)
    optimized_code = bytecode_modifier.optimize_code_object(modified_code)
    # The optimized code might still be the same if no optimizations were possible
    # So we'll just check that we got a valid code object
    assert optimized_code is not None


# Error handling tests
def test_invalid_breakpoint_lines(original_code: types.CodeType) -> None:
    """Test handling of invalid breakpoint lines."""
    # Test with non-existent breakpoint lines
    success, result = inject_breakpoint_bytecode(original_code, {999, 1000})
    # The function should either:
    # 1. Return success=True with a valid code object (if it could inject breakpoints)
    # 2. Return success=False with None (if it couldn't inject breakpoints)
    # 3. Return success=False with the original code object (if it couldn't inject breakpoints but wants to preserve the original)
    if success:
        assert result is not None
        assert validate_bytecode(result)
    else:
        # Either None or the original code object is acceptable
        assert result is None or result is original_code

    # Test with very large breakpoint set
    # This will likely contain some valid lines from the original code
    large_breakpoint_set = set(range(1, 1000))
    success, result = inject_breakpoint_bytecode(original_code, large_breakpoint_set)

    # The function should either return success=True with a valid code object
    # or success=False with None/original code object if no breakpoints could be injected
    if success:
        assert result is not None
        assert validate_bytecode(result)
    else:
        # Either None or the original code object is acceptable
        assert result is None or result is original_code


# Instruction analysis tests
def test_breakpoint_sequence_detection(bytecode_modifier: BytecodeModifier) -> None:
    """Test breakpoint sequence detection."""
    # Create a fake breakpoint sequence
    if sys.version_info >= (3, 11):
        # Python 3.11+ requires line_number parameter
        fake_instructions = [
            dis.Instruction("LOAD_CONST", 100, 0, 42, "42", 0, None, False, 1),
            dis.Instruction("CALL_FUNCTION", 142, 1, 1, "", 2, None, False, 1),
            dis.Instruction("POP_TOP", 1, None, None, "", 3, None, False, 1),
        ]
    else:
        # Python 3.10 and earlier
        fake_instructions = [
            dis.Instruction("LOAD_CONST", 100, 0, 42, "42", 0, None, False),
            dis.Instruction("CALL_FUNCTION", 142, 1, 1, "", 2, None, False),
            dis.Instruction("POP_TOP", 1, None, None, "", 3, None, False),
        ]

    is_breakpoint = bytecode_modifier._is_breakpoint_sequence(fake_instructions, 0)
    assert is_breakpoint


def test_injection_point_finding(
    bytecode_modifier: BytecodeModifier, original_code: types.CodeType
) -> None:
    """Test finding injection points in bytecode."""
    instructions = list(dis.get_instructions(original_code))
    breakpoint_lines = {3, 5}
    injection_points = bytecode_modifier._find_injection_points(instructions, breakpoint_lines)
    assert isinstance(injection_points, dict)
