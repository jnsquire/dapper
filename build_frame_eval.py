#!/usr/bin/env python3
"""
Build script for frame evaluation Cython extensions.

This script helps with development by providing easy commands to build
and test the frame evaluation extensions.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path


def run_command(cmd, cwd=None):
    """Run a command and return the result."""
    print(f"Running: {cmd}")
    result = subprocess.run(cmd, check=False, shell=True, cwd=cwd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return result.returncode == 0

def clean_build():
    """Clean build artifacts."""
    print("Cleaning build artifacts...")
    base_dir = Path(__file__).parent
    
    # Remove build directories
    for build_dir in ["build", "dist"]:
        if (base_dir / build_dir).exists():
            run_command(f"rmdir /s /q {build_dir}" if sys.platform == "win32" else f"rm -rf {build_dir}")
    
    # Remove Cython generated files
    for pattern in ["**/*.c", "**/*.so", "**/*.pyd", "**/*.html"]:
        for file in base_dir.glob(pattern):
            if file.is_file():
                file.unlink()
    
    # Remove __pycache__ directories
    for pycache in base_dir.rglob("__pycache__"):
        if pycache.is_dir():
            run_command(f"rmdir /s /q {pycache}" if sys.platform == "win32" else f"rm -rf {pycache}")
    
    print("Clean completed.")

def build_development():
    """Build in development mode with verbose output."""
    print("Building frame evaluation extensions (development mode)...")
    
    # Set environment variables for development
    env = os.environ.copy()
    env["CYTHON_ANNOTATE"] = "1"  # Generate HTML annotation files
    
    # Build with verbose output
    cmd = [
        sys.executable, "setup.py", 
        "build_ext", "--inplace", "--verbose"
    ]
    
    result = subprocess.run(cmd, check=False, env=env)
    return result.returncode == 0

def build_production():
    """Build in production mode."""
    print("Building frame evaluation extensions (production mode)...")
    
    cmd = [
        sys.executable, "setup.py", 
        "build_ext", "--inplace"
    ]
    
    result = subprocess.run(cmd, check=False)
    return result.returncode == 0

def install_dev():
    """Install in development mode with frame evaluation."""
    print("Installing Dapper in development mode with frame evaluation...")
    
    cmd = [
        sys.executable, "-m", "pip", "install", "-e", ".[dev,frame-eval]"
    ]
    
    return run_command(" ".join(cmd))

def test_frame_eval():
    """Test frame evaluation functionality."""
    print("Testing frame evaluation...")
    
    # Try to import and test basic functionality
    test_code = """
import sys
sys.path.insert(0, ".")

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
    
    return run_command(f'{sys.executable} -c "{test_code}"')

def main():
    parser = argparse.ArgumentParser(description="Build script for Dapper frame evaluation")
    parser.add_argument("command", choices=[
        "clean", "build-dev", "build-prod", "install-dev", "test"
    ], help="Command to run")
    
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
