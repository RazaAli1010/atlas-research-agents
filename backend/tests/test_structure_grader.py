"""structure_grader enforces the F7 report structure contract (F8)."""

from evals.graders import structure_grader
from tests.eval_helpers import VALID_REPORT, make_run


def test_valid_report_passes() -> None:
    result = structure_grader(make_run())
    assert result.passed is True
    assert result.score == 1.0


def test_missing_sources_heading_fails() -> None:
    broken = VALID_REPORT.replace("## Sources", "## References")
    result = structure_grader(make_run(report_md=broken))
    assert result.passed is False
    assert "Sources" in result.detail


def test_headings_out_of_order_fails() -> None:
    # Swap Limitations and Sources so Sources is no longer last.
    broken = (
        "# Vector DBs\n\n## Executive summary\n\ns\n\n## 1. Pricing\n\nx [1].\n\n"
        "## Sources\n\n1. [A](https://a.com)\n\n## Limitations\n\nNone.\n"
    )
    result = structure_grader(make_run(report_md=broken))
    assert result.passed is False
