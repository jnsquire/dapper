import types

from dapper._frame_eval import modify_bytecode as mb


def test_is_breakpoint_sequence_and_length():
    instrs = [
        mb._make_instruction(
            opname="LOAD_CONST",
            opcode=mb.LOAD_CONST,
            arg=0,
            argval=123,
            argrepr="123",
            offset=0,
            starts_line=None,
            is_jump_target=False,
        ),
        mb._make_instruction(
            opname="CALL_FUNCTION",
            opcode=mb.CALL_FUNCTION,
            arg=1,
            argval=1,
            argrepr="",
            offset=2,
            starts_line=None,
            is_jump_target=False,
        ),
        mb._make_instruction(
            opname="POP_TOP",
            opcode=mb.POP_TOP,
            arg=None,
            argval=None,
            argrepr="",
            offset=4,
            starts_line=None,
            is_jump_target=False,
        ),
    ]

    assert mb._bytecode_modifier._is_breakpoint_sequence(instrs, 0) is True
    assert mb._bytecode_modifier._get_breakpoint_sequence_length(instrs, 0) == 3

    # Non-matching sequence
    instrs2 = list(instrs)
    instrs2[1] = instrs2[1]._replace(opname="NOP", opcode=0)
    assert mb._bytecode_modifier._is_breakpoint_sequence(instrs2, 0) is False
    assert mb._bytecode_modifier._get_breakpoint_sequence_length(instrs2, 0) == 1


def test_create_breakpoint_wrapper_code_and_compile_returns_codeobj():
    codeobj = mb._bytecode_modifier.create_breakpoint_wrapper_code(7)
    assert isinstance(codeobj, types.CodeType)


def test_get_bytecode_info_handles_invalid_input():
    res = mb.get_bytecode_info(None)  # pyright: ignore[reportArgumentType]
    assert isinstance(res, dict)
    assert "error" in res


def test_optimize_bytecode_respects_flag():
    # Make a small code object
    src = "def a():\n    return 1\n"
    compiled = compile(src, "<opt>", "exec")
    code = next((c for c in compiled.co_consts if isinstance(c, types.CodeType)), None)
    assert code is not None

    mb.set_optimization_enabled(False)
    out = mb.optimize_bytecode(code)
    assert out is code
    mb.set_optimization_enabled(True)


def test_inject_and_remove_return_types():
    src = "def a():\n    x = 1\n    return x\n"
    compiled = compile(src, "<inj>", "exec")
    code = next((c for c in compiled.co_consts if isinstance(c, types.CodeType)), None)
    assert code is not None
    # Ensure global modifier state is deterministic for the test
    mb.clear_bytecode_cache()
    mb.set_optimization_enabled(True)

    ok, new_code = mb.inject_breakpoint_bytecode(code, {2})
    assert isinstance(ok, bool)
    assert isinstance(new_code, types.CodeType)

    removed = mb.remove_breakpoint_bytecode(new_code)
    assert isinstance(removed, types.CodeType)
