"""
Build script for frame evaluation Cython extensions (dev helper).

Moved into `scripts/` so it lives with other developer tooling. The
script determines the repository root automatically and operates from
there so behavior remains the same after relocation.
"""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys


def run_command(cmd, cwd=None):
    """Run a command and return the result."""
    print(f"Running: {cmd}")
    result = subprocess.run(cmd, check=False, shell=True, cwd=cwd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return result.returncode == 0


REPO_ROOT = Path(__file__).resolve().parent.parent
FRAME_EVAL_DIR = REPO_ROOT / "dapper" / "_frame_eval"
ARTIFACTS_ROOT = REPO_ROOT / "build" / "frame-eval"
BUILD_LIB_DIR = ARTIFACTS_ROOT / "lib"
BUILD_TEMP_DIR = ARTIFACTS_ROOT / "temp"
CYTHON_BUILD_DIR = ARTIFACTS_ROOT / "cython"


def _remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        path.unlink(missing_ok=True)


def clean_build():
    """Clean build artifacts."""
    print("Cleaning build artifacts...")

    # Remove dedicated frame-eval artifact tree.
    _remove_path(ARTIFACTS_ROOT)

    # Clean up legacy inline artifacts from previous --inplace builds.
    for pattern in ["_frame_evaluator*.so", "_frame_evaluator*.pyd", "*.html"]:
        for file in FRAME_EVAL_DIR.glob(pattern):
            if file.is_file():
                file.unlink(missing_ok=True)

    print("Clean completed.")


def build_development():
    """Build in development mode with verbose output."""
    print("Building frame evaluation extensions (development mode)...")

    # Set environment variables for development
    env = os.environ.copy()
    env["CYTHON_ANNOTATE"] = "1"  # Generate HTML annotation files
    env["CYTHON_BUILD_DIR"] = str(CYTHON_BUILD_DIR)

    BUILD_LIB_DIR.mkdir(parents=True, exist_ok=True)
    BUILD_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    CYTHON_BUILD_DIR.mkdir(parents=True, exist_ok=True)

    # Build into dedicated artifacts directory from repository root.
    cmd = [
        sys.executable,
        "setup.py",
        "build_ext",
        "--verbose",
        "--build-lib",
        str(BUILD_LIB_DIR),
        "--build-temp",
        str(BUILD_TEMP_DIR),
    ]

    result = subprocess.run(cmd, check=False, env=env, cwd=REPO_ROOT)
    if result.returncode == 0:
        print(f"Build artifacts: {ARTIFACTS_ROOT}")
    return result.returncode == 0


def build_production():
    """Build in production mode."""
    print("Building frame evaluation extensions (production mode)...")

    env = os.environ.copy()
    env["CYTHON_ANNOTATE"] = "0"
    env["CYTHON_BUILD_DIR"] = str(CYTHON_BUILD_DIR)

    BUILD_LIB_DIR.mkdir(parents=True, exist_ok=True)
    BUILD_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    CYTHON_BUILD_DIR.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "setup.py",
        "build_ext",
        "--build-lib",
        str(BUILD_LIB_DIR),
        "--build-temp",
        str(BUILD_TEMP_DIR),
    ]

    result = subprocess.run(cmd, check=False, cwd=REPO_ROOT, env=env)
    if result.returncode == 0:
        print(f"Build artifacts: {ARTIFACTS_ROOT}")
    return result.returncode == 0


def install_dev():
    """Install in development mode with frame evaluation."""
    print("Installing Dapper in development mode with frame evaluation...")

    cmd = [sys.executable, "-m", "pip", "install", "-e", " .[dev,frame-eval]"]
    # run_command uses shell=True so join into a single string
    return run_command(" ".join(cmd), cwd=REPO_ROOT)


def test_frame_eval():
    """Test frame evaluation functionality."""
    print("Testing frame evaluation...")

    test_code = """
import sys
sys.path.insert(0, ".")
sys.path.insert(0, r"__BUILD_LIB_DIR__")

try:
    from dapper._frame_eval import is_frame_eval_available, enable_frame_eval

    print(f"Frame eval available: {is_frame_eval_available()}")

    if is_frame_eval_available():
        success = enable_frame_eval()
        print(f"Frame eval enabled: {success}")
    else:
        print("Frame evaluation not available on this Python version")

except ImportError as e:
    print(f"Import error: {e}")
except Exception as e:
    print(f"Error: {e}")
"""
    test_code = test_code.replace("__BUILD_LIB_DIR__", str(BUILD_LIB_DIR))

    result = subprocess.run([sys.executable, "-c", test_code], check=False, cwd=REPO_ROOT)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="Build script for Dapper frame evaluation")
    parser.add_argument(
        "command",
        choices=["clean", "build-dev", "build-prod", "install-dev", "test"],
        help="Command to run",
    )

    args = parser.parse_args()

    if args.command == "clean":
        clean_build()
    elif args.command == "build-dev":
        success = build_development()
        sys.exit(0 if success else 1)
    elif args.command == "build-prod":
        success = build_production()
        sys.exit(0 if success else 1)
    elif args.command == "install-dev":
        success = install_dev()
        sys.exit(0 if success else 1)
    elif args.command == "test":
        success = test_frame_eval()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
