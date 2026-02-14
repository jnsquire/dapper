import os
from pathlib import Path
import sys

from setuptools import Extension
from setuptools import find_packages
from setuptools import setup
from setuptools.command.build_ext import build_ext
from setuptools.dist import Distribution

# Try to import Cython, but make it optional
try:
    from Cython.Build import cythonize
    from Cython.Distutils.build_ext import build_ext as cython_build_ext

    CYTHON_AVAILABLE = True
except ImportError:
    CYTHON_AVAILABLE = False
    cythonize = None
    cython_build_ext = None


class BuildExt(build_ext):
    """Custom build_ext to handle optional Cython compilation."""

    def build_extensions(self):
        # If Cython is not available, skip Cython extensions
        if not CYTHON_AVAILABLE:
            # Filter out Cython extensions
            self.extensions = [
                ext for ext in self.extensions if not ext.name.startswith("dapper._frame_eval")
            ]
            if not self.extensions:
                print("Cython not available - skipping frame evaluation extensions")
                return

        super().build_extensions()


def get_frame_eval_extensions():
    """Get Cython extensions for frame evaluation if available."""
    if not CYTHON_AVAILABLE:
        return []

    # Get the base directory
    base_dir = Path(__file__).parent.resolve()

    # Define the frame evaluation extensions
    extensions = []

    # Core frame evaluator
    frame_evaluator_ext = Extension(
        "dapper._frame_eval._frame_evaluator",
        sources=[str(Path("dapper") / "_frame_eval" / "_frame_evaluator.pyx")],
        include_dirs=[str(base_dir / "dapper" / "_frame_eval")],
        define_macros=[("NPY_NO_DEPRECATED_API", "NPY_1_7_API_VERSION")],
        extra_compile_args=["-O3"] if sys.platform != "win32" else ["/O2"],
    )
    extensions.append(frame_evaluator_ext)

    return extensions


def get_extensions():
    """Get all extensions for the build."""
    extensions = []

    # Add frame evaluation extensions if available
    frame_eval_exts = get_frame_eval_extensions()
    extensions.extend(frame_eval_exts)

    # Cythonize extensions if Cython is available
    if CYTHON_AVAILABLE and frame_eval_exts and cythonize is not None:
        cython_extensions = cythonize(
            extensions,
            compiler_directives={
                "language_level": "3",
                "boundscheck": False,
                "wraparound": False,
                "initializedcheck": False,
                "cdivision": True,
                "embedsignature": True,
            },
            annotate=str(os.environ.get("CYTHON_ANNOTATE", "0")).lower() == "1",
        )
        if cython_extensions is not None:
            extensions = cython_extensions

    return extensions


# Determine if we should include frame evaluation extensions.
# Include them whenever Cython is available in the build environment. This
# ensures `uv build` (which installs build-time requirements) will compile
# the Cython components.
include_frame_eval = CYTHON_AVAILABLE


# Custom Distribution class to force platform-specific wheels
class BinaryDistribution(Distribution):
    """Distribution which always forces a binary package with platform name."""

    def has_ext_modules(self):
        return True


# Setup configuration
setup_kwargs = {
    "distclass": BinaryDistribution,
    "name": "dapper",
    "version": "0.3.0",
    "description": "Debug Adapter Protocol implementation for Python",
    "author": "Joel Squire",
    "author_email": "joel@squire.org",
    "packages": find_packages(),
    "include_package_data": True,
    "install_requires": [
        "pyright>=1.1.405",
    ],
    "extras_require": {
        "dev": [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.18.0",
            "pytest-cov>=3.0.0",
            "black>=22.0.0",
            "isort>=5.10.0",
            "mypy>=0.940",
        ],
        "frame-eval": [
            "Cython>=3.0",
        ],
    },
    "python_requires": ">=3.9",
    "options": {
        "bdist_wheel": {
            "universal": False,  # This ensures platform-specific wheels are built
            "dist_dir": "dist",  # Output directory for wheels
            "py_limited_api": False,  # Don't use Python's limited API
        }
    },
    "classifiers": [
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Cython",
        "Topic :: Software Development :: Debuggers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    "cmdclass": {"build_ext": BuildExt},
}

# Add extensions if frame evaluation is included
if include_frame_eval:
    setup_kwargs["ext_modules"] = get_extensions()

# Run setup
setup(**setup_kwargs)
