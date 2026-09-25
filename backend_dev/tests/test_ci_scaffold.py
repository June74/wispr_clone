from pathlib import Path

import pytest


PROJECT_CONFIG = Path(__file__).resolve().parents[1] / "pyproject.toml"
PIPELINE_MARKERS = (
    "unit",
    "integration",
    "conformance",
    "probe",
    "adapter",
    "windows",
    "gpu",
    "e2e",
    "manual",
    "feature",
    "invariant",
    "quarantine",
)


def test_T_CI_001_trivial_test_passes() -> None:
    assert True


def test_T_CI_002_pipeline_markers_are_registered_and_unknown_markers_fail(
    pytester: pytest.Pytester,
) -> None:
    config_args = ["-c", str(PROJECT_CONFIG)] if PROJECT_CONFIG.exists() else []

    known_test = pytester.makepyfile(
        test_known_markers="\n".join(
            ["import pytest", *(f"@pytest.mark.{marker}" for marker in PIPELINE_MARKERS)]
            + ["def test_pipeline_markers():", "    pass"]
        )
    )
    known_result = pytester.runpytest(
        *config_args, "--strict-markers", "-q", known_test.name
    )

    unknown_test = pytester.makepyfile(
        test_unknown_marker="""
        import pytest

        @pytest.mark.unregistered_ci_marker
        def test_unknown_marker():
            pass
        """
    )
    unknown_result = pytester.runpytest(
        *config_args, "-q", unknown_test.name
    )

    assert known_result.ret == pytest.ExitCode.OK, "pipeline markers must be registered"
    known_result.assert_outcomes(passed=1)
    assert unknown_result.ret == pytest.ExitCode.INTERRUPTED, (
        "unknown markers must fail collection through project pytest configuration"
    )
    unknown_result.assert_outcomes(errors=1)
