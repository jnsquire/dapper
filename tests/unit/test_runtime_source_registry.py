"""Unit tests for RuntimeSourceRegistry and related helpers."""

from __future__ import annotations

import io
import linecache
import threading

import pytest

import dapper.shared.debug_shared as ds
from dapper.shared.runtime_source_registry import RuntimeSourceEntry
from dapper.shared.runtime_source_registry import RuntimeSourceRegistry
from dapper.shared.runtime_source_registry import annotate_stack_frames_with_source_refs
from dapper.shared.runtime_source_registry import is_synthetic_filename

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


class _MockWFile(io.BytesIO):
    def flush(self) -> None:
        pass


@pytest.fixture
def session():
    """Yield a fresh, IPC-enabled DebugSession as the active session."""
    s = ds.DebugSession()
    s.ipc_enabled = True
    s.ipc_wfile = _MockWFile()
    with ds.use_session(s):
        yield s


# ---------------------------------------------------------------------------
# is_synthetic_filename
# ---------------------------------------------------------------------------


class TestIsSyntheticFilename:
    def test_angle_bracket_string(self) -> None:
        assert is_synthetic_filename("<string>") is True

    def test_angle_bracket_stdin(self) -> None:
        assert is_synthetic_filename("<stdin>") is True

    def test_angle_bracket_module(self) -> None:
        assert is_synthetic_filename("<module>") is True

    def test_angle_bracket_unknown(self) -> None:
        assert is_synthetic_filename("<unknown>") is True

    def test_angle_bracket_eval_with_text(self) -> None:
        assert is_synthetic_filename("<eval some expr at 0x…>") is True

    def test_angle_bracket_frozen(self) -> None:
        assert is_synthetic_filename("<frozen importlib._bootstrap>") is True

    def test_angle_bracket_ipython(self) -> None:
        assert is_synthetic_filename("<ipython-input-3-abc123>") is True

    def test_angle_bracket_template(self) -> None:
        assert is_synthetic_filename("<template /views/index.html>") is True

    def test_real_path_is_not_synthetic(self) -> None:
        assert is_synthetic_filename("/home/user/project/foo.py") is False

    def test_relative_path_not_synthetic(self) -> None:
        assert is_synthetic_filename("src/foo.py") is False

    def test_empty_string_not_synthetic(self) -> None:
        assert is_synthetic_filename("") is False

    def test_partial_bracket_not_synthetic(self) -> None:
        assert is_synthetic_filename("<no_close") is False


# ---------------------------------------------------------------------------
# RuntimeSourceEntry
# ---------------------------------------------------------------------------


class TestRuntimeSourceEntry:
    def test_repr_does_not_crash(self) -> None:
        entry = RuntimeSourceEntry(1, "<string>", "x = 1\n", None, "eval")
        # repr is optional but must not raise
        _ = repr(entry)

    def test_name_defaults_to_virtual_path_when_none(self) -> None:
        entry = RuntimeSourceEntry(1, "<string>", "", None, "eval")
        assert entry.name == "<string>"

    def test_name_uses_supplied_value(self) -> None:
        entry = RuntimeSourceEntry(1, "<string>", "", "My Source", "eval")
        assert entry.name == "My Source"


# ---------------------------------------------------------------------------
# RuntimeSourceRegistry — basic operations
# ---------------------------------------------------------------------------


class TestRuntimeSourceRegistryRegister:
    def test_register_returns_entry(self) -> None:
        reg = RuntimeSourceRegistry()
        entry = reg.register("<string>", "x = 1\n", origin="eval")
        assert isinstance(entry, RuntimeSourceEntry)
        assert entry.ref >= 1
        assert entry.source_text == "x = 1\n"
        assert entry.virtual_path == "<string>"
        assert entry.origin == "eval"

    def test_register_is_idempotent(self) -> None:
        reg = RuntimeSourceRegistry()
        e1 = reg.register("<string>", "first\n")
        e2 = reg.register("<string>", "second\n")  # same path → same entry
        assert e1 is e2
        assert e2.source_text == "first\n"  # original text not overwritten

    def test_register_different_paths(self) -> None:
        reg = RuntimeSourceRegistry()
        e1 = reg.register("<a>", "a\n")
        e2 = reg.register("<b>", "b\n")
        assert e1.ref != e2.ref

    def test_ref_hint_adopted_when_free(self) -> None:
        reg = RuntimeSourceRegistry()
        entry = reg.register("<string>", "x\n", ref_hint=42)
        assert entry.ref == 42

    def test_ref_hint_ignored_when_taken(self) -> None:
        reg = RuntimeSourceRegistry()
        e1 = reg.register("<a>", "a\n", ref_hint=5)
        assert e1.ref == 5
        e2 = reg.register("<b>", "b\n", ref_hint=5)  # 5 already used
        assert e2.ref != 5

    def test_name_falls_back_to_virtual_path(self) -> None:
        reg = RuntimeSourceRegistry()
        entry = reg.register("<string>", "x\n")
        assert entry.name == "<string>"

    def test_name_supplied(self) -> None:
        reg = RuntimeSourceRegistry()
        entry = reg.register("<string>", "x\n", name="Eval snippet")
        assert entry.name == "Eval snippet"

    def test_leading_trailing_whitespace_normalised(self) -> None:
        reg = RuntimeSourceRegistry()
        e1 = reg.register("  <string>  ", "x\n")
        e2 = reg.register("<string>", "y\n")  # same key after strip
        assert e1 is e2


# ---------------------------------------------------------------------------
# RuntimeSourceRegistry — lookup
# ---------------------------------------------------------------------------


class TestRuntimeSourceRegistryLookup:
    def test_get_by_ref_returns_entry(self) -> None:
        reg = RuntimeSourceRegistry()
        entry = reg.register("<string>", "x\n")
        found = reg.get_by_ref(entry.ref)
        assert found is entry

    def test_get_by_ref_missing_returns_none(self) -> None:
        reg = RuntimeSourceRegistry()
        assert reg.get_by_ref(99999) is None

    def test_get_by_path_returns_entry(self) -> None:
        reg = RuntimeSourceRegistry()
        entry = reg.register("<string>", "x\n")
        found = reg.get_by_path("<string>")
        assert found is entry

    def test_get_by_path_missing_returns_none(self) -> None:
        reg = RuntimeSourceRegistry()
        assert reg.get_by_path("<not_there>") is None

    def test_get_source_text_by_ref(self) -> None:
        reg = RuntimeSourceRegistry()
        entry = reg.register("<string>", "hello\n")
        assert reg.get_source_text(entry.ref) == "hello\n"

    def test_get_source_text_missing_ref_returns_none(self) -> None:
        reg = RuntimeSourceRegistry()
        assert reg.get_source_text(12345) is None

    def test_get_source_text_by_path(self) -> None:
        reg = RuntimeSourceRegistry()
        reg.register("<eval>", "y = 2\n")
        assert reg.get_source_text_by_path("<eval>") == "y = 2\n"

    def test_get_source_text_by_path_missing_returns_none(self) -> None:
        reg = RuntimeSourceRegistry()
        assert reg.get_source_text_by_path("<nope>") is None


# ---------------------------------------------------------------------------
# RuntimeSourceRegistry — update
# ---------------------------------------------------------------------------


class TestRuntimeSourceRegistryUpdate:
    def test_update_existing_path(self) -> None:
        reg = RuntimeSourceRegistry()
        entry = reg.register("<string>", "v1\n")
        updated = reg.update("<string>", "v2\n")
        assert updated is True
        assert entry.source_text == "v2\n"

    def test_update_non_existing_returns_false(self) -> None:
        reg = RuntimeSourceRegistry()
        updated = reg.update("<not_registered>", "x\n")
        assert updated is False

    def test_update_does_not_create_entry(self) -> None:
        reg = RuntimeSourceRegistry()
        reg.update("<new>", "x\n")
        assert len(reg) == 0


# ---------------------------------------------------------------------------
# RuntimeSourceRegistry — linecache
# ---------------------------------------------------------------------------


class TestRuntimeSourceRegistryLinecache:
    def test_get_or_register_from_linecache_present(self) -> None:
        key = "<test-eval-123>"
        src = "z = 42\n"
        linecache.cache[key] = (len(src), None, [src], key)
        try:
            reg = RuntimeSourceRegistry()
            entry = reg.get_or_register_from_linecache(key)
            assert entry is not None
            assert entry.source_text == src
            assert entry.origin == "linecache-dynamic"
        finally:
            linecache.cache.pop(key, None)

    def test_get_or_register_from_linecache_absent_returns_none(self) -> None:
        reg = RuntimeSourceRegistry()
        result = reg.get_or_register_from_linecache("<definitely-not-in-linecache-xyz>")
        assert result is None

    def test_get_or_register_from_linecache_idempotent(self) -> None:
        key = "<eval-idem>"
        src = "w = 0\n"
        linecache.cache[key] = (len(src), None, [src], key)
        try:
            reg = RuntimeSourceRegistry()
            e1 = reg.get_or_register_from_linecache(key)
            e2 = reg.get_or_register_from_linecache(key)  # second call
            assert e1 is e2
        finally:
            linecache.cache.pop(key, None)


# ---------------------------------------------------------------------------
# RuntimeSourceRegistry — introspection
# ---------------------------------------------------------------------------


class TestRuntimeSourceRegistryIntrospection:
    def test_len(self) -> None:
        reg = RuntimeSourceRegistry()
        assert len(reg) == 0
        reg.register("<a>", "a\n")
        assert len(reg) == 1
        reg.register("<b>", "b\n")
        assert len(reg) == 2

    def test_all_entries_sorted_by_ref(self) -> None:
        reg = RuntimeSourceRegistry()
        reg.register("<c>", "c\n", ref_hint=3)
        reg.register("<a>", "a\n", ref_hint=1)
        reg.register("<b>", "b\n", ref_hint=2)
        entries = reg.all_entries()
        assert [e.ref for e in entries] == [1, 2, 3]

    def test_all_entries_returns_snapshot(self) -> None:
        reg = RuntimeSourceRegistry()
        reg.register("<a>", "a\n")
        snapshot = reg.all_entries()
        reg.register("<b>", "b\n")
        assert len(snapshot) == 1  # snapshot not mutated
        assert len(reg.all_entries()) == 2

    def test_clear(self) -> None:
        reg = RuntimeSourceRegistry()
        reg.register("<a>", "a\n")
        reg.clear()
        assert len(reg) == 0
        assert reg.get_by_path("<a>") is None


# ---------------------------------------------------------------------------
# RuntimeSourceRegistry — thread safety smoke test
# ---------------------------------------------------------------------------


class TestRuntimeSourceRegistryThreadSafety:
    def test_concurrent_register(self) -> None:
        """Multiple threads registering distinct paths must not corrupt state."""
        reg = RuntimeSourceRegistry()
        errors: list[Exception] = []

        def register_many(prefix: str) -> None:
            try:
                for i in range(50):
                    reg.register(f"<{prefix}-{i}>", f"# {prefix} {i}\n")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=register_many, args=(f"t{n}",)) for n in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(reg) == 250  # 5 threads x 50 unique paths


# ---------------------------------------------------------------------------
# SourceCatalog.register_dynamic_source integration
# ---------------------------------------------------------------------------


class TestSourceCatalogDynamicSourceIntegration:
    def test_register_dynamic_source_returns_ref(self, session) -> None:
        ref = session.register_dynamic_source("<string>", "x = 1\n", origin="eval")
        assert isinstance(ref, int)
        assert ref >= 1

    def test_register_dynamic_source_is_idempotent(self, session) -> None:
        r1 = session.register_dynamic_source("<string>", "initial\n")
        r2 = session.register_dynamic_source("<string>", "updated\n")
        assert r1 == r2  # same ref re-used

    def test_get_source_content_by_ref_hits_dynamic_store(self, session) -> None:
        src = "def foo(): pass\n"
        ref = session.register_dynamic_source("<string>", src)
        assert session.get_source_content_by_ref(ref) == src

    def test_get_source_content_by_path_hits_dynamic_store(self, session) -> None:
        src = "print('hi')\n"
        session.register_dynamic_source("<stdin>", src)
        assert session.get_source_content_by_path("<stdin>") == src

    def test_dynamic_source_not_in_regular_ref_map_initially(self, session) -> None:
        # Before registration the path should not be present
        assert session.get_ref_for_path("<string>") is None

    def test_get_dynamic_sources_returns_entries(self, session) -> None:
        session.register_dynamic_source("<eval>", "e = 1\n", origin="eval")
        session.register_dynamic_source("<stdin>", "s = 2\n", origin="stdin")
        entries = session.get_dynamic_sources()
        paths = {e.virtual_path for e in entries}
        assert "<eval>" in paths
        assert "<stdin>" in paths

    def test_get_dynamic_sources_empty_initially(self, session) -> None:
        assert session.get_dynamic_sources() == []


# ---------------------------------------------------------------------------
# annotate_stack_frames_with_source_refs
# ---------------------------------------------------------------------------


class TestAnnotateStackFrames:
    @pytest.mark.usefixtures("session")
    def test_synthetic_frame_gets_source_reference(self) -> None:
        key = "<annotate-test>"
        src = "annotated = True\n"
        linecache.cache[key] = (len(src), None, [src], key)
        try:
            frames = [
                {
                    "id": 1,
                    "name": "test",
                    "source": {"name": key, "path": key},
                    "line": 1,
                    "column": 0,
                }
            ]
            annotate_stack_frames_with_source_refs(frames)
            assert "sourceReference" in frames[0]["source"]
            assert isinstance(frames[0]["source"]["sourceReference"], int)
            assert frames[0]["source"]["sourceReference"] > 0
        finally:
            linecache.cache.pop(key, None)

    @pytest.mark.usefixtures("session")
    def test_real_path_frame_not_modified(self, tmp_path) -> None:
        p = tmp_path / "real.py"
        p.write_text("x = 1\n")
        frames = [
            {
                "id": 2,
                "name": "real",
                "source": {"name": "real.py", "path": str(p)},
                "line": 1,
                "column": 0,
            }
        ]
        annotate_stack_frames_with_source_refs(frames)
        # Real paths should not have sourceReference injected by this helper
        assert "sourceReference" not in frames[0]["source"]

    @pytest.mark.usefixtures("session")
    def test_already_annotated_frame_unchanged(self) -> None:
        frames = [
            {
                "id": 3,
                "name": "already",
                "source": {"name": "<string>", "path": "<string>", "sourceReference": 99},
                "line": 1,
                "column": 0,
            }
        ]
        annotate_stack_frames_with_source_refs(frames)
        # Pre-existing sourceReference must not be overwritten
        assert frames[0]["source"]["sourceReference"] == 99

    @pytest.mark.usefixtures("session")
    def test_empty_list_does_not_crash(self) -> None:
        annotate_stack_frames_with_source_refs([])  # no exception

    def test_placeholder_registered_when_no_linecache(self, session) -> None:
        key = "<no-linecache-content-xyz>"
        linecache.cache.pop(key, None)  # ensure absent
        frames = [
            {
                "id": 4,
                "name": "nodoc",
                "source": {"name": key, "path": key},
                "line": 1,
                "column": 0,
            }
        ]
        annotate_stack_frames_with_source_refs(frames)
        ref = frames[0]["source"].get("sourceReference")
        assert ref is not None
        assert ref > 0
        # Content should be the placeholder comment
        content = session.get_source_content_by_ref(ref)
        assert content is not None
        assert key in content

    def test_source_content_retrievable_after_annotation(self, session) -> None:
        key = "<annotation-retrieve>"
        src = "retrieved = True\n"
        linecache.cache[key] = (len(src), None, [src], key)
        try:
            frames = [
                {
                    "id": 5,
                    "name": "fn",
                    "source": {"name": key, "path": key},
                    "line": 1,
                    "column": 0,
                }
            ]
            annotate_stack_frames_with_source_refs(frames)
            ref = frames[0]["source"]["sourceReference"]
            content = session.get_source_content_by_ref(ref)
            assert content == src
        finally:
            linecache.cache.pop(key, None)


# ---------------------------------------------------------------------------
# handle_loaded_sources includes dynamic sources
# ---------------------------------------------------------------------------


class TestHandleLoadedSourcesIncludesDynamic:
    def test_dynamic_source_appears_in_loaded_sources(self, session) -> None:
        from dapper.shared.source_handlers import handle_loaded_sources  # noqa: PLC0415

        session.register_dynamic_source("<my-eval>", "result = 42\n", origin="eval")

        captured: list[dict] = []

        def capture(*args, **kwargs) -> bool:
            if args[0] == "response":
                captured.append(kwargs)
            return True

        handle_loaded_sources(session, capture)

        assert captured, "safe_send_debug_message was not called"
        sources = captured[-1].get("body", {}).get("sources", [])
        dynamic_paths = [s["path"] for s in sources if s.get("sourceReference")]
        assert "<my-eval>" in dynamic_paths

    def test_dynamic_source_has_correct_ref_in_loaded_sources(self, session) -> None:
        from dapper.shared.source_handlers import handle_loaded_sources  # noqa: PLC0415

        ref = session.register_dynamic_source("<check-ref>", "pass\n")

        captured: list[dict] = []

        def capture(*args, **kwargs) -> bool:
            if args[0] == "response":
                captured.append(kwargs)
            return True

        handle_loaded_sources(session, capture)

        sources = captured[-1].get("body", {}).get("sources", [])
        matching = [s for s in sources if s.get("path") == "<check-ref>"]
        assert matching, "Expected dynamic source not found in loadedSources"
        assert matching[0]["sourceReference"] == ref
