from __future__ import annotations

import importlib
import sys
from typing import TYPE_CHECKING
from typing import Any
from typing import cast
from unittest.mock import Mock

import pytest

from dapper._frame_eval.telemetry import get_frame_eval_telemetry
from dapper._frame_eval.telemetry import reset_frame_eval_telemetry
from dapper.adapter.server import PyDebugger
from dapper.adapter.source_tracker import LoadedSourceTracker

if TYPE_CHECKING:
    from pathlib import Path


class _FakeInProcessBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[dict]]] = []

    async def set_breakpoints(self, path: str, breakpoints: list[dict]) -> list[dict]:
        self.calls.append((path, breakpoints))
        return [{"verified": True, "line": bp.get("line")} for bp in breakpoints]


class _FrameLike:
    def __init__(self, locals_map: dict[str, Any]) -> None:
        self.f_locals = locals_map
        self.f_code = "frame-like"


class _CodeFrameLike:
    def __init__(self, locals_map: dict[str, Any], code: Any) -> None:
        self.f_locals = locals_map
        self.f_code = code


def _load_temp_module(module_name: str, file_path: Path):
    module_dir = str(file_path.parent)
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    return importlib.import_module(module_name)


@pytest.mark.asyncio
async def test_hot_reload_inprocess_success(tmp_path: Path) -> None:
    reset_frame_eval_telemetry()

    module_name = f"hot_reload_mod_{id(tmp_path)}"
    module_file = tmp_path / f"{module_name}.py"
    module_file.write_text("VALUE = 1\n", encoding="utf-8")
    _load_temp_module(module_name, module_file)

    debugger = PyDebugger(Mock())
    fake_backend = _FakeInProcessBackend()
    cast("Any", debugger)._inproc_backend = cast("Any", fake_backend)

    path = str(module_file.resolve())
    debugger.breakpoint_manager.record_line_breakpoint(path, 1, condition="VALUE == 1")

    emitted: list[tuple[str, dict]] = []

    def _capture_event(event_type: str, payload: dict[str, Any]) -> None:
        emitted.append((event_type, payload))

    debugger.emit_event = _capture_event

    body = await debugger.hot_reload(path, {"invalidatePycache": False})

    assert body.get("reloadedModule") == module_name
    assert body.get("reloadedPath") == path
    assert body.get("reboundFrames") == 0
    assert body.get("updatedFrameCodes") == 0
    assert body.get("patchedInstances") == 0
    assert isinstance(body.get("warnings"), list)

    assert fake_backend.calls, "Expected breakpoint reapplication to call backend.set_breakpoints"
    called_path, called_breakpoints = fake_backend.calls[0]
    assert called_path == path
    assert called_breakpoints == [{"line": 1, "condition": "VALUE == 1"}]

    event_names = [name for name, _payload in emitted]
    assert "loadedSource" in event_names
    assert "dapper/hotReloadResult" in event_names

    snapshot = get_frame_eval_telemetry()
    assert snapshot.reason_counts.hot_reload_succeeded >= 1

    sys.modules.pop(module_name, None)


@pytest.mark.asyncio
async def test_hot_reload_rebinds_frame_local_functions(tmp_path: Path) -> None:
    module_name = f"hot_reload_rebind_mod_{id(tmp_path)}"
    module_file = tmp_path / f"{module_name}.py"
    module_file.write_text("def target():\n    return 1\n", encoding="utf-8")
    module = _load_temp_module(module_name, module_file)

    frame = _FrameLike({"fn": module.target})

    debugger = PyDebugger(Mock())
    fake_backend = _FakeInProcessBackend()
    cast("Any", debugger)._inproc_backend = cast("Any", fake_backend)

    service = cast("Any", debugger)._hot_reload_service
    service._iter_live_frames = lambda: [frame]

    module_file.write_text("def target():\n    return 2\n", encoding="utf-8")

    body = await debugger.hot_reload(str(module_file.resolve()))

    assert body.get("reboundFrames") == 1
    rebound_fn = frame.f_locals["fn"]
    assert callable(rebound_fn)
    assert rebound_fn() == 2

    sys.modules.pop(module_name, None)


@pytest.mark.asyncio
async def test_hot_reload_clears_variable_caches(tmp_path: Path) -> None:
    module_name = f"hot_reload_vars_mod_{id(tmp_path)}"
    module_file = tmp_path / f"{module_name}.py"
    module_file.write_text("VALUE = 1\n", encoding="utf-8")
    _load_temp_module(module_name, module_file)

    debugger = PyDebugger(Mock())
    fake_backend = _FakeInProcessBackend()
    cast("Any", debugger)._inproc_backend = cast("Any", fake_backend)

    var_ref = debugger.variable_manager.allocate_ref({"x": 1})
    assert var_ref != 0
    assert debugger.variable_manager.var_refs
    debugger._session_facade.current_stack_frames[1] = [{"id": 1, "name": "frame"}]

    await debugger.hot_reload(str(module_file.resolve()), {"invalidatePycache": False})

    assert debugger.variable_manager.var_refs == {}
    assert debugger.variable_manager.next_var_ref == debugger.variable_manager.DEFAULT_START_REF
    assert debugger._session_facade.current_stack_frames == {}

    sys.modules.pop(module_name, None)


@pytest.mark.asyncio
async def test_hot_reload_updates_frame_code_when_compatible(tmp_path: Path) -> None:
    module_name = f"hot_reload_frame_code_ok_{id(tmp_path)}"
    module_file = tmp_path / f"{module_name}.py"
    module_file.write_text("def target(x):\n    return x + 1\n", encoding="utf-8")
    module = _load_temp_module(module_name, module_file)

    frame = _CodeFrameLike({"fn": module.target}, module.target.__code__)

    debugger = PyDebugger(Mock())
    fake_backend = _FakeInProcessBackend()
    cast("Any", debugger)._inproc_backend = cast("Any", fake_backend)

    service = cast("Any", debugger)._hot_reload_service
    service._iter_live_frames = lambda: [frame]

    module_file.write_text("def target(x):\n    return x + 2\n", encoding="utf-8")

    body = await debugger.hot_reload(str(module_file.resolve()))

    assert body.get("updatedFrameCodes") == 1
    reloaded_module = sys.modules[module_name]
    assert frame.f_code is reloaded_module.target.__code__

    sys.modules.pop(module_name, None)


@pytest.mark.asyncio
async def test_hot_reload_skips_frame_code_when_incompatible(tmp_path: Path) -> None:
    module_name = f"hot_reload_frame_code_bad_{id(tmp_path)}"
    module_file = tmp_path / f"{module_name}.py"
    module_file.write_text("def target(x):\n    return x + 1\n", encoding="utf-8")
    module = _load_temp_module(module_name, module_file)

    old_code = module.target.__code__
    frame = _CodeFrameLike({"fn": module.target}, old_code)

    debugger = PyDebugger(Mock())
    fake_backend = _FakeInProcessBackend()
    cast("Any", debugger)._inproc_backend = cast("Any", fake_backend)

    service = cast("Any", debugger)._hot_reload_service
    service._iter_live_frames = lambda: [frame]

    module_file.write_text("def target():\n    return 2\n", encoding="utf-8")

    body = await debugger.hot_reload(str(module_file.resolve()))

    assert body.get("updatedFrameCodes") == 0
    warnings = body.get("warnings") or []
    assert any("co_argcount changed" in warning for warning in warnings)
    assert frame.f_code is old_code

    sys.modules.pop(module_name, None)


@pytest.mark.asyncio
async def test_hot_reload_warns_and_skips_closure_rebinding(tmp_path: Path) -> None:
    module_name = f"hot_reload_closure_mod_{id(tmp_path)}"
    module_file = tmp_path / f"{module_name}.py"
    module_file.write_text(
        "def make_closure():\n"
        "    x = 1\n"
        "    def closure():\n"
        "        return x\n"
        "    return closure\n"
        "closure = make_closure()\n",
        encoding="utf-8",
    )
    module = _load_temp_module(module_name, module_file)

    frame = _FrameLike({"fn": module.closure})

    debugger = PyDebugger(Mock())
    fake_backend = _FakeInProcessBackend()
    cast("Any", debugger)._inproc_backend = cast("Any", fake_backend)

    service = cast("Any", debugger)._hot_reload_service
    service._iter_live_frames = lambda: [frame]

    module_file.write_text(
        "def make_closure():\n"
        "    x = 2\n"
        "    def closure():\n"
        "        return x\n"
        "    return closure\n"
        "closure = make_closure()\n",
        encoding="utf-8",
    )

    body = await debugger.hot_reload(str(module_file.resolve()))

    assert body.get("reboundFrames") == 0
    warnings = body.get("warnings") or []
    assert any("Closure function closure() skipped" in warning for warning in warnings)
    assert frame.f_locals["fn"]() == 1

    sys.modules.pop(module_name, None)


@pytest.mark.asyncio
async def test_hot_reload_rejects_c_extension_module_path(tmp_path: Path) -> None:
    extension_file = tmp_path / "native_mod.so"
    extension_file.write_bytes(b"\x00")

    debugger = PyDebugger(Mock())
    fake_backend = _FakeInProcessBackend()
    cast("Any", debugger)._inproc_backend = cast("Any", fake_backend)

    with pytest.raises(ValueError, match="Cannot reload C extension module"):
        await debugger.hot_reload(str(extension_file.resolve()))


@pytest.mark.asyncio
async def test_hot_reload_requires_inprocess_backend(tmp_path: Path) -> None:
    reset_frame_eval_telemetry()

    module_file = tmp_path / "plain.py"
    module_file.write_text("VALUE = 10\n", encoding="utf-8")

    debugger = PyDebugger(Mock())

    with pytest.raises(RuntimeError, match="in-process"):
        await debugger.hot_reload(str(module_file.resolve()), {"invalidatePycache": False})

    snapshot = get_frame_eval_telemetry()
    assert snapshot.reason_counts.hot_reload_failed >= 1


def test_resolve_module_for_path(tmp_path: Path) -> None:
    module_name = f"source_tracker_mod_{id(tmp_path)}"
    module_file = tmp_path / f"{module_name}.py"
    module_file.write_text("VALUE = 5\n", encoding="utf-8")
    module = _load_temp_module(module_name, module_file)

    tracker = LoadedSourceTracker()
    found = tracker.resolve_module_for_path(module_file)

    assert found is not None
    resolved_name, resolved_module = found
    assert resolved_name == module_name
    assert resolved_module is module

    sys.modules.pop(module_name, None)
