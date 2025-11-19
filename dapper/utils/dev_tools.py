"""Small developer helpers used for console entry points.

Keep these tiny and import-safe; they are installed into the environment as
console scripts so tools like `uv run <name>` can invoke them.
"""

from __future__ import annotations

import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


class JSTestsFailedError(RuntimeError):
    def __init__(self, returncode: int, message: str | None = None):
        super().__init__(message or f"JS tests failed with exit code {returncode}")
        self.returncode = int(returncode)


def run_js_tests(js_args: list[str] | None = None) -> None:
    """Run the extension's JS tests and raise JSTestsFailedError on failure.

    This matches the behavior used in `tests/conftest.py` so `uv run pytest`
    and `uv run test` both run JS tests exactly once.
    """
    # Allow opt-out via environment variable for CI or dev workflows
    if str(os.getenv("DAPPER_SKIP_JS_TESTS", "0")).lower() in ("1", "true", "yes"):
        return

    # Base extension path relative to top-level package directory
    ext_dir = Path(__file__).resolve().parent.parent.parent / "vscode" / "extension"
    if not ext_dir.exists():
        return

    npm_bin = shutil.which("npm")
    if not npm_bin:
        return

    node_modules_dir = ext_dir / "node_modules"
    try:
        if not node_modules_dir.exists():
            subprocess.run([npm_bin, "ci"], cwd=str(ext_dir), check=True)
    except Exception as exc:  # pragma: no cover - environment specific
        # We prefer not to fail on install, log and proceed to attempt tests
        print(f"Warning: Failed to install extension dependencies: {exc!s}")

    cmd = [npm_bin, "test"]
    if js_args:
        cmd.extend(["--", *js_args])
    proc = subprocess.run(cmd, cwd=str(ext_dir), check=False)
    if proc.returncode != 0:
        raise JSTestsFailedError(proc.returncode)


def update_docs() -> None:
    """Run the scripts/update_docs.py helper as a module-style script.

    This uses runpy.run_path so it works even when the top-level 'scripts'
    directory is not a package.
    """
    script = Path(__file__).resolve().parent.parent.parent / "scripts" / "update_docs.py"
    if not script.exists():
        msg = f"update_docs script not found: {script}"
        raise SystemExit(msg)
    # Execute the script as __main__ (it calls SystemExit(main()) itself).
    runpy.run_path(str(script), run_name="__main__")


if __name__ == "__main__":
    update_docs()


def run_tests(argv: list[str] | None = None) -> None:
    """Run pytest programmatically.

    This is a thin wrapper so `uv run test` can execute the project's pytest
    suite via the same `uv` script mechanism that `docs` uses. It exits with
    the pytest exit code on failure.
    """
    # Run pytest with the current working directory as root
    # Prevent pytest conftest hook from running JS tests as run_tests will run them below
    os.environ.setdefault("DAPPER_SKIP_JS_TESTS_IN_CONFT", "1")
    if argv is None:
        argv = list(sys.argv[1:])

    # Split argv on the conventional '--' separator to allow passing args to
    # the JS test runner while the rest are passed to pytest. Example:
    # `uv run test -k mytest -- --runInBand`
    js_args = None
    if "--" in argv:
        sep = argv.index("--")
        js_args = argv[sep + 1 :] if sep + 1 < len(argv) else []
        argv = argv[:sep]

    rc = pytest.main(argv)
    if rc != 0:
        raise SystemExit(rc)
    # Run JS tests after pytest completes
    try:
        run_js_tests(js_args)
    except JSTestsFailedError as exc:
        raise SystemExit(exc.returncode) from exc
