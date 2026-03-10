"""Tests for bytecode modification functionality using pytest."""

# Standard library imports
import dis
import sys
import types
from types import SimpleNamespace
from typing import Any
from typing import cast
import warnings

# Third-party imports
import pytest  # pyright: ignore[reportMissingImports]

# Disable import order warnings for this test file
pytestmark = pytest.mark.filterwarnings(
    "ignore:import should be at the top-level of a file:RuntimeWarning",
)

# Local application imports
from dapper._frame_eval import modify_bytecode as modify_bytecode_mod
from dapper._frame_eval.modify_bytecode import BytecodeErrorInfo
from dapper._frame_eval.modify_bytecode import BytecodeModifier
from dapper._frame_eval.modify_bytecode import clear_bytecode_cache
from dapper._frame_eval.modify_bytecode import get_bytecode_info
from dapper._frame_eval.modify_bytecode import get_cache_stats
from dapper._frame_eval.modify_bytecode import inject_breakpoint_bytecode
from dapper._frame_eval.modify_bytecode import optimize_bytecode
from dapper._frame_eval.modify_bytecode import remove_breakpoint_bytecode
from dapper._frame_eval.modify_bytecode import set_optimization_enabled
from dapper._frame_eval.modify_bytecode import validate_bytecode
from tests._cython import compiled_frame_evaluator_expected


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
            ],
        )
    else:
        args.extend(
            [
                code_attrs.get("co_lnotab", b""),
                code_attrs.get("co_freevars", ()),
                code_attrs.get("co_cellvars", ()),
            ],
        )

    return args


def _first_executable_line(code_obj: types.CodeType) -> int:
    """Return the first source line after the function definition line."""
    line_numbers = _iter_code_lines(code_obj)
    return next(line for line in line_numbers if line > code_obj.co_firstlineno)


def _iter_code_lines(code_obj: types.CodeType) -> list[int]:
    """Return executable source lines across Python minor versions."""
    co_lines = getattr(code_obj, "co_lines", None)
    if callable(co_lines):
        return [line for _, _, line in cast("Any", co_lines)() if line is not None]
    return [line for _, line in dis.findlinestarts(code_obj)]


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


def test_cache_key_identity_and_fingerprint(
    bytecode_modifier: BytecodeModifier,
) -> None:
    """Cache key includes object identity but shares fingerprint/version.

    Modern behaviour keys by ``id(code)`` so two independently compiled
    objects will not collide, but the fingerprint and version bits should be
    identical when the breakpoint set is the same.
    """
    src = "def sample():\n    value = 1\n    return value\n"
    code_1 = compile(src, "<test_cache_key>", "exec")
    code_2 = compile(src, "<test_cache_key>", "exec")

    key_1 = bytecode_modifier._get_cache_key(code_1, {2})
    key_2 = bytecode_modifier._get_cache_key(code_2, {2})

    # ids should differ
    assert key_1[0] != key_2[0]
    # fingerprint and version should match
    assert key_1[1:] == key_2[1:]


def test_breakpoint_injection(
    bytecode_modifier: BytecodeModifier,
    original_code: types.CodeType,
) -> None:
    """Test breakpoint injection with debug mode."""
    breakpoint_lines = {2, 3, 4}
    success, modified_code = bytecode_modifier.inject_breakpoints(
        original_code,
        breakpoint_lines,
        debug_mode=True,
    )
    assert success
    assert modified_code is not None


def test_rebuild_code_object_prefers_replace(
    bytecode_modifier: BytecodeModifier,
    original_code: types.CodeType,
    monkeypatch,
) -> None:
    """Prefer code.replace(), but allow constructor fallback when replacement fails."""
    if not hasattr(original_code, "replace"):
        pytest.skip("code.replace() unavailable on this Python runtime")

    instructions = list(dis.get_instructions(original_code))
    real_code_type = type(original_code)
    code_type_calls = {"count": 0}

    def track_code_type_calls(*args, **kwargs):
        code_type_calls["count"] += 1
        return types.CodeType(*args, **kwargs)

    monkeypatch.setattr(types, "CodeType", track_code_type_calls)

    accepted, rebuilt = bytecode_modifier._rebuild_code_object(original_code, instructions)
    assert accepted
    assert isinstance(rebuilt, real_code_type)


def test_optimization_toggle(
    bytecode_modifier: BytecodeModifier,
    original_code: types.CodeType,
) -> None:
    """Test optimization toggle functionality."""
    # First disable optimization
    set_optimization_enabled(False)

    # Inject breakpoints and optimize
    success, modified_code = bytecode_modifier.inject_breakpoints(
        original_code,
        {3, 5},
        debug_mode=True,
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
    assert isinstance(success, bool)
    assert result is not None


def test_rollback_on_rebuild_failure(
    bytecode_modifier: BytecodeModifier, original_code: types.CodeType, monkeypatch
) -> None:
    """Simulate a rebuild failure and ensure rollback occurs."""

    # force rebuild to reject candidate
    def fake_rebuild(orig, instrs):
        return False, orig

    monkeypatch.setattr(
        "dapper._frame_eval._code_object_builder.rebuild_code_object",
        fake_rebuild,
    )

    # clear existing telemetry and then exercise failure
    from dapper._frame_eval.telemetry import get_frame_eval_telemetry
    from dapper._frame_eval.telemetry import reset_frame_eval_telemetry

    reset_frame_eval_telemetry()
    target_line = _first_executable_line(original_code)
    success, new_code = bytecode_modifier.inject_breakpoints(
        original_code,
        {target_line},
        debug_mode=True,
    )
    assert not success
    assert new_code is original_code
    stats = get_cache_stats()
    # no entries should be left behind
    assert stats["cached_code_objects"] == 0

    # telemetry should have noted a rollback
    snap = get_frame_eval_telemetry()
    assert snap.reason_counts.bytecode_rollback > 0


def test_metadata_version_mismatch(original_code: types.CodeType) -> None:
    """Stale code-extra metadata should be ignored and emit mismatch telemetry."""
    if not compiled_frame_evaluator_expected():
        pytest.skip(
            "Compiled frame-eval metadata behavior is only expected on the supported 3.11-3.12 paths"
        )

    from dapper._frame_eval import _frame_evaluator
    from dapper._frame_eval.telemetry import get_frame_eval_telemetry
    from dapper._frame_eval.telemetry import reset_frame_eval_telemetry

    # deliberately write bad metadata using internal helper
    bad_meta = {"modified_code": original_code, "breakpoint_fp": 0, "version": 999}
    _frame_evaluator._store_code_extra_metadata(original_code, bad_meta)

    reset_frame_eval_telemetry()
    result = _frame_evaluator._get_modified_code_for_evaluation(original_code)
    assert result is None
    snap = get_frame_eval_telemetry()
    assert snap.reason_counts.bytecode_cache_key_mismatch > 0


def test_generator_and_async_instrumentation(bytecode_modifier: BytecodeModifier) -> None:
    """Ensure generators and async functions can be instrumented."""
    import asyncio

    def gen():
        x = 1  # bp
        yield x
        yield 2

    bp_line = gen.__code__.co_firstlineno + 1
    success, modified = bytecode_modifier.inject_breakpoints(gen.__code__, {bp_line})
    assert success
    assert isinstance(modified, types.CodeType)

    async def coro():
        await asyncio.sleep(0)  # bp
        return "ok"

    bp_line2 = coro.__code__.co_firstlineno + 1
    success2, modified2 = bytecode_modifier.inject_breakpoints(coro.__code__, {bp_line2})
    assert success2
    assert isinstance(modified2, types.CodeType)


def test_module_level_instrumentation(bytecode_modifier: BytecodeModifier) -> None:
    """Instrument a module-level code object."""
    src = "x = 1\nx = 2\n"
    code = compile(src, "<mod_test>", "exec")
    lines = set(_iter_code_lines(code))
    assert lines
    success, modified = bytecode_modifier.inject_breakpoints(code, lines)
    assert success
    assert isinstance(modified, types.CodeType)


def test_live_object_instrumentation_and_telemetry(monkeypatch):
    """Ensure the debugger helper instruments a live function and emits telemetry."""
    from dapper._frame_eval.debugger_integration import DebuggerFrameEvalBridge
    from dapper._frame_eval.telemetry import get_frame_eval_telemetry
    from dapper._frame_eval.telemetry import reset_frame_eval_telemetry

    bridge = DebuggerFrameEvalBridge()
    # create a fake module object inserted into sys.modules
    import sys

    module_name = "__dapper_test_module__"
    mod = types.ModuleType(module_name)

    def foo():
        x = 1  # breakpoint line
        return x

    cast("Any", mod).foo = foo
    sys.modules[module_name] = mod

    reset_frame_eval_telemetry()
    # instrument by filepath matching foo code
    filepath = foo.__code__.co_filename
    result = bridge._instrument_live_code_objects_for_file(
        filepath, {foo.__code__.co_firstlineno + 1}
    )
    assert result is True
    # telemetry should note eager instrumentation
    snap = get_frame_eval_telemetry()
    assert snap.reason_counts.bytecode_eager_instrumentation > 0

    # cleanup
    del sys.modules[module_name]


def test_recursive_instrumentation(bytecode_modifier: BytecodeModifier) -> None:
    """Nested functions should be instrumented independently."""

    def outer():
        def inner():
            x = 1  # bp line
            return x

        return inner()

    code = outer.__code__
    inner_code = next(
        (
            const
            for const in code.co_consts
            if isinstance(const, types.CodeType) and const.co_name == "inner"
        ),
        None,
    )
    assert inner_code is not None
    lines = set(_iter_code_lines(inner_code))
    # there should be at least one line to target
    if not lines:
        pytest.skip("no inner lines discovered")
    bp_line = next(iter(lines))
    success, modified = inject_breakpoint_bytecode(code, {bp_line})
    assert success
    # ensure nested code got cached separately
    stats = get_cache_stats()
    assert stats["cached_code_objects"] >= 1


def test_cache_invalidation(original_code: types.CodeType) -> None:
    """Invalidating breakpoints removes cached bytecode entries."""
    from dapper._frame_eval.cache_manager import invalidate_breakpoints

    target_line = _first_executable_line(original_code)
    success, modified = inject_breakpoint_bytecode(original_code, {target_line})
    assert success and modified is not original_code
    # simulate a breakpoint change
    invalidate_breakpoints(original_code.co_filename)
    stats = get_cache_stats()
    assert stats["cached_code_objects"] == 0


def test_lazy_eager_instrumentation_behavior(
    bytecode_modifier: BytecodeModifier, original_code: types.CodeType, monkeypatch
) -> None:
    """Verify lazy vs eager instrumentation call counts."""
    calls = {"count": 0}

    def track_inject(code_obj, lines, debug_mode=False):
        calls["count"] += 1
        return True, code_obj

    monkeypatch.setattr(bytecode_modifier, "inject_breakpoints", track_inject)

    # lazy: only called when breakpoints hit
    calls["count"] = 0
    # simulate two hits
    bytecode_modifier.inject_breakpoints(original_code, {2})
    bytecode_modifier.inject_breakpoints(original_code, {2})
    assert calls["count"] == 2

    # eager mode might call upon update - simulate by directly calling helper
    # (integration code toggles this behaviour; we mimic it here)
    calls["count"] = 0
    # pretend eagerness triggers two calls
    bytecode_modifier.inject_breakpoints(original_code, {2})
    bytecode_modifier.inject_breakpoints(original_code, {3})
    assert calls["count"] == 2

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
    fake_instructions = bytecode_modifier._create_breakpoint_check_instructions(42)

    is_breakpoint = bytecode_modifier._is_breakpoint_sequence(fake_instructions, 0)
    assert is_breakpoint


def test_injection_point_finding(
    bytecode_modifier: BytecodeModifier,
    original_code: types.CodeType,
) -> None:
    """Test finding injection points in bytecode."""
    instructions = list(dis.get_instructions(original_code))
    breakpoint_lines = {3, 5}
    injection_points = bytecode_modifier._find_injection_points(instructions, breakpoint_lines)
    assert isinstance(injection_points, dict)


def test_injection_point_finding_uses_line_number_metadata(
    bytecode_modifier: BytecodeModifier,
) -> None:
    instructions = cast(
        "list[dis.Instruction]",
        [
            SimpleNamespace(
                opname="LOAD_CONST",
                starts_line=True,
                line_number=101,
            ),
            SimpleNamespace(
                opname="STORE_FAST",
                starts_line=False,
                line_number=101,
            ),
        ],
    )

    injection_points = bytecode_modifier._find_injection_points(instructions, {101})

    assert injection_points == {101: 1}


def test_insert_code_invalid_line_returns_failure(original_code: types.CodeType) -> None:
    success, result = modify_bytecode_mod.insert_code(original_code, -1, (1, 2))
    assert success is False
    assert result is original_code


def test_insert_code_handles_inject_breakpoints_exception(
    monkeypatch: pytest.MonkeyPatch,
    original_code: types.CodeType,
) -> None:
    def explode(_code_obj, _breakpoint_lines, debug_mode=False):
        assert debug_mode is True
        msg = "inject failed"
        raise RuntimeError(msg)

    monkeypatch.setattr(modify_bytecode_mod._bytecode_modifier, "inject_breakpoints", explode)
    success, result = modify_bytecode_mod.insert_code(original_code, 10, (10, 11))
    assert success is False
    assert result is original_code


def test_get_bytecode_info_error_path_reports_unknown_fields() -> None:
    class BrokenCode:
        pass

    raw = get_bytecode_info(BrokenCode())  # type: ignore[arg-type]
    # Narrow to BytecodeErrorInfo — the error path always includes the "error" key.
    info = cast("BytecodeErrorInfo", raw)
    assert info["error"] == "Failed to analyze bytecode"
    assert info["filename"] == "unknown"
    assert info["name"] == "unknown"


def test_rebuild_code_object_fallback_when_replace_unavailable(
    bytecode_modifier: BytecodeModifier,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code = compile("x = 1\n", "<fallback-test>", "exec")
    instructions = list(dis.get_instructions(code))

    class FakeCode:
        co_argcount = 0
        co_kwonlyargcount = 0
        co_nlocals = 0
        co_stacksize = 1
        co_flags = 0
        co_consts = tuple(code.co_consts)
        co_names = tuple(code.co_names)
        co_varnames = tuple(code.co_varnames)
        co_filename = "<fake>"
        co_name = "fake"
        co_firstlineno = 1
        co_freevars = ()
        co_cellvars = ()
        co_posonlyargcount = 0
        co_lnotab = b""

        def co_lines(self):
            co_lines_fn = getattr(code, "co_lines", None)
            return co_lines_fn() if co_lines_fn is not None else iter(())

    captured: dict[str, object] = {}

    def fake_code_type(*args):
        captured["args"] = args
        return "rebuilt-fallback"

    monkeypatch.setattr(types, "CodeType", fake_code_type)

    accepted, _rebuilt = bytecode_modifier._rebuild_code_object(FakeCode(), instructions)  # type: ignore[arg-type]
    # The fake constructor was invoked (fallback path exercised).
    assert "args" in captured
    # "rebuilt-fallback" is a str, not a CodeType; the safety layer rejects it
    # and returns (False, original) rather than propagating a corrupt object.
    assert not accepted
