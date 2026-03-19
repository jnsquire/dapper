from __future__ import annotations

from pathlib import Path
import sys


def _add_src_to_sys_path() -> None:
    workspace_root = Path(__file__).resolve().parent
    src_path = workspace_root / "src"

    if src_path.is_dir():
        src_string = str(src_path)
        if src_string not in sys.path:
            sys.path.insert(0, src_string)


_add_src_to_sys_path()
