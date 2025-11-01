"""
Advanced caching system for frame evaluation.

This module provides efficient caching mechanisms for FuncCodeInfo objects
and thread-local data using Python's _PyCode_SetExtra API and optimized
data structures.
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
import weakref
from collections import OrderedDict
from typing import TYPE_CHECKING
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Set
from typing import Tuple
from typing import Union

from typing_extensions import TypedDict

if TYPE_CHECKING:
    from types import CodeType
    from typing import Callable


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
    cached_files: List[str]


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

# Global cache state
_cache_lock = threading.RLock()
_code_extra_index = -1
_global_cache_enabled = True
_cache_stats: GlobalCacheStats = {
    "hits": 0,
    "misses": 0,
    "evictions": 0,
    "total_entries": 0,
    "memory_usage": 0,
}


class FuncCodeInfoCache:
    """
    High-performance cache for FuncCodeInfo objects.

    Uses a hybrid approach with both code object extra data and
    an LRU cache for fallback and statistics.
    """

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

    def _release_code_extra(self, obj) -> None:
        """Callback for releasing code object extra data."""

        ctypes.pythonapi.Py_DecRef(ctypes.py_object(obj))

    def _release_code_extra_ctypes(self, obj_ptr) -> None:
        """Callback for releasing code object extra data via ctypes."""
        if obj_ptr.value is not None:
            obj = ctypes.cast(obj_ptr.value, ctypes.py_object).value
            ctypes.pythonapi.Py_DecRef(ctypes.py_object(obj))

    def _init_code_extra_index(self) -> None:
        global _code_extra_index

        if _code_extra_index == -1:
            try:
                # Try to import the C API functions from the Cython module
                # This would be available in the actual compiled extension
                from dapper._frame_eval._frame_evaluator import _PyEval_RequestCodeExtraIndex
                
                # Request an extra slot index for code objects
                _code_extra_index = _PyEval_RequestCodeExtraIndex(self._release_code_extra)
                
            except (ImportError, AttributeError):
                # Fallback: try to use ctypes to access the C API directly
                try:
                    import sys
                    from ctypes import c_int
                    from ctypes import c_void_p
                    from ctypes import py_object
                    
                    # Get the Python interpreter handle
                    python_api = ctypes.pythonapi
                    
                    # Define the function signatures
                    python_api._PyEval_RequestCodeExtraIndex.argtypes = [c_void_p]
                    python_api._PyEval_RequestCodeExtraIndex.restype = c_int
                    
                    # Create a cleanup callback
                    cleanup_callback = ctypes.CFUNCTYPE(None, c_void_p)(self._release_code_extra_ctypes)
                    
                    # Request the extra index
                    _code_extra_index = python_api._PyEval_RequestCodeExtraIndex(cleanup_callback)
                    
                except Exception:
                    _code_extra_index = -1

    def get(self, code_obj: CodeType) -> Optional[Any]:
        """
        Get cached FuncCodeInfo for a code object.

        Args:
            code_obj: The code object to get cached info for

        Returns:
            FuncCodeInfo object or None if not cached
        """
        if not _global_cache_enabled:
            return None

        with self._lock:
            # First try code object extra data (fastest)
            if _code_extra_index >= 0:
                try:
                    # Try to get from Cython module first
                    from dapper._frame_eval._frame_evaluator import _PyCode_GetExtra
                    
                    extra = _PyCode_GetExtra(code_obj, _code_extra_index)
                    if extra is not None:
                        _cache_stats["hits"] += 1
                        return extra
                        
                except (ImportError, AttributeError):
                    # Fallback: use ctypes to access the C API
                    try:
                        import ctypes
                        from ctypes import c_int
                        from ctypes import c_void_p
                        from ctypes import py_object
                        
                        python_api = ctypes.pythonapi
                        python_api._PyCode_GetExtra.argtypes = [py_object, c_int, c_void_p]
                        python_api._PyCode_GetExtra.restype = c_int
                        
                        # Create a pointer to hold the result
                        extra_ptr = c_void_p()
                        
                        # Call the C API function
                        result = python_api._PyCode_GetExtra(
                            py_object(code_obj), 
                            _code_extra_index, 
                            ctypes.byref(extra_ptr)
                        )
                        
                        if result == 0 and extra_ptr.value is not None:
                            # Successfully retrieved extra data
                            extra_obj = ctypes.cast(extra_ptr.value, ctypes.py_object).value
                            _cache_stats["hits"] += 1
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
                    _cache_stats["hits"] += 1
                    return self._lru_cache[cache_key]
                # Expired entry
                del self._lru_cache[cache_key]
                del self._timestamps[cache_key]
                _cache_stats["evictions"] += 1

            _cache_stats["misses"] += 1
            return None

    def set(self, code_obj: CodeType, info: Any) -> None:
        """
        Cache FuncCodeInfo for a code object.

        Args:
            code_obj: The code object to cache info for
            info: The FuncCodeInfo object to cache
        """
        if not _global_cache_enabled:
            return

        with self._lock:
            cache_key = id(code_obj)
            current_time = time.time()

            # Store in code object extra data if available
            if _code_extra_index >= 0:
                try:
                    # Try to use Cython module first
                    from dapper._frame_eval._frame_evaluator import _PyCode_SetExtra
                    
                    # Store in code object (Cython handles reference counting)
                    _PyCode_SetExtra(code_obj, _code_extra_index, info)
                    
                except (ImportError, AttributeError):
                    # Fallback: use ctypes to access the C API
                    try:
                        import ctypes
                        from ctypes import c_int
                        from ctypes import c_void_p
                        from ctypes import py_object
                        
                        python_api = ctypes.pythonapi
                        python_api._PyCode_SetExtra.argtypes = [py_object, c_int, c_void_p]
                        python_api._PyCode_SetExtra.restype = c_int
                        
                        # Increment reference count manually
                        ctypes.pythonapi.Py_IncRef(ctypes.py_object(info))
                        
                        # Call the C API function
                        result = python_api._PyCode_SetExtra(
                            py_object(code_obj), 
                            _code_extra_index, 
                            ctypes.py_object(info)
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
                _cache_stats["evictions"] += 1

            # Update statistics
            _cache_stats["total_entries"] = len(self._lru_cache)
            _cache_stats["memory_usage"] = self._estimate_memory_usage()

    def remove(self, code_obj: CodeType) -> bool:
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
            if _code_extra_index >= 0:
                try:
                    # Try to use Cython module first
                    from dapper._frame_eval._frame_evaluator import _PyCode_SetExtra
                    
                    # Set to NULL to remove (Cython handles reference counting)
                    _PyCode_SetExtra(code_obj, _code_extra_index, None)
                    removed = True
                    
                except (ImportError, AttributeError):
                    # Fallback: use ctypes to access the C API
                    try:
                        import ctypes
                        from ctypes import c_int
                        from ctypes import c_void_p
                        from ctypes import py_object
                        
                        python_api = ctypes.pythonapi
                        python_api._PyCode_SetExtra.argtypes = [py_object, c_int, c_void_p]
                        python_api._PyCode_SetExtra.restype = c_int
                        
                        # Call the C API function with NULL pointer
                        result = python_api._PyCode_SetExtra(
                            py_object(code_obj), 
                            _code_extra_index, 
                            None
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
            _cache_stats["total_entries"] = len(self._lru_cache)
            _cache_stats["memory_usage"] = self._estimate_memory_usage()

            return removed

    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self._lru_cache.clear()
            self._timestamps.clear()
            self._weak_refs.clear()

            # Update statistics
            _cache_stats["total_entries"] = 0
            _cache_stats["memory_usage"] = 0

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

            _cache_stats["evictions"] += len(expired_keys)
            _cache_stats["total_entries"] = len(self._lru_cache)
            _cache_stats["memory_usage"] = self._estimate_memory_usage()

            return len(expired_keys)

    def _estimate_memory_usage(self) -> int:
        """Estimate memory usage of the cache in bytes."""
        # Rough estimation - each entry is approximately 200 bytes
        return len(self._lru_cache) * 200

    def get_stats(self) -> FuncCodeCacheStats:
        """Get cache statistics."""
        with self._lock:
            total_requests = _cache_stats["hits"] + _cache_stats["misses"]
            hit_rate = _cache_stats["hits"] / total_requests if total_requests > 0 else 0

            return {
                "hits": _cache_stats["hits"],
                "misses": _cache_stats["misses"],
                "evictions": _cache_stats["evictions"],
                "total_entries": len(self._lru_cache),
                "max_size": self.max_size,
                "ttl": self.ttl,
                "hit_rate": hit_rate,
                "memory_usage": self._estimate_memory_usage(),
                "code_extra_index_available": _code_extra_index >= 0,
            }


class ThreadLocalCache:
    """
    Thread-local cache for frame evaluation data.

    Provides fast access to thread-specific debugging information
    without the overhead of global locks.
    """

    def __init__(self):
        self._local = threading.local()
        self._cleanup_interval = 60  # seconds
        self._last_cleanup = time.time()

    def get_thread_info(self) -> ThreadInfo:
        """Get thread-local debugging information."""
        if not hasattr(self._local, "thread_info"):
            self._local.thread_info = ThreadInfo()

        return self._local.thread_info

    def get_breakpoint_cache(self) -> Dict[str, Set[int]]:
        """Get thread-local breakpoint cache."""
        if not hasattr(self._local, "breakpoint_cache"):
            self._local.breakpoint_cache = {}

        return self._local.breakpoint_cache

    def get_frame_stack(self) -> List[Any]:
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
                if hasattr(data, "timestamp") and current_time - data.timestamp > 300  # 5 minutes
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
        if self.recursion_depth > 10:
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

        for path in debugger_paths:
            if path in filename:
                return True

        return False


class BreakpointCache:
    """
       Specialized cache for breakpoint information.

       Provides fast lookup of breakpoints by file path with
    intelligent invalidation and update mechanisms.
    """

    def __init__(self, max_entries: int = 500):
        self.max_entries = max_entries
        self._cache = OrderedDict()
        self._timestamps = {}
        self._file_mtimes = {}
        self._lock = threading.RLock()

    def get_breakpoints(self, filepath: str) -> Optional[Set[int]]:
        """
        Get cached breakpoints for a file.

        Args:
            filepath: Path to the source file

        Returns:
            Set of line numbers with breakpoints or None if not cached
        """
        with self._lock:
            if filepath in self._cache:
                # Check if file has been modified
                if self._is_file_current(filepath):
                    # Move to end (LRU update)
                    self._cache.move_to_end(filepath)
                    return self._cache[filepath]
                # File modified, remove stale cache
                self._remove_entry(filepath)

            return None

    def set_breakpoints(self, filepath: str, breakpoints: Set[int]) -> None:
        """
        Cache breakpoints for a file.

        Args:
            filepath: Path to the source file
            breakpoints: Set of line numbers with breakpoints
        """
        with self._lock:
            current_time = time.time()

            self._cache[filepath] = set(breakpoints)  # Make a copy
            self._timestamps[filepath] = current_time

            # Store file modification time
            try:
                import os

                self._file_mtimes[filepath] = os.path.getmtime(filepath)
            except OSError:
                self._file_mtimes[filepath] = current_time

            # Maintain size limit
            while len(self._cache) > self.max_entries:
                oldest_key = next(iter(self._cache))
                self._remove_entry(oldest_key)

    def invalidate_file(self, filepath: str) -> None:
        """Invalidate cached breakpoints for a specific file."""
        with self._lock:
            self._remove_entry(filepath)

    def clear_all(self) -> None:
        """Clear all cached breakpoints."""
        with self._lock:
            self._cache.clear()
            self._timestamps.clear()
            self._file_mtimes.clear()

    def _is_file_current(self, filepath: str) -> bool:
        """Check if cached data is still current for the file."""
        if filepath not in self._file_mtimes:
            return False

        try:
            import os

            current_mtime = os.path.getmtime(filepath)
            return self._file_mtimes[filepath] >= current_mtime
        except OSError:
            # If we can't check the file, assume cache is stale
            return False

    def _remove_entry(self, filepath: str) -> None:
        """Remove an entry from all cache structures."""
        self._cache.pop(filepath, None)
        self._timestamps.pop(filepath, None)
        self._file_mtimes.pop(filepath, None)

    def get_stats(self) -> BreakpointCacheStats:
        """Get breakpoint cache statistics."""
        with self._lock:
            return {
                "total_files": len(self._cache),
                "max_entries": self.max_entries,
                "cached_files": list(self._cache.keys()),
            }


# Global cache instances
_func_code_cache = FuncCodeInfoCache()
_thread_local_cache = ThreadLocalCache()
_breakpoint_cache = BreakpointCache()


def get_func_code_info(code_obj: CodeType) -> Optional[Any]:
    """Get cached FuncCodeInfo for a code object."""
    return _func_code_cache.get(code_obj)


def set_func_code_info(code_obj: CodeType, info: Any) -> None:
    """Cache FuncCodeInfo for a code object."""
    _func_code_cache.set(code_obj, info)


def remove_func_code_info(code_obj: CodeType) -> bool:
    """Remove cached FuncCodeInfo for a code object."""
    return _func_code_cache.remove(code_obj)


def get_thread_info() -> ThreadInfo:
    """Get thread-local debugging information."""
    return _thread_local_cache.get_thread_info()


def get_breakpoints(filepath: str) -> Optional[Set[int]]:
    """Get cached breakpoints for a file."""
    return _breakpoint_cache.get_breakpoints(filepath)


def set_breakpoints(filepath: str, breakpoints: Set[int]) -> None:
    """Cache breakpoints for a file."""
    _breakpoint_cache.set_breakpoints(filepath, breakpoints)


def invalidate_breakpoints(filepath: str) -> None:
    """Invalidate cached breakpoints for a file."""
    _breakpoint_cache.invalidate_file(filepath)


def cleanup_caches() -> CleanupResults:
    """Cleanup all caches and return statistics."""
    expired_func_code = _func_code_cache.cleanup_expired()
    _thread_local_cache.cleanup_if_needed()

    return {
        "func_code_expired": expired_func_code,
        "breakpoint_files": len(_breakpoint_cache._cache),
    }


def clear_all_caches() -> None:
    """Clear all caches."""
    _func_code_cache.clear()
    _thread_local_cache.clear_thread_local()
    _breakpoint_cache.clear_all()


def get_cache_statistics() -> CacheStatistics:
    """Get comprehensive cache statistics."""
    return {
        "func_code_cache": _func_code_cache.get_stats(),
        "breakpoint_cache": _breakpoint_cache.get_stats(),
        "global_stats": _cache_stats.copy(),
    }


def set_cache_enabled(enabled: bool) -> None:
    """Enable or disable all caching."""
    global _global_cache_enabled
    _global_cache_enabled = enabled

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
    global _func_code_cache, _breakpoint_cache

    # Recreate caches with new parameters
    old_stats = get_cache_statistics()

    _func_code_cache = FuncCodeInfoCache(max_size=func_code_max_size, ttl=func_code_ttl)

    _breakpoint_cache = BreakpointCache(max_entries=breakpoint_max_size)

    print(f"Cache reconfigured: {old_stats} -> new parameters")
