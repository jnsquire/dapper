from __future__ import annotations

# This file is intentionally present at repo root for local helpers used in
# development; ruff flags it as part of an implicit namespace package. Silence
# the rule here to avoid changing package layout.
# ruff: noqa: INP001
from typing import Any

from dapper.shared import debug_shared


def handle_terminate(_dbg: Any, _args: dict[str, Any]) -> None:
    """
    Terminate handler must set the termination flag on the shared state and then
    call the configured exit function. Tests expect is_terminated to be True
    after calling this function even if the exit function raises SystemExit.
    """
    s = debug_shared.state
    # Ensure we mutate the state object (not reassign a new object)
    s.is_terminated = True

    # Call the exit function - tests replace it with fake_exit that raises SystemExit.
    s.exit_func(0)


def handle_threads(dbg: Any, _args: dict[str, Any]) -> dict[str, Any]:
    """
    Return the list of threads in the format expected by the tests:
      { "success": True, "body": { "threads": [ { "id": 1, "name": "MainThread" }, ... ] } }
    Accepts dbg possibly being None and threads mapping keys may be ints or strings.
    """
    threads_list: list[dict[str, Any]] = []
    try:
        threads_mapping = getattr(dbg, "threads", None) or {}
        # If mapping is dict-like
        for tid, tname in threads_mapping.items():
            # Convert tid to int when possible, tests expect int ids
            try:
                tid_val = int(tid)
            except Exception:
                tid_val = tid
            threads_list.append({"id": tid_val, "name": str(tname)})
    except Exception:
        threads_list = []

    return {"success": True, "body": {"threads": threads_list}}


def extract_variables(dbg: Any | None, variables: list[dict[str, Any]], value: Any, name: str | None = None) -> None:
    """
    Extract variables recursively into `variables` as a list of dicts:
      { "name": <name>, "value": <value>, "type": <type_name> }
    Handles dict, list/tuple and simple scalars. Name is composed with dot notation for dict keys and [index] for lists.
    """
    def append_var(n: str | None, v: Any) -> None:
        variables.append({
            "name": n if n is not None else "",
            "value": v,
            "type": type(v).__name__
        })

    # None explicitly
    if value is None:
        append_var(name, None)
        return

    # Dicts: recurse into items
    if isinstance(value, dict):
        for k, v in value.items():
            full_name = f"{k}" if name is None else f"{name}.{k}"
            extract_variables(dbg, variables, v, full_name)
        return

    # Lists and tuples: index by integer
    if isinstance(value, (list, tuple)):
        for idx, v in enumerate(value):
            full_name = f"{name}[{idx}]" if name is not None else f"[{idx}]"
            extract_variables(dbg, variables, v, full_name)
        return

    # Scalars: append and return
    append_var(name, value)