"""
Communication helpers for the debug launcher.

This module re-exports ``send_debug_message`` from the canonical
implementation in ``dapper.shared.debug_shared`` so that existing
callers (``from dapper.launcher.comm import send_debug_message``)
continue to work without change.
"""

from __future__ import annotations

# Single canonical implementation lives in debug_shared.
from dapper.shared.debug_shared import send_debug_message

__all__ = ["send_debug_message"]
