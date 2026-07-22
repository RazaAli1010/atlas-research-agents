"""coverage_grader scores the fraction of must_cover points addressed (F8)."""

from evals.graders import CoverageVerdict, coverage_grader
from tests.eval_helpers import make_run
from tests.fakes import FakeJudge


def test_partial_coverage_below_threshold_fails() -> None:
    run = make_run(must_cover=["a", "b", "c", "d", "e"])
    judge = FakeJudge([CoverageVerdict(covered=[True, True, True, False, False], notes="n")])
    result = coverage_grader(run, judge=judge)
    assert result.score == 0.6
    assert result.passed is False


def test_full_coverage_passes() -> None:
    run = make_run(must_cover=["a", "b", "c"])
    judge = FakeJudge([CoverageVerdict(covered=[True, True, True], notes="n")])
    result = coverage_grader(run, judge=judge)
    assert result.score == 1.0
    assert result.passed is True


def test_judge_list_length_mismatch_is_aligned() -> None:
    # Judge returns too few flags — grader pads defensively to the point count.
    run = make_run(must_cover=["a", "b", "c", "d"])
    judge = FakeJudge([CoverageVerdict(covered=[True, True], notes="n")])
    result = coverage_grader(run, judge=judge)
    assert result.score == 0.5  # 2 covered / 4 points
