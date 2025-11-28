"""
Compatibility shim: re-export the shared/launcher_handlers implementation.
"""

import threading

import dapper.shared.launcher_handlers as _shared
from dapper.core.debug_utils import evaluate_hit_condition as _evaluate_hit_condition_impl
from dapper.core.debug_utils import format_log_message as _format_log_message_impl
from dapper.launcher.comm import send_debug_message  # noqa: F401 - re-exported for patching

# Compatibility helpers: expose a small set of names that tests (and other
# modules) patch on the handlers module. We also bind these into the
# shared handler module so patches (e.g. patching `dapper.launcher.handlers.threading`)
# are visible to the implementation in `dapper.shared.launcher_handlers`.
from dapper.shared.launcher_handlers import *  # noqa: F403

# Ensure the shared implementation uses the same objects to allow tests to
# patch the symbols on the handlers module and have the patched value used
# by the shared implementation.
_shared.threading = threading


def _shared_send_proxy(event_type: str, **kwargs):
    # Delegate to this module's send_debug_message so tests that
    # patch `dapper.launcher.handlers.send_debug_message` are honored.
    import dapper.launcher.handlers as _self  # noqa: PLC0415

    return _self.send_debug_message(event_type, **kwargs)


_shared.send_debug_message = _shared_send_proxy

# Re-export underscore-prefixed helpers that tests import from this module.
# These are defined in launcher_handlers but not included in star imports.
from dapper.shared.launcher_handlers import (  # noqa: E402
    _convert_string_to_value as _convert_string_to_value,  # noqa: PLC0414
    _convert_value_with_context as _convert_value_with_context,  # noqa: PLC0414
)


def _evaluate_hit_condition(expr: str, hit_count: int) -> bool:
    """Compatibility wrapper around core evaluator."""
    return _evaluate_hit_condition_impl(expr, hit_count)


# Re-export internal compatibility helpers used by tests.
try:
    def _format_log_message(template: str, frame):
        return _format_log_message_impl(template, frame)

    # Some internal helpers still live in the shared module and start with an underscore.
    # Tests import these directly from dapper.launcher.handlers; to remain compatible we
    # expose them here as aliases.
    try:
        from dapper.shared.launcher_handlers import (
            _set_object_member,  # type: ignore[attr-defined]
        )
    except Exception:
        _set_object_member = None
    try:
        from dapper.shared.launcher_handlers import (
            _set_scope_variable,  # type: ignore[attr-defined]
        )
    except Exception:
        _set_scope_variable = None
except Exception:
    pass

__all__ = [
    name
    for name in dir()
    if not name.startswith("_") and name not in ("__all__",)
]
