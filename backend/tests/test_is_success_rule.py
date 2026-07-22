"""is_success implements the fixed F8 success rule and first-failing order."""

from evals.graders import GraderResult, is_success


def _results(
    structure: bool, citation: bool, coverage: float, groundedness: float
) -> list[GraderResult]:
    def r(name: str, passed: bool, score: float) -> GraderResult:
        return GraderResult(name=name, passed=passed, score=score, detail="")

    return [
        r("structure", structure, 1.0 if structure else 0.0),
        r("citation", citation, 1.0 if citation else 0.0),
        r("coverage", coverage >= 0.8, coverage),
        r("groundedness", groundedness >= 0.8, groundedness),
    ]


def test_all_pass_is_success() -> None:
    ok, first = is_success(_results(True, True, 0.9, 0.85))
    assert ok is True
    assert first is None


def test_coverage_below_threshold_fails() -> None:
    ok, first = is_success(_results(True, True, 0.79, 1.0))
    assert ok is False
    assert first == "coverage"


def test_first_failing_follows_grader_order() -> None:
    # Structure and citation both fail — structure is earlier in GRADER_ORDER.
    ok, first = is_success(_results(False, False, 1.0, 1.0))
    assert ok is False
    assert first == "structure"


def test_groundedness_threshold_is_exclusive_below() -> None:
    ok, first = is_success(_results(True, True, 1.0, 0.8))  # exactly 0.8 passes
    assert ok is True
    ok2, first2 = is_success(_results(True, True, 1.0, 0.79))
    assert (ok2, first2) == (False, "groundedness")
