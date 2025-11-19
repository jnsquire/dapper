#!/usr/bin/env python3
"""

import sys
from pathlib import Path

# Add the project root to the Python path
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

Simple test script for frame evaluation functionality."""

try:
    from dapper._frame_eval import enable_frame_eval
    from dapper._frame_eval import is_frame_eval_available
    import dapper._frame_eval

    print(f"CYTHON_AVAILABLE: {dapper._frame_eval.CYTHON_AVAILABLE}")
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
