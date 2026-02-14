"""Small event utilities used by the adapter.

Provides a minimal synchronous EventEmitter with add_listener/remove_listener/emit.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class EventEmitter:
    """Tiny synchronous event emitter.

    API:
    - add_listener(callable)
    - remove_listener(callable)
    - emit(*args, **kwargs)
    """

    def __init__(self) -> None:
        self._listeners: list[Any] = []

    def add_listener(self, fn: Any) -> None:
        self._listeners.append(fn)

    def remove_listener(self, fn: Any) -> None:
        try:
            self._listeners.remove(fn)
        except ValueError:
            pass

    def emit(self, *args: Any, **kwargs: Any) -> None:
        listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(*args, **kwargs)
            except Exception:
                logger.exception("error in event listener")
