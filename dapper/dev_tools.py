"""Small developer helpers used for console entry points.

Keep these tiny and import-safe; they are installed into the environment as
console scripts so tools like `uv run <name>` can invoke them.
"""
from __future__ import annotations

import runpy
from pathlib import Path


def update_docs() -> None:
    """Run the scripts/update_docs.py helper as a module-style script.

    This uses runpy.run_path so it works even when the top-level 'scripts'
    directory is not a package.
    """
    root = Path(__file__).resolve().parent.parent
    script = root / "scripts" / "update_docs.py"
    if not script.exists():
        msg = f"update_docs script not found: {script}"
        raise SystemExit(msg)
    # Execute the script as __main__ (it calls SystemExit(main()) itself).
    runpy.run_path(str(script), run_name="__main__")


if __name__ == "__main__":
    update_docs()
