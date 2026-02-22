"""MkDocs hooks for Dapper docs.

Registered via `hooks: [scripts/mkdocs_hooks.py]` in mkdocs.yml.
These hooks run during both `mkdocs build` and `mkdocs serve`, so the
temporary doc files (copied/patched README, examples page) are always
available regardless of how the docs are built or served.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Keep track of patched files so we can restore them in on_post_build.
_backups: dict[Path, str] = {}


def on_pre_build(config) -> None:  # noqa: ARG001
    """Copy and patch source files before MkDocs reads them."""
    _backups.clear()

    # 1. Copy root README.md -> doc/README.md, fixing absolute links.
    #    Links written as `(doc/something)` in the root README become
    #    `(something)` once the file lives inside doc/.
    readme_src = ROOT / "README.md"
    readme_dst = ROOT / "doc" / "README.md"
    readme_content = readme_src.read_text(encoding="utf-8")
    readme_patched = readme_content.replace("(doc/", "(")
    readme_dst.write_text(readme_patched, encoding="utf-8")

    # 2. Patch any links inside the docs directory that point to paths
    #    that changed between the repo layout and the mkdocs layout.
    #    Add (path, old_str, new_str) tuples here as needed.
    patches: list[tuple[Path, str, str]] = []
    for path, old, new in patches:
        if path.exists():
            original = path.read_text(encoding="utf-8")
            if old in original:
                _backups[path] = original
                path.write_text(original.replace(old, new), encoding="utf-8")


def on_post_build(config) -> None:  # noqa: ARG001
    """Restore any in-place patched files after the build completes.

    We intentionally leave doc/README.md on disk so that `mkdocs serve`
    (watch mode) can find it on subsequent reloads without triggering an
    extra rebuild cycle.  The file is regenerated fresh on every
    on_pre_build call, so it never goes stale.  It is listed in .gitignore
    so it is not accidentally committed.
    """
    # Restore any in-place patched files.
    for path, original in _backups.items():
        path.write_text(original, encoding="utf-8")
    _backups.clear()
