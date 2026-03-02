"""Custom logging levels for dapper.

Defines TRACE (level 5), a finer-grained level below DEBUG that captures
the full contents of every DAP message passing through the connection layer.
The level is registered once on import so that log records with level TRACE
display as "TRACE" rather than "Level 5" in log files.
"""

from __future__ import annotations

import logging

#: Numeric level for TRACE - one step below DEBUG (10).
TRACE: int = 5

# Register the name once so formatters render "TRACE" instead of "Level 5".
logging.addLevelName(TRACE, "TRACE")
