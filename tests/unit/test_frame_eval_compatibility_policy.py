"""Unit tests for frame evaluation compatibility policy."""

from __future__ import annotations

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
