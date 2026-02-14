"""Source and module introspection utilities.

This module provides the SourceIntrospection class that encapsulates
logic for discovering and listing Python source files and modules.
Used by PyDebugger to respond to DAP loadedSources and modules requests.
"""

from __future__ import annotations

import linecache
from pathlib import Path
import sys
from typing import TYPE_CHECKING
from typing import Any
from typing import cast

if TYPE_CHECKING:
    from dapper.protocol.requests import Module
    from dapper.protocol.structures import Source


class LoadedSourceTracker:
    """Utility class for introspecting Python sources and modules.

    This class provides methods to discover loaded Python source files
    and modules, used for DAP loadedSources and modules requests.
    """

    def __init__(self, program_path: str | None = None) -> None:
        """Initialize with optional program path.

        Args:
            program_path: Path to the main program being debugged
        """
        self._program_path = program_path

    @property
    def program_path(self) -> str | None:
        """Get the current program path."""
        return self._program_path

    @program_path.setter
    def program_path(self, value: str | None) -> None:
        """Set the program path."""
        self._program_path = value

    # ------------------------------------------------------------------
    # Path utilities
    # ------------------------------------------------------------------
    def is_python_source_file(self, filename: str | Path) -> bool:
        """Check if a filename is a Python source file."""
        try:
            return str(filename).endswith((".py", ".pyw"))
        except Exception:
            return False

    def resolve_path(self, filename: str | Path) -> Path | None:
        """Resolve a filename to an absolute Path, or None on error."""
        try:
            return Path(filename).resolve()
        except Exception:
            return None

    def make_source(self, path: Path, origin: str, name: str | None = None) -> Source:
        """Create a DAP Source object from a path.

        Args:
            path: The resolved file path
            origin: Origin string (e.g., 'module:foo', 'linecache', 'main')
            name: Optional display name (defaults to path.name)

        Returns:
            A DAP Source dictionary
        """
        src: dict[str, Any] = {
            "name": name or path.name,
            "path": str(path),
        }
        if origin:
            src["origin"] = origin
        return cast("Source", src)

    # ------------------------------------------------------------------
    # Source collection helpers
    # ------------------------------------------------------------------
    def try_add_source(
        self,
        seen_paths: set[str],
        loaded_sources: list[Source],
        filename: str | Path,
        *,
        origin: str = "",
        name: str | None = None,
        check_exists: bool = False,
    ) -> None:
        """Try to add a source file to the collection if valid.

        Args:
            seen_paths: Set of already-seen absolute paths (modified in place)
            loaded_sources: List to append Source objects to (modified in place)
            filename: The filename to potentially add
            origin: Origin string for the source
            name: Optional display name
            check_exists: If True, verify the file exists before adding
        """
        if not self.is_python_source_file(filename):
            return
        path = self.resolve_path(filename)
        if path is None or (abs_path := str(path)) in seen_paths:
            return
        if check_exists and not path.exists():
            return
        seen_paths.add(abs_path)
        loaded_sources.append(self.make_source(path, origin, name))

    def iter_python_module_files(self):
        """Iterate over loaded Python module files.

        Yields:
            Tuples of (module_name, resolved_path, origin_string)
        """
        # Iterate over a snapshot to avoid 'dictionary changed size during iteration'
        # if imports occur while scanning.
        for module_name, module in list(sys.modules.items()):
            if module is None:
                continue
            try:
                module_file = getattr(module, "__file__", None)
                if not module_file:
                    continue
                path = self.resolve_path(module_file)
                if path is None or not self.is_python_source_file(path):
                    continue
                package = getattr(module, "__package__", None)
                origin = f"module:{package or module_name}"
                yield module_name, path, origin
            except Exception:
                continue

    # ------------------------------------------------------------------
    # Main introspection methods
    # ------------------------------------------------------------------
    def get_loaded_sources(self) -> list[Source]:
        """Get all loaded source files.

        Returns:
            List of DAP Source objects for all loaded Python files
        """
        loaded_sources: list[Source] = []
        seen_paths: set[str] = set()

        # Add sources from loaded modules
        for _name, path, origin in self.iter_python_module_files():
            self.try_add_source(
                seen_paths,
                loaded_sources,
                path,
                origin=origin,
                name=path.name,
                check_exists=False,
            )

        # Add sources from linecache
        for filename in list(linecache.cache.keys()):
            self.try_add_source(
                seen_paths,
                loaded_sources,
                filename,
                origin="linecache",
                check_exists=True,
            )

        # Add the main program if set
        if self._program_path:
            self.try_add_source(
                seen_paths,
                loaded_sources,
                self._program_path,
                origin="main",
                check_exists=True,
            )

        loaded_sources.sort(key=lambda s: s.get("name", ""))
        return loaded_sources

    def get_modules(self) -> list[Module]:
        """Get all loaded Python modules.

        Returns:
            List of DAP Module objects for all loaded modules
        """
        all_modules: list[Module] = []

        for name, module in sys.modules.items():
            if module is None:
                continue

            module_id = str(id(module))

            path = None
            try:
                if hasattr(module, "__file__") and module.__file__:
                    path = module.__file__
            except Exception:
                pass

            is_user_code = False
            if path:
                is_user_code = (
                    not path.startswith(sys.prefix)
                    and not path.startswith(sys.base_prefix)
                    and "site-packages" not in path
                )

            module_obj: Module = {
                "id": module_id,
                "name": name,
                "isUserCode": is_user_code,
            }
            if path:
                module_obj["path"] = path

            all_modules.append(module_obj)

        all_modules.sort(key=lambda m: m["name"])
        return all_modules
