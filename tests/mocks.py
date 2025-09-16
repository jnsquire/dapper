from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class CodeLike(Protocol):
    co_filename: str
    co_firstlineno: int


class FrameLike(Protocol):
    f_code: CodeLike
    f_lineno: int
    f_back: FrameLike | None


@dataclass
class MockCode:
    co_filename: str
    co_firstlineno: int


@dataclass
class MockFrame:
    f_code: MockCode
    f_lineno: int
    f_back: MockFrame | None = None


# Expose names for import convenience in tests
__all__ = ["CodeLike", "FrameLike", "MockCode", "MockFrame"]
