"""citation_grader flags dangling markers and passes clean reports (F8)."""

from evals.graders import citation_grader
from tests.eval_helpers import VALID_REPORT, make_run


def test_clean_report_passes() -> None:
    result = citation_grader(make_run())
    assert result.passed is True
    assert result.score == 1.0


def test_dangling_marker_fails() -> None:
    # Add a [3] marker though only 2 sources are listed.
    broken = VALID_REPORT.replace("Weaviate scales well [2].", "Weaviate scales well [2][3].")
    result = citation_grader(make_run(report_md=broken))
    assert result.passed is False
    assert "dangling" in result.detail
    assert "3" in result.detail


def test_section_without_citation_fails() -> None:
    broken = VALID_REPORT.replace("Weaviate scales well [2].", "Weaviate scales well.")
    result = citation_grader(make_run(report_md=broken))
    assert result.passed is False
    assert "no citation" in result.detail


def test_bracketed_year_in_source_title_is_not_dangling() -> None:
    # A source title containing a bracketed number ([2026]) lives in the Sources list,
    # which uses [text](url) link syntax — it must not be read as a citation marker.
    report = VALID_REPORT.replace(
        "2. [B](https://b.com)", "2. [Weaviate Review [2026]](https://b.com)"
    )
    result = citation_grader(make_run(report_md=report))
    assert result.passed is True  # [2026] in the Sources list is not a dangling marker
    assert "dangling" not in result.detail
