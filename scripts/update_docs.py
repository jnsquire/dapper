#!/usr/bin/env python3
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
import shutil
import subprocess
import sys
from pathlib import Path

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
        raise SystemExit("npx not found; please install Node.js or run the provided render scripts")

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


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true", help="Force re-rendering of all diagrams")
    args = p.parse_args()

    try:
        render_diagrams(args.force)
    except subprocess.CalledProcessError as e:
        print("Rendering step failed:", e)
        return 2

    try:
        build_mkdocs()
    except subprocess.CalledProcessError as e:
        print("MkDocs build failed:", e)
        return 3

    print("Docs updated in ./site/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
