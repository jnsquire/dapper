from __future__ import annotations

from types import ModuleType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from dapper.adapter import source_tracker as source_tracker_mod
from dapper.adapter.source_tracker import LoadedSourceTracker


def _make_module(name: str, file_path: Path, package: str | None = None) -> ModuleType:
    module = ModuleType(name)
    module.__file__ = str(file_path)
    module.__package__ = package
    return module


def test_iter_python_module_files_uses_debounce_cache(monkeypatch, tmp_path: Path) -> None:
    tracker = LoadedSourceTracker()
    module_name = "dapper_test_mod_cache"
    file_a = tmp_path / "mod_a.py"
    file_b = tmp_path / "mod_b.py"
    file_a.write_text("x = 1\n", encoding="utf-8")
    file_b.write_text("x = 2\n", encoding="utf-8")

    # Freeze time so the debounce window remains active.
    monkeypatch.setattr(source_tracker_mod.time, "monotonic", lambda: 100.0)

    monkeypatch.setitem(
        source_tracker_mod.sys.modules,
        module_name,
        _make_module(module_name, file_a, package="pkg_a"),
    )

    first = list(tracker.iter_python_module_files())
    first_entry = next(entry for entry in first if entry[0] == module_name)
    assert first_entry[1] == file_a.resolve()
    assert first_entry[2] == "module:pkg_a"

    # Replace module metadata without changing total module count.
    monkeypatch.setitem(
        source_tracker_mod.sys.modules,
        module_name,
        _make_module(module_name, file_b, package="pkg_b"),
    )

    second = list(tracker.iter_python_module_files())
    second_entry = next(entry for entry in second if entry[0] == module_name)

    # Still cached because we're inside debounce window and module count unchanged.
    assert second_entry[1] == file_a.resolve()
    assert second_entry[2] == "module:pkg_a"


def test_iter_python_module_files_refreshes_when_module_count_changes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    tracker = LoadedSourceTracker()

    module_a = "dapper_test_mod_count_a"
    module_b = "dapper_test_mod_count_b"

    file_a = tmp_path / "count_a.py"
    file_b = tmp_path / "count_b.py"
    file_a.write_text("a = 1\n", encoding="utf-8")
    file_b.write_text("b = 2\n", encoding="utf-8")

    monkeypatch.setattr(source_tracker_mod.time, "monotonic", lambda: 200.0)

    monkeypatch.setitem(
        source_tracker_mod.sys.modules,
        module_a,
        _make_module(module_a, file_a, package="pkg_count_a"),
    )

    first = list(tracker.iter_python_module_files())
    assert any(name == module_a for name, _path, _origin in first)

    # Add one module: cache should refresh even within debounce window.
    monkeypatch.setitem(
        source_tracker_mod.sys.modules,
        module_b,
        _make_module(module_b, file_b, package="pkg_count_b"),
    )

    second = list(tracker.iter_python_module_files())
    assert any(name == module_a for name, _path, _origin in second)
    assert any(name == module_b for name, _path, _origin in second)
