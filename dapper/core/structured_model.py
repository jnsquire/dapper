"""Helpers for detecting and rendering structured Python model types.

Supports three families of "structured model":

* **dataclasses** — stdlib ``dataclasses.dataclass`` instances (Python 3.7+).
* **namedtuples** — ``collections.namedtuple`` / ``typing.NamedTuple`` instances.
* **Pydantic models** — both Pydantic v1 (``__fields__``) and v2
  (``model_fields``) model instances.

The public API is:

``is_structured_model(value)``
    Return ``True`` if the value should be rendered with field-aware expansion.

``get_model_fields(value)``
    Return an ordered list of ``(field_name, field_value)`` pairs for the
    declared fields of a structured model.  Returns an empty list for
    unrecognised objects.

``structured_model_label(value)``
    Return a short human-readable type label, e.g. ``"dataclass Point"``.
"""

from __future__ import annotations

import dataclasses
from typing import Any

# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------


def is_dataclass_instance(value: Any) -> bool:
    """Return ``True`` if *value* is an instance of a dataclass (not the class itself)."""
    return dataclasses.is_dataclass(value) and not isinstance(value, type)


def is_namedtuple_instance(value: Any) -> bool:
    """Return ``True`` if *value* is a namedtuple instance."""
    t = type(value)
    fields = getattr(t, "_fields", None)
    return (
        issubclass(t, tuple)
        and isinstance(fields, tuple)
        and all(isinstance(f, str) for f in fields)
    )


def is_pydantic_instance(value: Any) -> bool:
    """Return ``True`` if *value* is a Pydantic v1 or v2 model instance.

    Detection is intentionally duck-typed so that no Pydantic import is needed
    at the top level — the Pydantic package is an optional dependency.
    """
    cls = type(value)
    # Pydantic v2: model classes expose ``model_fields`` (a dict)
    if hasattr(cls, "model_fields") and isinstance(getattr(cls, "model_fields", None), dict):
        return True
    # Pydantic v1: model classes expose ``__fields__`` *and* ``__validators__``
    return hasattr(cls, "__fields__") and hasattr(cls, "__validators__")


def is_structured_model(value: Any) -> bool:
    """Return ``True`` if *value* should be rendered as a structured model.

    Structured models are dataclasses, namedtuples, and Pydantic models.
    Class objects themselves are excluded (only instances qualify).
    """
    if isinstance(value, type):
        return False
    return (
        is_dataclass_instance(value)
        or is_namedtuple_instance(value)
        or is_pydantic_instance(value)
    )


# ---------------------------------------------------------------------------
# Field extraction
# ---------------------------------------------------------------------------


def get_model_fields(value: Any) -> list[tuple[str, Any]]:
    """Return ``(name, field_value)`` pairs for a structured model's declared fields.

    Fields are returned in declaration order where possible.  Returns an empty
    list if the type is not a recognised structured model.
    """
    # --- dataclass ---
    if is_dataclass_instance(value):
        _missing = object()
        result: list[tuple[str, Any]] = []
        for f in dataclasses.fields(value):  # type: ignore[arg-type]
            val = getattr(value, f.name, _missing)
            if val is not _missing:
                result.append((f.name, val))
        return result

    # --- namedtuple ---
    if is_namedtuple_instance(value):
        return [(name, getattr(value, name)) for name in type(value)._fields]

    # --- Pydantic v2 ---
    if hasattr(type(value), "model_fields") and isinstance(
        getattr(type(value), "model_fields", None), dict
    ):
        try:
            return [(name, getattr(value, name)) for name in type(value).model_fields]
        except Exception:
            pass

    # --- Pydantic v1 ---
    if hasattr(type(value), "__fields__") and hasattr(type(value), "__validators__"):
        try:
            return [(name, getattr(value, name)) for name in type(value).__fields__]
        except Exception:
            pass

    return []


# ---------------------------------------------------------------------------
# Label helper
# ---------------------------------------------------------------------------


def structured_model_label(value: Any) -> str:
    """Return a short human-readable type label for a structured model value.

    Examples::

        structured_model_label(Point(x=1, y=2))  # "dataclass Point"
        structured_model_label(MyTuple(a=1))       # "namedtuple MyTuple"
        structured_model_label(MyModel(x=1))       # "pydantic MyModel"
    """
    if is_dataclass_instance(value):
        return f"dataclass {type(value).__name__}"
    if is_namedtuple_instance(value):
        return f"namedtuple {type(value).__name__}"
    if is_pydantic_instance(value):
        return f"pydantic {type(value).__name__}"
    return type(value).__name__


__all__ = [
    "get_model_fields",
    "is_dataclass_instance",
    "is_namedtuple_instance",
    "is_pydantic_instance",
    "is_structured_model",
    "structured_model_label",
]
