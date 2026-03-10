"""Unit tests for frame evaluation compatibility policy."""

from __future__ import annotations

from unittest.mock import patch

from dapper._frame_eval.compatibility_policy import FrameEvalCompatibilityPolicy


class VersionInfo:
    """Simple version-info stand-in for policy tests."""

    def __init__(self, major: int, minor: int, micro: int) -> None:
        self.major = major
        self.minor = minor
        self.micro = micro


def test_policy_python_version_bounds() -> None:
    """Policy enforces supported Python bounds inclusively."""
    policy = FrameEvalCompatibilityPolicy(min_python=(3, 9), max_python=(3, 13))

    supported, reason = policy.is_supported_python(VersionInfo(3, 9, 0))
    assert supported is True
    assert reason == ""

    supported, reason = policy.is_supported_python(VersionInfo(3, 13, 0))
    assert supported is True
    assert reason == ""

    supported, reason = policy.is_supported_python(VersionInfo(3, 8, 9))
    assert supported is False
    assert "too old" in reason

    supported, reason = policy.is_supported_python(VersionInfo(3, 14, 0))
    assert supported is False
    assert "too new" in reason


def test_policy_platform_support() -> None:
    """Policy validates platform and architecture pairs."""
    policy = FrameEvalCompatibilityPolicy(
        supported_platforms=("Windows", "Linux"),
        supported_architectures=("64bit",),
    )

    assert policy.is_supported_platform("Linux", "64bit") is True
    assert policy.is_supported_platform("Darwin", "64bit") is False
    assert policy.is_supported_platform("Linux", "32bit") is False


def test_policy_detects_incompatible_environment() -> None:
    """Policy flags known incompatible runtime environments."""
    policy = FrameEvalCompatibilityPolicy(
        incompatible_debuggers=("pdb",),
        incompatible_environment_vars=("PYCHARM_HOSTED",),
        incompatible_coverage_tools=("coverage",),
    )

    assert policy.is_incompatible_environment({"pdb": object()}, {}) is True
    assert policy.is_incompatible_environment({}, {"PYCHARM_HOSTED": "1"}) is True
    assert policy.is_incompatible_environment({"coverage": object()}, {}) is True
    assert policy.is_incompatible_environment({}, {}) is False


def test_policy_evaluate_environment_shape() -> None:
    """Policy emits compatibility payload with expected keys."""
    policy = FrameEvalCompatibilityPolicy()

    result = policy.evaluate_environment(
        version_info=VersionInfo(3, 11, 4),
        platform_name="Linux-6.8",
        platform_system="Linux",
        architecture="64bit",
        implementation="CPython",
        modules={},
        environ={},
    )

    assert result["compatible"] is True
    assert result["reason"] == ""
    assert result["python_version"] == "3.11.4"
    assert result["platform"] == "Linux-6.8"
    assert result["architecture"] == "64bit"
    assert result["implementation"] == "CPython"
    assert result["recommended_backend"] in {"eval_frame", "tracing"}


def test_policy_reports_eval_frame_specific_fallback_reason() -> None:
    """Eval-frame compatibility details should point callers at tracing when unavailable."""
    policy = FrameEvalCompatibilityPolicy()

    expected_reason = "Compiled frame-eval extension not available in this runtime"

    with (
        patch.object(policy, "supports_eval_frame", return_value=False),
        patch.object(policy, "_get_eval_frame_unavailable_reason", return_value=expected_reason),
    ):
        result = policy.evaluate_environment(
            version_info=VersionInfo(3, 11, 4),
            platform_name="Linux-6.8",
            platform_system="Linux",
            architecture="64bit",
            implementation="CPython",
            modules={},
            environ={},
        )

    assert result["compatible"] is True
    assert result["eval_frame_supported"] is False
    assert result["eval_frame_reason"] == expected_reason
    assert result["recommended_backend"] == "tracing"


def test_policy_reports_specific_incompatible_environment_reasons() -> None:
    """Each incompatible-environment category should surface its own reason string."""
    policy = FrameEvalCompatibilityPolicy(
        incompatible_debuggers=("pdb",),
        incompatible_environment_vars=("PYCHARM_HOSTED",),
        incompatible_coverage_tools=("coverage",),
    )

    assert (
        policy.get_incompatible_environment_reason({"pdb": object()}, {})
        == "Incompatible debugger detected: pdb"
    )
    assert (
        policy.get_incompatible_environment_reason({}, {"PYCHARM_HOSTED": "1"})
        == "Incompatible environment variable detected: PYCHARM_HOSTED"
    )
    assert (
        policy.get_incompatible_environment_reason({"coverage": object()}, {})
        == "Incompatible coverage tool detected: coverage"
    )


def test_policy_treats_alternate_implementations_as_tracing_only() -> None:
    """Non-CPython runtimes stay generally compatible but disable eval-frame explicitly."""
    policy = FrameEvalCompatibilityPolicy()

    result = policy.evaluate_environment(
        version_info=VersionInfo(3, 11, 4),
        platform_name="Linux-6.8",
        platform_system="Linux",
        architecture="64bit",
        implementation="PyPy",
        modules={},
        environ={},
    )

    assert result["compatible"] is True
    assert result["eval_frame_supported"] is False
    assert result["eval_frame_reason"] == "Eval-frame backend requires CPython (got PyPy)"
    assert result["recommended_backend"] == "tracing"
