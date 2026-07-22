"""render_summary produces the failure-taxonomy + per-category tables (F8, AC-2)."""

from evals.run_benchmark import RunResult, render_summary


def _result(
    topic: str, category: str, success: bool, first_failing: str | None, wall: float, cost: float
) -> RunResult:
    return RunResult(
        topic=topic,
        category=category,
        success=success,
        first_failing=first_failing,
        grader_scores={},
        grader_passed={},
        grader_details={},
        wall_time_s=wall,
        cost_usd=cost,
        revision_loops=0,
        tool_calls_per_section={},
        cost_per_node={},
    )


def _sample() -> list[RunResult]:
    return [
        _result("A", "tech_comparison", True, None, 10.0, 0.02),
        _result("B", "tech_comparison", False, "coverage", 20.0, 0.03),
        _result("C", "pricing_quant", False, "citation", 15.0, 0.01),
        _result("D", "pricing_quant", False, "coverage", 30.0, 0.05),
    ]


def test_summary_contains_taxonomy_and_category_tables() -> None:
    md = render_summary(_sample(), timestamp="20260722-120000", seed=42)

    # Failure-taxonomy table grouped by first-failing grader.
    assert "Failure taxonomy" in md
    assert "| coverage | 2 |" in md  # two runs first-failed on coverage
    assert "| citation | 1 |" in md

    # Per-category breakdown with a row per present category.
    assert "Per-category success" in md
    assert "| tech_comparison | 2 | 50.0% |" in md
    assert "| pricing_quant | 2 | 0.0% |" in md

    # Aggregate fields filled.
    assert "Success rate:** 25.0%" in md
    assert "Seed:** 42" in md


def test_summary_handles_all_success() -> None:
    results = [_result("A", "tech_comparison", True, None, 5.0, 0.01)]
    md = render_summary(results, timestamp="t", seed=1)
    assert "_No failures._" in md
    assert "100.0%" in md
