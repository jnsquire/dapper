"""
scripts/update_docs.py

Helper to update documentation locally:
 - renders Mermaid diagrams (using existing scripts)
 - runs `mkdocs build --clean --site-dir site`

Usage:
  python scripts/update_docs.py [--force]

This script is intended to be run with uv, e.g.:
  uv run python scripts/update_docs.py

It will try to invoke the platform-appropriate render script (PowerShell on
Windows, shell on POSIX). If those are not available, it will attempt to call
`npx -p @mermaid-js/mermaid-cli mmdc` directly for each .mmd file.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
RENDER_PS = ROOT / "scripts" / "render-mermaid.ps1"
RENDER_SH = ROOT / "scripts" / "render-mermaid.sh"


def run_cmd(cmd, check=True, **kwargs):
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, check=check, **kwargs)


def render_diagrams(force: bool) -> None:
    """Render diagrams using available script or npx fallback."""
    if sys.platform.startswith("win"):
        # Prefer PowerShell script
        pwsh = shutil.which("pwsh") or shutil.which("powershell")
        if pwsh and RENDER_PS.exists():
            cmd = [pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass", str(RENDER_PS)]
            if force:
                cmd.append("-Force")
            run_cmd(cmd)
            return
    else:
        sh = shutil.which("bash") or shutil.which("sh")
        if sh and RENDER_SH.exists():
            cmd = [str(RENDER_SH)]
            if force:
                cmd.append("--force")
            run_cmd(cmd)
            return

    # Fallback: try npx mmdc directly (per-file)
    print("No platform script found or no shell available; falling back to npx mmdc per-file")
    npx = shutil.which("npx")
    if not npx:
        raise SystemExit(
            "npx not found; please install Node.js or run the provided render scripts"
        )

    diagrams = list((ROOT / "doc" / "reference" / "diagrams").glob("*.mmd"))
    outdir = ROOT / "doc" / "reference" / "images"
    outdir.mkdir(parents=True, exist_ok=True)
    for m in diagrams:
        out = outdir / (m.stem + ".svg")
        if not force and out.exists() and m.stat().st_mtime <= out.stat().st_mtime:
            print(f"Skipping up-to-date: {m} -> {out}")
            continue
        print(f"Rendering {m} -> {out}")
        run_cmd([npx, "-p", "@mermaid-js/mermaid-cli", "mmdc", "-i", str(m), "-o", str(out)])


def build_mkdocs() -> None:
    mkdocs = shutil.which("mkdocs")
    if not mkdocs:
        # Try python -m mkdocs
        print("mkdocs not found on PATH, trying 'python -m mkdocs'...")
        run_cmd([sys.executable, "-m", "mkdocs", "build", "--clean", "--site-dir", "site"])
        return
    run_cmd([mkdocs, "build", "--clean", "--site-dir", "site"])


def prepare_docs_for_build() -> dict[Path, str]:
    """
    Copy root README and examples README into doc/ so MkDocs can see them.
    Patch links in existing docs to point to these local copies.
    Returns a dict of {path: original_content} for restoration.
    """
    # 1. Copy README.md -> doc/README.md and patch links
    readme_content = (ROOT / "README.md").read_text(encoding="utf-8")
    # Fix links like [Text](doc/FILE.md) -> [Text](FILE.md) since README is now inside doc/
    readme_patched = readme_content.replace("(doc/", "(")
    (ROOT / "doc" / "README.md").write_text(readme_patched, encoding="utf-8")

    # 2. Copy examples/README.md -> doc/examples.md
    shutil.copy(ROOT / "examples" / "README.md", ROOT / "doc" / "examples.md")

    # 3. Patch doc/getting-started/using-vscode.md
    #    It links to ../README.md and ../examples/README.md
    #    We want it to link to ../README.md and ../examples.md
    p = ROOT / "doc" / "getting-started" / "using-vscode.md"
    if p.exists():
        original = p.read_text(encoding="utf-8")
        patched = original.replace("../examples/README.md", "../examples.md")
        p.write_text(patched, encoding="utf-8")
        return {p: original}
    return {}


def cleanup_docs(backups: dict[Path, str]) -> None:
    """Restore patched files and remove temporary copies."""
    # Restore patched files
    for p, content in backups.items():
        p.write_text(content, encoding="utf-8")

    # Remove copies
    (ROOT / "doc" / "README.md").unlink(missing_ok=True)
    (ROOT / "doc" / "examples.md").unlink(missing_ok=True)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true", help="Force re-rendering of all diagrams")
    args = p.parse_args()

    try:
        render_diagrams(args.force)
    except subprocess.CalledProcessError as e:
        print("Rendering step failed:", e)
        return 2

    backups = {}
    try:
        print("Preparing docs for build (copying READMEs, patching links)...")
        backups = prepare_docs_for_build()
        build_mkdocs()
    except subprocess.CalledProcessError as e:
        print("MkDocs build failed:", e)
        return 3
    except Exception as e:
        print(f"Unexpected error during build: {e}")
        return 4
    finally:
        print("Cleaning up temporary doc files...")
        cleanup_docs(backups)

    print("Docs updated in ./site/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
