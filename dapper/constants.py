"""
Constants used throughout the Dapper debugger.

This module contains constants to avoid magic numbers in the codebase.
"""
from typing import Final

# Debug Protocol Constants
CONTENT_LENGTH_HEADER: Final[str] = "Content-Length: "
MIN_CONTENT_LENGTH: Final[int] = 0
DEFAULT_BUFFER_SIZE: Final[int] = 1024
DEFAULT_MAX_STRING_LENGTH: Final[int] = 100

# Debugger Constants
DEFAULT_MAX_RECURSION_DEPTH: Final[int] = 10
DEFAULT_CACHE_SIZE: Final[int] = 1000
DEFAULT_CACHE_TTL: Final[int] = 300  # 5 minutes
CLEANUP_INTERVAL: Final[int] = 60  # seconds

# Breakpoint Constants
DEFAULT_BREAKPOINT_CONDITION: Final[str] = "True"
DEFAULT_HIT_CONDITION: Final[str] = ">=1"
DEFAULT_BREAKPOINT_LINE: Final[int] = 10
DEFAULT_BREAKPOINT_HIT_COUNT: Final[int] = 3
DEFAULT_BREAKPOINT_CONDITION_VALUE: Final[int] = 5  # Used in conditions like "x > 5"

# Test Constants
TEST_DEFAULT_LINE: Final[int] = 10
TEST_ALT_LINE_1: Final[int] = 20
TEST_ALT_LINE_2: Final[int] = 30
TEST_MAX_STRING_LENGTH: Final[int] = 2000
TEST_STRING_LIMIT: Final[int] = 100

# Threading Constants
DEFAULT_THREAD_POOL_SIZE: Final[int] = 10

# Network Constants
DEFAULT_PORT: Final[int] = 5678
DEFAULT_HOST: Final[str] = "localhost"

# Performance Constants
MEMORY_CHUNK_SIZE: Final[int] = 4096  # 4KB chunks for memory operations
MEMORY_ESTIMATE_PER_ITEM: Final[int] = 100  # Rough estimate in bytes per item

# Error Handling
MAX_ERROR_RETRIES: Final[int] = 3
DEFAULT_TIMEOUT: Final[float] = 30.0  # 30 seconds

# Type Checking
TYPE_CHECKING: Final[bool] = False  # Will be overridden by typing.TYPE_CHECKING

# ASCII/Character Constants
ASCII_MAX: Final[int] = 255  # Maximum ASCII value
