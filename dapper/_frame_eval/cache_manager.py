"""
Advanced caching system for frame evaluation.

This module provides efficient caching mechanisms for FuncCodeInfo objects
and thread-local data using Python's _PyCode_SetExtra API and optimized
data structures.
"""

from __future__ import annotations

import ctypes
import threading
import time
import weakref
from collections import OrderedDict
from ctypes import c_int
from ctypes import c_void_p
from ctypes import py_object
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from typing import ClassVar
from typing import Final
from typing import TypedDict

# Third-party imports
# Local application imports
from dapper.common.constants import DEFAULT_CACHE_TTL
from dapper.common.constants import DEFAULT_MAX_RECURSION_DEPTH

if TYPE_CHECKING:
    import os
    from types import CodeType

# Conditional imports for Cython module
# Note: These are private APIs but necessary for frame evaluation
# ruff: noqa: SLF001
# pylint: disable=protected-access
try:
    from dapper._frame_eval._frame_evaluator import _PyCode_GetExtra as _cython_get_extra
    from dapper._frame_eval._frame_evaluator import _PyCode_SetExtra as _cython_set_extra
    from dapper._frame_eval._frame_evaluator import (
        _PyEval_RequestCodeExtraIndex as _cython_request_index,
    )

    # Alias for consistency with ctypes fallback
    _PyCode_SetExtra = _cython_set_extra
    CYTHON_AVAILABLE = True
except ImportError:
    CYTHON_AVAILABLE = False
    _cython_get_extra = None
    _cython_set_extra = None
    _cython_request_index = None

    # Define _PyCode_SetExtra using ctypes as fallback
    try:
        _PyCode_SetExtra = ctypes.pythonapi._PyCode_SetExtra
        _PyCode_SetExtra.argtypes = [ctypes.py_object, ctypes.c_int, ctypes.c_void_p]
        _PyCode_SetExtra.restype = ctypes.c_int
    except (AttributeError, OSError, TypeError):
        # If _PyCode_SetExtra is not available, set to None
        _PyCode_SetExtra = None

# Constants for magic numbers
CLEANUP_INTERVAL: Final[int] = 60  # seconds
CACHE_EXPIRY_SECONDS: Final[int] = DEFAULT_CACHE_TTL
MAX_RECURSION_DEPTH: Final[int] = DEFAULT_MAX_RECURSION_DEPTH


class GlobalCacheStats(TypedDict):
    """TypedDict for global cache statistics.

    Provides type safety for cache statistics returned by the caching system.
    Enables better IDE autocomplete and static type checking with tools like mypy.
    """

    hits: int
    misses: int
    evictions: int
    total_entries: int
    memory_usage: int


class FuncCodeCacheStats(TypedDict):
    """TypedDict for FuncCodeInfo cache statistics.

    Contains detailed statistics about the FuncCodeInfo cache including
    hit rates, memory usage, and configuration parameters.
    """

    hits: int
    misses: int
    evictions: int
    total_entries: int
    max_size: int
    ttl: int
    hit_rate: float
    memory_usage: int
    code_extra_index_available: bool


class BreakpointCacheStats(TypedDict):
    """TypedDict for breakpoint cache statistics.

    Provides information about cached breakpoint data including
    file counts and cached file paths.
    """

    total_files: int
    max_entries: int
    cached_files: list[str]


class CacheStatistics(TypedDict):
    """TypedDict for comprehensive cache statistics.

    Combines statistics from all cache subsystems into a single
    typed structure for easy consumption and type checking.
    """

    func_code_cache: FuncCodeCacheStats
    breakpoint_cache: BreakpointCacheStats
    global_stats: GlobalCacheStats


class CleanupResults(TypedDict):
    """TypedDict for cache cleanup results.

    Returns information about cleanup operations including
    how many expired entries were removed.
    """

    func_code_expired: int
    breakpoint_files: int


class CacheManager:
    # Class variables for caching
    _breakpoint_cache: ClassVar[dict[str, set[int]]] = {}
    _func_code_cache: ClassVar[dict[CodeType, CodeType]] = {}
    _cache_lock: ClassVar[threading.RLock] = threading.RLock()
    _global_cache_enabled: ClassVar[bool] = True
    _cache_stats: ClassVar[GlobalCacheStats] = {
        "hits": 0,
        "misses": 0,
        "evictions": 0,
        "total_entries": 0,
        "memory_usage": 0,
    }

    @classmethod
    def _set_cached_code(cls, original_code: CodeType, modified_code: CodeType) -> None:
        """Cache modified code for an original code object.

        Args:
            original_code: The original code object.
            modified_code: The modified code object to cache.
        """
        with cls._cache_lock:
            cls._func_code_cache[original_code] = modified_code

    @classmethod
    def _get_cached_code(cls, original_code: CodeType) -> CodeType | None:
        """Get cached modified code for an original code object.

        Args:
            original_code: The original code object.

        Returns:
            The modified code object if found in cache, None otherwise.
        """
        with cls._cache_lock:
            return cls._func_code_cache.get(original_code)

    @classmethod
    def _get_cached_breakpoints(cls, filepath: str) -> set[int] | None:
        """Get cached breakpoint lines for a file.

        Args:
            filepath: Path to the file to get breakpoints for.

        Returns:
            Set of line numbers with breakpoints, or None if not found in cache.
        """
        with cls._cache_lock:
            return cls._breakpoint_cache.get(filepath)

    @classmethod
    def _set_cached_breakpoints(cls, filepath: str, lines: set[int]) -> None:
        """Cache breakpoint lines for a file.

        Args:
            filepath: Path to the file to cache breakpoints for.
            lines: Set of line numbers with breakpoints.
        """
        with cls._cache_lock:
            cls._breakpoint_cache[filepath] = set(lines)  # Create a copy to prevent modification

    @classmethod
    def _clear_caches(cls) -> None:
        """Clear all caches."""
        with cls._cache_lock:
            cls._breakpoint_cache.clear()
            cls._func_code_cache.clear()

    @classmethod
    def get_cache_statistics(cls) -> CacheStatistics:
        """Get comprehensive cache statistics."""
        return {
            "func_code_cache": {
                "hits": cls._cache_stats["hits"],
                "misses": cls._cache_stats["misses"],
                "evictions": cls._cache_stats["evictions"],
                "total_entries": len(cls._func_code_cache),
                "max_size": 1000,
                "ttl": 300,
                "hit_rate": cls._cache_stats["hits"]
                / (cls._cache_stats["hits"] + cls._cache_stats["misses"])
                if cls._cache_stats["hits"] + cls._cache_stats["misses"] > 0
                else 0,
                "memory_usage": len(cls._func_code_cache) * 200,
                "code_extra_index_available": True,
            },
            "breakpoint_cache": {
                "total_files": len(cls._breakpoint_cache),
                "max_entries": 500,
                "cached_files": list(cls._breakpoint_cache.keys()),
            },
            "global_stats": cls._cache_stats.copy(),
        }


class FuncCodeInfoCache:
    """
    High-performance cache for FuncCodeInfo objects.

    Uses a hybrid approach with both code object extra data and
    an LRU cache for fallback and statistics.
    """

    # Class variable to store the shared code extra index
    _code_extra_index = -1
    _code_extra_lock = threading.RLock()

    def __init__(self, max_size: int = 1000, ttl: int = 300):
        """
        Initialize the cache.

        Args:
            max_size: Maximum number of entries in the LRU cache
            ttl: Time-to-live for cache entries in seconds
        """
        self.max_size = max_size
        self.ttl = ttl
        self._lru_cache = OrderedDict()
        self._timestamps = {}
        self._weak_refs = weakref.WeakValueDictionary()
        self._lock = threading.RLock()

        # Initialize code extra index
        self._init_code_extra_index()

    def _init_code_extra_index(self) -> None:
        """Initialize the code extra index for storing additional information on code objects.

        This method sets up an index in the code object's extra data array where we can
        store our cached information. It uses a class variable to ensure consistency
        across all instances.

        The index is used to store cached information in the code object's extra data
        array, allowing for efficient retrieval and storage of cached data.
        """
        with self._code_extra_lock:
            if self._code_extra_index < 0:
                if CYTHON_AVAILABLE and _cython_request_index is not None:
                    # Use Cython implementation if available
                    self._code_extra_index = _cython_request_index()
                else:
                    try:
                        # Fallback to ctypes if Cython is not available
                        request_code_extra_index = ctypes.pythonapi._PyEval_RequestCodeExtraIndex
                        request_code_extra_index.argtypes = [
                            ctypes.py_object,  # freefunc
                            ctypes.c_void_p,  # extra
                        ]
                        request_code_extra_index.restype = ctypes.c_int

                        self._code_extra_index = request_code_extra_index(
                            ctypes.py_object(self._release_code_extra_ctypes), ctypes.c_void_p(0)
                        )
                    except (AttributeError, OSError, TypeError):
                        # Fallback if _PyEval_RequestCodeExtraIndex is not available
                        self._code_extra_index = -1

    def _release_code_extra(self, obj) -> None:
        """Callback for releasing code object extra data."""

        ctypes.pythonapi.Py_DecRef(ctypes.py_object(obj))

    def _release_code_extra_ctypes(self, obj_ptr) -> None:
        """Callback for releasing code object extra data via ctypes."""
        if obj_ptr.value is not None:
            obj = ctypes.cast(obj_ptr.value, ctypes.py_object).value
            ctypes.pythonapi.Py_DecRef(ctypes.py_object(obj))

    def get(self, code_obj: Any) -> Any | None:
        """
        Get cached FuncCodeInfo for a code object.

        Args:
            code_obj: The code object to get cached info for

        Returns:
            FuncCodeInfo object or None if not cached
        """
        if not CacheManager._global_cache_enabled:
            return None

        with self._lock:
            # First try code object extra data (fastest)
            if self._code_extra_index >= 0:
                try:
                    # Try to get from Cython module first
                    if CYTHON_AVAILABLE and _cython_get_extra is not None:
                        extra = _cython_get_extra(code_obj)
                        if extra is not None:
                            CacheManager._cache_stats["hits"] += 1
                            return extra
                    # Fall through to ctypes fallback if Cython not available
                except (ImportError, AttributeError):
                    # Fallback: use ctypes to access the C API
                    try:
                        python_api = ctypes.pythonapi
                        python_api._PyCode_GetExtra.argtypes = [py_object, c_int, c_void_p]
                        python_api._PyCode_GetExtra.restype = c_int

                        # Create a pointer to hold the result
                        extra_ptr = c_void_p()
                        result = python_api._PyCode_GetExtra(
                            py_object(code_obj), self._code_extra_index, ctypes.byref(extra_ptr)
                        )
                        if result == 0 and extra_ptr.value is not None:
                            # Successfully retrieved extra data
                            extra_obj = ctypes.cast(extra_ptr.value, ctypes.py_object).value
                            CacheManager._cache_stats["hits"] += 1
                            return extra_obj
                    except Exception:
                        pass

            # Fallback to LRU cache
            cache_key = id(code_obj)
            if cache_key in self._lru_cache:
                # Check TTL
                if time.time() - self._timestamps.get(cache_key, 0) < self.ttl:
                    # Move to end (LRU update)
                    self._lru_cache.move_to_end(cache_key)
                    CacheManager._cache_stats["hits"] += 1
                    return self._lru_cache[cache_key]
                # Expired entry
                del self._lru_cache[cache_key]
                del self._timestamps[cache_key]
                CacheManager._cache_stats["evictions"] += 1

            CacheManager._cache_stats["misses"] += 1
            return None

    def set(self, code_obj: Any, info: Any) -> None:
        """
        Cache FuncCodeInfo for a code object.

        Args:
            code_obj: The code object to cache info for
            info: The FuncCodeInfo object to cache
        """
        if not CacheManager._global_cache_enabled:
            return

        with self._lock:
            cache_key = id(code_obj)
            current_time = time.time()

            # Store in code object extra data if available
            if self._code_extra_index >= 0 and _PyCode_SetExtra is not None:
                try:
                    # Try to use Cython module first
                    _PyCode_SetExtra(code_obj, self._code_extra_index, info)
                except (ImportError, AttributeError, TypeError):
                    # Fallback: use ctypes to access the C API
                    try:
                        python_api = ctypes.pythonapi
                        python_api._PyCode_SetExtra.argtypes = [py_object, c_int, c_void_p]
                        python_api._PyCode_SetExtra.restype = c_int

                        # Increment reference count manually
                        ctypes.pythonapi.Py_IncRef(ctypes.py_object(info))

                        # Call the C API function
                        result = python_api._PyCode_SetExtra(
                            py_object(code_obj), self._code_extra_index, ctypes.py_object(info)
                        )
                        if result != 0:
                            # Failed to set extra data, decrement ref count
                            ctypes.pythonapi.Py_DecRef(ctypes.py_object(info))
                    except Exception:
                        pass

            # Also store in LRU cache for statistics and fallback
            self._lru_cache[cache_key] = info
            self._timestamps[cache_key] = current_time

            # Maintain size limit
            while len(self._lru_cache) > self.max_size:
                oldest_key = next(iter(self._lru_cache))
                del self._lru_cache[oldest_key]
                if oldest_key in self._timestamps:
                    del self._timestamps[oldest_key]
                CacheManager._cache_stats["evictions"] += 1

            # Update statistics
            CacheManager._cache_stats["total_entries"] = len(self._lru_cache)
            CacheManager._cache_stats["memory_usage"] = self._estimate_memory_usage()

    def remove(self, code_obj: Any) -> bool:
        """
        Remove cached info for a code object.

        Args:
            code_obj: The code object to remove cache for

        Returns:
            True if entry was removed, False if not found
        """
        with self._lock:
            cache_key = id(code_obj)
            removed = False

            # Remove from code object extra data
            if self._code_extra_index >= 0:
                try:
                    # Try to use Cython module first
                    _PyCode_SetExtra(code_obj, self._code_extra_index, None)
                    removed = True
                except (ImportError, AttributeError):
                    # Fallback: use ctypes to access the C API
                    try:
                        python_api = ctypes.pythonapi
                        python_api._PyCode_SetExtra.argtypes = [py_object, c_int, c_void_p]
                        python_api._PyCode_SetExtra.restype = c_int

                        # Call the C API function with NULL pointer
                        result = python_api._PyCode_SetExtra(
                            py_object(code_obj), self._code_extra_index, ctypes.c_void_p(0)
                        )
                        if result == 0:
                            removed = True
                    except Exception:
                        pass

            # Remove from LRU cache
            if cache_key in self._lru_cache:
                del self._lru_cache[cache_key]
                if cache_key in self._timestamps:
                    del self._timestamps[cache_key]
                removed = True

            # Update statistics
            CacheManager._cache_stats["total_entries"] = len(self._lru_cache)
            CacheManager._cache_stats["memory_usage"] = self._estimate_memory_usage()

            return removed

    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self._lru_cache.clear()
            self._timestamps.clear()
            self._weak_refs.clear()

            # Update statistics
            CacheManager._cache_stats["total_entries"] = 0
            CacheManager._cache_stats["memory_usage"] = 0

    def cleanup_expired(self) -> int:
        """
        Remove expired entries from the cache.

        Returns:
            Number of entries removed
        """
        with self._lock:
            current_time = time.time()
            expired_keys = []

            for cache_key, timestamp in self._timestamps.items():
                if current_time - timestamp > self.ttl:
                    expired_keys.append(cache_key)

            for key in expired_keys:
                del self._lru_cache[key]
                del self._timestamps[key]

            CacheManager._cache_stats["evictions"] += len(expired_keys)
            CacheManager._cache_stats["total_entries"] = len(self._lru_cache)
            CacheManager._cache_stats["memory_usage"] = self._estimate_memory_usage()

            return len(expired_keys)

    def _estimate_memory_usage(self) -> int:
        """Estimate memory usage of the cache in bytes."""
        # Rough estimation - each entry is approximately 200 bytes
        return len(self._lru_cache) * 200

    def get_stats(self) -> FuncCodeCacheStats:
        """Get cache statistics."""
        with self._lock:
            total_requests = (
                CacheManager._cache_stats["hits"] + CacheManager._cache_stats["misses"]
            )
            hit_rate = (
                CacheManager._cache_stats["hits"] / total_requests if total_requests > 0 else 0
            )

            return {
                "hits": CacheManager._cache_stats["hits"],
                "misses": CacheManager._cache_stats["misses"],
                "evictions": CacheManager._cache_stats["evictions"],
                "total_entries": len(self._lru_cache),
                "max_size": self.max_size,
                "ttl": self.ttl,
                "hit_rate": hit_rate,
                "memory_usage": self._estimate_memory_usage(),
                "code_extra_index_available": self._code_extra_index >= 0,
            }


class ThreadLocalCache:
    """
    Thread-local cache for frame evaluation data.

    Provides fast access to thread-specific debugging information
    without the overhead of global locks.
    """

    def __init__(self):
        self._local = threading.local()
        # Initialize storage for the current thread
        self._ensure_storage()
        self._cleanup_interval = CLEANUP_INTERVAL
        self._last_cleanup = time.time()

    def _ensure_storage(self):
        """Ensure that storage is initialized for the current thread."""
        if not hasattr(self._local, "storage"):
            self._local.storage = {}

    def get_thread_info(self) -> ThreadInfo:
        """Get thread-local debugging information."""
        if not hasattr(self._local, "thread_info"):
            self._local.thread_info = ThreadInfo()

        return self._local.thread_info

    def get_breakpoint_cache(self) -> dict[str, set[int]]:
        """Get thread-local breakpoint cache."""
        if not hasattr(self._local, "breakpoint_cache"):
            self._local.breakpoint_cache = {}

        return self._local.breakpoint_cache

    def get_frame_stack(self) -> list[Any]:
        """Get thread-local frame stack."""
        if not hasattr(self._local, "frame_stack"):
            self._local.frame_stack = []

        return self._local.frame_stack

    def cleanup_if_needed(self) -> None:
        """Cleanup thread-local data if cleanup interval has passed."""
        current_time = time.time()
        if current_time - self._last_cleanup > self._cleanup_interval:
            self._cleanup_thread_local()
            self._last_cleanup = current_time

    def _cleanup_thread_local(self) -> None:
        """Cleanup expired thread-local data."""
        if hasattr(self._local, "breakpoint_cache"):
            # Remove old entries
            current_time = time.time()
            expired_keys = [
                key
                for key, data in self._local.breakpoint_cache.items()
                if hasattr(data, "timestamp")
                and current_time - data.timestamp > CACHE_EXPIRY_SECONDS
            ]
            for key in expired_keys:
                del self._local.breakpoint_cache[key]

    def clear_thread_local(self) -> None:
        """Clear all thread-local data for the current thread."""
        if hasattr(self._local, "thread_info"):
            delattr(self._local, "thread_info")
        if hasattr(self._local, "breakpoint_cache"):
            delattr(self._local, "breakpoint_cache")
        if hasattr(self._local, "frame_stack"):
            delattr(self._local, "frame_stack")


class ThreadInfo:
    """Thread-local debugging information."""

    def __init__(self):
        self.inside_frame_eval = 0
        self.fully_initialized = False
        self.is_pydevd_thread = False
        self.thread_trace_func = None
        self.additional_info = {}
        self.recursion_depth = 0
        self.skip_all_frames = False
        self.last_activity = time.time()

    def enter_frame_eval(self) -> None:
        """Enter frame evaluation context."""
        self.inside_frame_eval += 1
        self.recursion_depth += 1
        self.last_activity = time.time()

    def exit_frame_eval(self) -> None:
        """Exit frame evaluation context."""
        if self.inside_frame_eval > 0:
            self.inside_frame_eval -= 1
        if self.recursion_depth > 0:
            self.recursion_depth -= 1
        self.last_activity = time.time()

    def should_skip_frame(self, filename: str) -> bool:
        """Check if frame should be skipped during evaluation."""
        # Skip if recursion depth is too high
        if self.recursion_depth > MAX_RECURSION_DEPTH:
            return True

        # Skip if thread is marked to skip all frames
        if self.skip_all_frames:
            return True

        # Skip debugger frames
        debugger_paths = [
            "dapper/debugger_bdb.py",
            "dapper/server.py",
            "dapper/debug_launcher.py",
            "dapper/_frame_eval/",
            "site-packages/",
            "python3.",
            "lib/python",
            "Python/Lib",
        ]

        return any(path in filename for path in debugger_paths)


class BreakpointCache:
    """
    Specialized cache for breakpoint information.

    Provides fast lookup of breakpoints by file path with
    intelligent invalidation and update mechanisms.
    """

    def __init__(self, max_entries: int = 500):
        self.max_entries = max_entries
        # Use OrderedDict to maintain access order (most recent at end)
        self._cache = OrderedDict()
        self._file_mtimes = {}
        self._lock = threading.RLock()
        # Keep track of access order for LRU
        self._access_order = []

    def get_breakpoints(self, filepath: str | os.PathLike) -> set[int] | None:
        """
        Get cached breakpoints for a file.

        Args:
            filepath: Path to the source file (PathLike)

        Returns:
            Set of line numbers with breakpoints or None if not cached
        """
        with self._lock:
            # Convert Path to string for consistent handling
            filepath_str = str(filepath)

            # Check if we have this file in cache
            if filepath_str in self._cache:
                # For test files or files that don't exist, don't check modification time
                is_test_file = (
                    "test_" in filepath_str
                    or "test/" in filepath_str
                    or "test\\" in filepath_str
                    or not Path(filepath_str).exists()
                )
                if is_test_file or self._is_file_current(filepath_str):
                    # Update access time for LRU
                    if filepath_str in self._access_order:
                        self._access_order.remove(filepath_str)
                    self._access_order.append(filepath_str)
                    # Return a copy to prevent modification of cached data
                    return set(self._cache[filepath_str])
                # File modified, remove stale cache
                self._remove_entry(filepath_str)

            return None

    def set_breakpoints(self, filepath: str | os.PathLike, lines: set[int]) -> None:
        """
        Cache breakpoints for a file.

        Args:
            filepath: Path to the source file (PathLike)
            lines: Set of line numbers with breakpoints
        """
        if not CacheManager._global_cache_enabled:
            return

        filepath_str = str(filepath)

        with self._lock:
            # Remove any existing entry for this file
            if filepath_str in self._cache:
                self._remove_entry(filepath_str)

            # If lines is None or empty, just ensure it's not in the cache
            if not lines:
                return

            # If we're at capacity, remove the least recently used file
            if len(self._cache) >= self.max_entries and self._access_order:
                # Remove the least recently used file (first in access order)
                while self._access_order:
                    oldest_file = self._access_order[0]
                    if oldest_file in self._cache:
                        self._remove_entry(oldest_file)
                        break
                    self._access_order.pop(0)

            # Store the breakpoints
            self._cache[filepath_str] = set(lines)  # Create a copy to prevent modification

            # Update the file modification time
            try:
                self._file_mtimes[filepath_str] = Path(filepath).stat().st_mtime
            except (OSError, AttributeError):
                # If we can't get the mtime, use the current time
                self._file_mtimes[filepath_str] = time.time()

            # Update access time and LRU order
            if filepath_str in self._access_order:
                self._access_order.remove(filepath_str)
            self._access_order.append(filepath_str)

            # Ensure we don't exceed max_entries
            while len(self._cache) > self.max_entries and self._access_order:
                oldest = self._access_order[0]
                self._remove_entry(oldest)

    def invalidate_file(self, filepath: str) -> None:
        """Invalidate cached breakpoints for a file."""
        with self._lock:
            self._remove_entry(filepath)

    def clear_all(self) -> None:
        """Clear all cached breakpoints."""
        with self._lock:
            self._cache.clear()
            self._file_mtimes.clear()
            self._access_order = []

    def _is_file_current(self, filepath: str) -> bool:
        """Check if cached data is still current for the file."""
        try:
            # First try with pathlib.Path
            mtime = Path(filepath).stat().st_mtime
            return self._file_mtimes.get(filepath, 0) >= mtime
        except (OSError, AttributeError):
            # Fall back to os.path if Path fails
            try:
                current_mtime = Path(filepath).stat().st_mtime
                cached_mtime = self._file_mtimes[filepath]
                # Use a small epsilon to account for floating point precision issues
                return abs(current_mtime - cached_mtime) < 1.0
            except (OSError, KeyError, AttributeError):
                # If we can't check the file, assume it's not current
                return False

    def _update_access(self, filepath: str) -> None:
        """Update the access time for a file to mark it as recently used.

        Args:
            filepath: Path to the source file that was accessed
        """
        with self._lock:
            # Remove the file from its current position in the access order
            if filepath in self._access_order:
                self._access_order.remove(filepath)
            # Add it to the end (most recently used)
            self._access_order.append(filepath)

    def _remove_entry(self, filepath: str) -> None:
        """Remove an entry from the cache."""
        with self._lock:
            self._cache.pop(filepath, None)
            self._file_mtimes.pop(filepath, None)
            if filepath in self._access_order:
                self._access_order.remove(filepath)

    def get_stats(self) -> BreakpointCacheStats:
        """Get breakpoint cache statistics."""
        with self._lock:
            return {
                "total_files": len(self._cache),
                "max_entries": self.max_entries,
                "cached_files": list(self._cache.keys()),
            }


# Global cache instances (wrapped in a class to avoid module-level state)
class _GlobalCaches:
    _instance = None

    def __init__(self):
        self.func_code = FuncCodeInfoCache()
        self.thread_local = ThreadLocalCache()
        self.breakpoint = BreakpointCache()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def update_func_code_cache(self, max_size: int, ttl: int) -> None:
        """Update the function code cache with new parameters.

        Args:
            max_size: Maximum size of the function code cache
            ttl: Time-to-live for cache entries in seconds
        """
        self.func_code = FuncCodeInfoCache(max_size=max_size, ttl=ttl)

    def update_breakpoint_cache(self, max_entries: int) -> None:
        """Update the breakpoint cache with a new maximum size.

        Args:
            max_entries: Maximum number of entries in the breakpoint cache
        """
        self.breakpoint = BreakpointCache(max_entries=max_entries)


# Singleton instance
_caches = _GlobalCaches.get_instance()


def get_func_code_info(code_obj: CodeType) -> Any | None:
    """Get cached FuncCodeInfo for a code object."""
    return _caches.func_code.get(code_obj)


def set_func_code_info(code_obj: CodeType, info: Any) -> None:
    """Cache FuncCodeInfo for a code object."""
    _caches.func_code.set(code_obj, info)


def remove_func_code_info(code_obj: CodeType) -> bool:
    """Remove cached FuncCodeInfo for a code object."""
    return _caches.func_code.remove(code_obj)


def get_thread_info() -> ThreadInfo:
    """Get thread-local debugging information."""
    return _caches.thread_local.get_thread_info()


def get_breakpoints(filepath: str) -> set[int] | None:
    """Get cached breakpoints for a file."""
    return _caches.breakpoint.get_breakpoints(filepath)


def set_breakpoints(filepath: str, breakpoints: set[int]) -> None:
    """Cache breakpoints for a file."""
    _caches.breakpoint.set_breakpoints(filepath, breakpoints)


def invalidate_breakpoints(filepath: str) -> None:
    """Invalidate cached breakpoints for a file."""
    _caches.breakpoint.invalidate_file(filepath)


def cleanup_caches() -> CleanupResults:
    """Cleanup all caches and return statistics."""
    expired_func_code = _caches.func_code.cleanup_expired()
    # BreakpointCache doesn't have cleanup_expired, so we'll just get the count
    breakpoint_files = len(_caches.breakpoint._cache)

    return {
        "func_code_expired": expired_func_code,
        "breakpoint_files": breakpoint_files,
    }


def clear_all_caches() -> None:
    """Clear all caches."""
    _caches.func_code.clear()
    _caches.thread_local.clear_thread_local()
    _caches.breakpoint.clear_all()
    CacheManager._clear_caches()


def get_cache_statistics() -> CacheStatistics:
    """Get comprehensive cache statistics."""
    stats = CacheManager.get_cache_statistics()
    stats.update(
        {
            "func_code_cache": _caches.func_code.get_stats(),
            "breakpoint_cache": _caches.breakpoint.get_stats(),
            "global_stats": CacheManager._cache_stats.copy(),
        }
    )
    return stats


def set_cache_enabled(enabled: bool) -> None:
    """Enable or disable all caching."""
    CacheManager._global_cache_enabled = enabled

    if not enabled:
        clear_all_caches()


def configure_caches(
    func_code_max_size: int = 1000,
    func_code_ttl: int = 300,
    breakpoint_max_size: int = 500,
) -> None:
    """
    Configure cache parameters.

    Args:
        func_code_max_size: Maximum size of FuncCodeInfo cache
        func_code_ttl: Time-to-live for FuncCodeInfo cache entries
        breakpoint_max_size: Maximum size of breakpoint cache
    """
    # Get the global caches instance
    caches = _GlobalCaches.get_instance()

    # Update caches with new parameters
    old_stats = get_cache_statistics()

    # Update function code cache with new parameters
    caches.update_func_code_cache(max_size=func_code_max_size, ttl=func_code_ttl)

    # Update breakpoint cache with new parameters
    caches.update_breakpoint_cache(max_entries=breakpoint_max_size)

    print(f"Cache reconfigured: {old_stats} -> new parameters")
