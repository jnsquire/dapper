"""Compatibility policy for frame evaluation runtime.

Centralizes Python/platform/environment compatibility checks so all call sites
use a single, authoritative decision model.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from collections.abc import Mapping


class FrameEvalCompatibilityPolicy:
    """Policy object for frame evaluation compatibility checks."""

    def __init__(
        self,
        *,
        min_python: tuple[int, int] = (3, 9),
        max_python: tuple[int, int] = (3, 14),
        supported_platforms: tuple[str, ...] = ("Windows", "Linux", "Darwin"),
        supported_architectures: tuple[str, ...] = ("64bit", "32bit"),
        incompatible_debuggers: tuple[str, ...] = ("pydevd", "pdb", "ipdb"),
        incompatible_environment_vars: tuple[str, ...] = ("PYCHARM_HOSTED", "VSCODE_PID"),
        incompatible_coverage_tools: tuple[str, ...] = ("coverage", "pytest_cov"),
    ) -> None:
        self.min_python = min_python
        self.max_python = max_python
        self.supported_platforms = supported_platforms
        self.supported_architectures = supported_architectures
        self.incompatible_debuggers = incompatible_debuggers
        self.incompatible_environment_vars = incompatible_environment_vars
        self.incompatible_coverage_tools = incompatible_coverage_tools

    @staticmethod
    def _version_tuple(version_info: Any) -> tuple[int, int, int]:
        return (
            int(getattr(version_info, "major", 0)),
            int(getattr(version_info, "minor", 0)),
            int(getattr(version_info, "micro", 0)),
        )

    def is_supported_python(self, version_info: Any) -> tuple[bool, str]:
        """Return whether Python version is supported and reason if not."""
        major, minor, _micro = self._version_tuple(version_info)
        version_tuple = (major, minor)

        if version_tuple < self.min_python:
            min_major, min_minor = self.min_python
            return False, f"Python version too old (requires {min_major}.{min_minor}+)"

        if version_tuple > self.max_python:
            max_major, max_minor = self.max_python
            return False, f"Python version too new (supports up to {max_major}.{max_minor})"

        return True, ""

    def is_supported_platform(self, platform_system: str, architecture: str) -> bool:
        """Return whether platform and architecture are supported."""
        return (
            platform_system in self.supported_platforms
            and architecture in self.supported_architectures
        )

    @staticmethod
    def supports_sys_monitoring() -> bool:
        """Return True if this interpreter supports the sys.monitoring API.

        sys.monitoring was added in CPython 3.12. The check is against the
        running interpreter, not the configured min/max_python range.
        """
        return sys.version_info >= (3, 12) and hasattr(sys, "monitoring")

    def is_incompatible_environment(
        self, modules: dict[str, Any], environ: Mapping[str, str]
    ) -> bool:
        """Return whether runtime environment is known-incompatible."""
        if any(name in modules for name in self.incompatible_debuggers):
            return True

        if any(env_var in environ for env_var in self.incompatible_environment_vars):
            return True

        return bool(any(name in modules for name in self.incompatible_coverage_tools))

    def evaluate_environment(
        self,
        *,
        version_info: Any,
        platform_name: str,
        platform_system: str,
        architecture: str,
        implementation: str,
        modules: dict[str, Any],
        environ: Mapping[str, str],
    ) -> dict[str, Any]:
        """Build full compatibility response for the current runtime."""
        major, minor, micro = self._version_tuple(version_info)
        compatibility = {
            "compatible": False,
            "reason": "",
            "python_version": f"{major}.{minor}.{micro}",
            "platform": platform_name,
            "architecture": architecture,
            "implementation": implementation,
        }

        python_supported, reason = self.is_supported_python(version_info)
        if not python_supported:
            compatibility["reason"] = reason
            return compatibility

        if not self.is_supported_platform(platform_system, architecture):
            compatibility["reason"] = f"Platform {platform_name} not supported"
            return compatibility

        if self.is_incompatible_environment(modules, environ):
            compatibility["reason"] = (
                "Running in incompatible environment (debugger or IDE detected)"
            )
            return compatibility

        compatibility["compatible"] = True
        return compatibility
