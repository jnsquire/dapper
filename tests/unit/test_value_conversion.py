from __future__ import annotations

from types import SimpleNamespace

import pytest

from dapper.shared.value_conversion import convert_value_with_context
from dapper.shared.value_conversion import evaluate_with_policy


def test_convert_value_with_context_uses_frame_expression():
    frame = SimpleNamespace(f_globals={"x": 5}, f_locals={})
    assert convert_value_with_context("x + 1", frame) == 6


def test_convert_value_with_context_blocked_expression_falls_back_to_string():
    frame = SimpleNamespace(f_globals={"x": 5}, f_locals={})
    blocked = "__import__('os').system('echo hi')"
    assert convert_value_with_context(blocked, frame) == blocked


def test_evaluate_with_policy_blocks_hostile_expression():
    frame = SimpleNamespace(f_globals={"x": 1}, f_locals={})
    with pytest.raises(ValueError, match="blocked by policy"):
        evaluate_with_policy("__import__('os').system('id')", frame)


def test_evaluate_with_policy_allows_readonly_dunder_name():
    frame = SimpleNamespace(f_globals={"__name__": "fixture"}, f_locals={})
    assert evaluate_with_policy("__name__", frame) == "fixture"


def test_evaluate_with_policy_allows_readonly_dunder_file():
    frame = SimpleNamespace(f_globals={"__file__": "/tmp/example.py"}, f_locals={})
    assert evaluate_with_policy("__file__", frame) == "/tmp/example.py"


def test_evaluate_with_policy_blocks_dunder_attribute_access():
    frame = SimpleNamespace(f_globals={"x": object()}, f_locals={})
    with pytest.raises(ValueError, match="blocked by policy"):
        evaluate_with_policy("x.__class__", frame)


def test_evaluate_with_policy_rejects_missing_frame():
    with pytest.raises(ValueError, match="frame context is required"):
        evaluate_with_policy("1 + 1", None)
