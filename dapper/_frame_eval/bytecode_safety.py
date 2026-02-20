"""
Bytecode safety layer for Dapper frame evaluation.

Provides pre-activation validation of modified code objects so that
bytecode injection failures always report structured reason codes and
fall back to the original code object cleanly rather than producing
corrupt state.
"""

from __future__ import annotations

import dis
from typing import TYPE_CHECKING
from typing import NamedTuple
from typing import TypedDict

from dapper._frame_eval.telemetry import telemetry

if TYPE_CHECKING:
    from types import CodeType


# Maximum stack-size increase that a safe bytecode transformation is allowed
# to introduce.  Transformations that grow the stack by more than this are
# treated as unsafe and rejected.
_DEFAULT_MAX_STACKSIZE_DELTA: int = 16


class BytecodeValidationResult(NamedTuple):
    """Result returned by :func:`validate_code_object`.

    Attributes:
        valid: ``True`` when all enabled checks passed.
        errors: Human-readable descriptions of every failing check.  Empty
            when *valid* is ``True``.
    """

    valid: bool
    errors: list[str]


class BytecodeSafetyConfig(TypedDict, total=False):
    """Configuration knobs for the bytecode safety layer.

    All fields are optional; :data:`DEFAULT_SAFETY_CONFIG` supplies defaults.

    Attributes:
        validate_decodable: Verify that the modified bytecode can be fully
            decoded by :mod:`dis`.  Defaults to ``True``.
        validate_stacksize: Verify that the stack-size change is within the
            allowed :attr:`max_stacksize_delta` bound.  Defaults to ``True``.
        max_stacksize_delta: Upper bound on how much the stack size may grow
            relative to the original code object.  Defaults to
            :data:`_DEFAULT_MAX_STACKSIZE_DELTA`.
    """

    validate_decodable: bool
    validate_stacksize: bool
    max_stacksize_delta: int


DEFAULT_SAFETY_CONFIG: BytecodeSafetyConfig = {
    "validate_decodable": True,
    "validate_stacksize": True,
    "max_stacksize_delta": _DEFAULT_MAX_STACKSIZE_DELTA,
}


def validate_code_object(
    original: CodeType,
    modified: CodeType,
    config: BytecodeSafetyConfig | None = None,
) -> BytecodeValidationResult:
    """Validate *modified* against *original* using the given safety *config*.

    Checks performed (each can be individually disabled via *config*):

    - **decodable**: :func:`dis.get_instructions` can iterate *modified*
      without raising.
    - **stacksize**: The stack-size delta from *original* to *modified* is
      non-negative and at most *config['max_stacksize_delta']*.

    Args:
        original: The untouched code object before transformation.
        modified: The code object produced by a bytecode transformation.
        config: Optional overrides; unset keys fall back to
            :data:`DEFAULT_SAFETY_CONFIG`.

    Returns:
        :class:`BytecodeValidationResult` with :attr:`~BytecodeValidationResult.valid`
        set to ``True`` only when every enabled check passes.
    """
    cfg: BytecodeSafetyConfig = {**DEFAULT_SAFETY_CONFIG, **(config or {})}  # type: ignore[misc]
    errors: list[str] = []

    if cfg.get("validate_decodable", True):
        try:
            list(dis.get_instructions(modified))
        except Exception as exc:
            errors.append(f"instruction stream not decodable: {exc}")

    if cfg.get("validate_stacksize", True):
        try:
            orig_size = original.co_stacksize
            mod_size = modified.co_stacksize  # type: ignore[union-attr]
            delta = mod_size - orig_size
            max_delta = cfg.get("max_stacksize_delta", _DEFAULT_MAX_STACKSIZE_DELTA)

            if delta < 0:
                errors.append(
                    f"stacksize decreased by {-delta} (original={orig_size}, modified={mod_size})"
                )
            elif delta > max_delta:
                errors.append(
                    f"stacksize grew by {delta} which exceeds the maximum allowed"
                    f" delta of {max_delta}"
                    f" (original={orig_size}, modified={mod_size})"
                )
        except AttributeError as exc:
            errors.append(f"stacksize check failed — modified object lacks co_stacksize: {exc}")

    return BytecodeValidationResult(valid=len(errors) == 0, errors=errors)


def safe_replace_code(
    original: CodeType,
    modified: CodeType,
    config: BytecodeSafetyConfig | None = None,
) -> tuple[bool, CodeType]:
    """Return *modified* only when it passes all safety checks.

    If any check fails the failure is recorded via
    :meth:`~dapper._frame_eval.telemetry.FrameEvalTelemetry.record_bytecode_injection_failed`
    and the *original* code object is returned so that execution
    continues unmodified.

    Args:
        original: The untouched code object before transformation.
        modified: The code object produced by a bytecode transformation.
        config: Optional validation overrides.

    Returns:
        ``(True, modified)`` when validation passes, otherwise
        ``(False, original)``.
    """
    result = validate_code_object(original, modified, config)

    if result.valid:
        return True, modified

    telemetry.record_bytecode_injection_failed(
        filename=getattr(original, "co_filename", "unknown"),
        name=getattr(original, "co_name", "unknown"),
        validation_errors=result.errors,
    )
    return False, original
