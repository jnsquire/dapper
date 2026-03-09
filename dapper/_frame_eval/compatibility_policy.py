# ruff: noqa: PLC0415
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

    def get_incompatible_environment_reason(
        self,
        modules: dict[str, Any],
        environ: Mapping[str, str],
    ) -> str:
        """Return a specific reason for an incompatible runtime environment."""
        debugger_name = next(
            (name for name in self.incompatible_debuggers if name in modules),
            None,
        )
        if debugger_name is not None:
            return f"Incompatible debugger detected: {debugger_name}"

        env_var = next(
            (name for name in self.incompatible_environment_vars if name in environ),
            None,
        )
        if env_var is not None:
            return f"Incompatible environment variable detected: {env_var}"

        coverage_tool = next(
            (name for name in self.incompatible_coverage_tools if name in modules),
            None,
        )
        if coverage_tool is not None:
            return f"Incompatible coverage tool detected: {coverage_tool}"

        return ""

    @staticmethod
    def is_supported_implementation(implementation: str) -> tuple[bool, str]:
        """Return whether *implementation* can use eval-frame hooking."""
        if implementation != "CPython":
            return False, f"Eval-frame backend requires CPython (got {implementation})"
        return True, ""

    def supports_eval_frame(self) -> bool:
        """Return True if the runtime is capable of eval-frame hooking.

        The default implementation is conservative: it only returns ``True``
        when the compiled ``_frame_evaluator`` extension module is available
        and reports that the hook API claims to be ``available``.  This
        allows the compatibility object to serve as the central source of
        truth for feature presence without duplicating logic elsewhere.

        When the module is missing or has not yet been built, or when the
        module explicitly reports ``available=False`` (the stub state during
        Phase 2 development), this method returns ``False``.  Higher layers may
        consult other policy methods (e.g. Python version) as additional
        filters if desired.
        """
        try:
            from dapper._frame_eval._frame_evaluator import get_frame_eval_capabilities

            capabilities = get_frame_eval_capabilities()
            return bool(capabilities.get("supports_eval_frame_hook", False))
        except ImportError:
            return False
        except Exception:  # pragma: no cover - be conservative on unexpected errors
            return False

    def can_use_eval_frame(
        self,
        *,
        version_info: Any,
        platform_system: str,
        architecture: str,
        implementation: str,
        modules: dict[str, Any],
        environ: Mapping[str, str],
    ) -> tuple[bool, str]:
        """Return whether eval-frame can be used and the blocking reason if not."""
        reason = ""

        python_supported, reason = self.is_supported_python(version_info)
        if python_supported:
            if not self.is_supported_platform(platform_system, architecture):
                reason = f"Platform {platform_system} / {architecture} not supported"
            else:
                implementation_supported, implementation_reason = self.is_supported_implementation(
                    implementation
                )
                if not implementation_supported:
                    reason = implementation_reason
                else:
                    environment_reason = self.get_incompatible_environment_reason(modules, environ)
                    if environment_reason:
                        reason = environment_reason
                    elif not self.supports_eval_frame():
                        reason = self._get_eval_frame_unavailable_reason()

        if reason:
            return False, reason
        return True, ""

    @staticmethod
    def _get_eval_frame_unavailable_reason() -> str:
        try:
            from dapper._frame_eval._frame_evaluator import get_frame_eval_capabilities

            capabilities = get_frame_eval_capabilities()
            capability_reason = capabilities.get("reason")
            if isinstance(capability_reason, str) and capability_reason:
                return capability_reason
        except Exception:
            pass
        return "Eval-frame hook API not available in this runtime"

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
            "eval_frame_supported": False,
            "eval_frame_reason": "",
            "recommended_backend": "tracing",
        }

        python_supported, reason = self.is_supported_python(version_info)
        if not python_supported:
            compatibility["reason"] = reason
            return compatibility

        if not self.is_supported_platform(platform_system, architecture):
            compatibility["reason"] = f"Platform {platform_name} not supported"
            return compatibility

        if self.is_incompatible_environment(modules, environ):
            compatibility["reason"] = self.get_incompatible_environment_reason(modules, environ)
            return compatibility

        compatibility["compatible"] = True
        eval_frame_supported, eval_frame_reason = self.can_use_eval_frame(
            version_info=version_info,
            platform_system=platform_system,
            architecture=architecture,
            implementation=implementation,
            modules=modules,
            environ=environ,
        )
        compatibility["eval_frame_supported"] = eval_frame_supported
        compatibility["eval_frame_reason"] = eval_frame_reason
        compatibility["recommended_backend"] = "eval_frame" if eval_frame_supported else "tracing"
        return compatibility
