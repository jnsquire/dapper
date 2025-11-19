"""
Communication helpers for the debug adapter and launcher.
"""

from __future__ import annotations

import importlib
import logging
import sys
from typing import Any

# Cached resolvers for the two external helpers. We prefer the launcher
# helpers when that module is present (tests commonly patch
# `dapper.debug_launcher.send_debug_message`) and fall back to the adapter
# communication helpers otherwise. The resolver updates the cached target if
# the launcher module appears or its attribute is replaced, so unittest.patch
# usage continues to work.
_impl_cache: dict[str, Any | None] = {
    "cached_send": None,
    "cached_process": None,
    "registered_send": None,
}

# Module logger for diagnostic messages
logger = logging.getLogger(__name__)


def send_debug_message(*args, **kwargs):
    """Call the best available send_debug_message implementation.

    This checks `sys.modules` for `dapper.debug_launcher` and prefers
    its `send_debug_message` attribute when present (this allows tests that
    patch that attribute to be observed). If not available, we fall back to
    `dapper.debug_adapter_comm.send_debug_message` and cache that.
    """
    # Prefer explicit registered helper first (tests may call register_debug_helpers)
    registered = _impl_cache.get("registered_send")
    if registered is not None:
        return registered(*args, **kwargs)

    # Prefer patched launcher helper when present in sys.modules
    mod = sys.modules.get("dapper.launcher.debug_launcher")
    if mod is not None:
        fn = getattr(mod, "send_debug_message", None)
        if callable(fn):
            if fn is not _impl_cache.get("cached_send"):
                _impl_cache["cached_send"] = fn
            impl = _impl_cache.get("cached_send")
            assert impl is not None
            return impl(*args, **kwargs)

    # Fallback to adapter comm helper
    impl = _impl_cache.get("cached_send")
    if impl is None or getattr(impl, "__module__", "") == "dapper.adapter.debug_adapter_comm":
        try:
            mod_fallback = importlib.import_module("dapper.adapter.debug_adapter_comm")
            _fallback = getattr(mod_fallback, "send_debug_message", None)
            if callable(_fallback):
                if impl is not _fallback:
                    _impl_cache["cached_send"] = _fallback
                impl = _impl_cache.get("cached_send")
        except Exception:
            # Last resort: try dynamic import path again (very rare)
            try:
                mod2 = importlib.import_module("dapper.adapter.debug_adapter_comm")
                fn2 = getattr(mod2, "send_debug_message", None)
                if callable(fn2):
                    _impl_cache["cached_send"] = fn2
                    impl = fn2
            except Exception:
                _impl_cache["cached_send"] = None
                impl = None

    if impl is None:
        msg = "No send_debug_message implementation available"
        raise RuntimeError(msg)

    return impl(*args, **kwargs)


def process_queued_commands():
    """Call the best available process_queued_commands implementation.

    Works similarly to send_debug_message: prefer launcher helper if present,
    otherwise use adapter comm helper.
    """
    # Use the single adapter-side implementation. Import lazily to avoid
    # circular imports when this module is imported early in tests.
    try:
        mod = importlib.import_module("dapper.adapter.debug_adapter_comm")
        fn = getattr(mod, "process_queued_commands", None)
        if callable(fn):
            return fn()
    except Exception:
        # Fall through to error below
        pass

    msg = "No process_queued_commands implementation available"
    raise RuntimeError(msg)


def register_debug_helpers(send_fn=None):
    """Register explicit debug helper functions.

    Tests can call this to inject mocks directly (preferred over patching
    other modules). Passing None leaves the corresponding helper untouched.
    """
    if send_fn is not None:
        _impl_cache["registered_send"] = send_fn


def unregister_debug_helpers():
    """Remove any registered debug helpers so the module falls back to
    the normal resolution behavior (launcher helper or adapter comm).
    """
    _impl_cache["registered_send"] = None
