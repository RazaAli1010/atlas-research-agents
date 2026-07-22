"""groundedness_grader samples cited claims and checks support (F8, AC-1 sampling)."""

from app.graph.state import SectionDraft, Source
from evals.graders import ClaimGrounded, groundedness_grader
from tests.eval_helpers import make_run
from tests.fakes import FakeJudge


def _draft_with_n_claims(n: int) -> SectionDraft:
    body = " ".join(f"Fact number {k} holds [1]." for k in range(n))
    src = Source(url="https://a.com", title="A", snippet="Supporting evidence.", tool="web_search")
    return SectionDraft(section_id="s1", content_md=body, sources=[src], revision=0)


def test_score_is_fraction_supported() -> None:
    run = make_run(drafts=[_draft_with_n_claims(5)])
    supported = ClaimGrounded(supported=True, reason="r")
    unsupported = ClaimGrounded(supported=False, reason="r")
    judge = FakeJudge([supported] * 4 + [unsupported])
    result = groundedness_grader(run, judge=judge)
    assert result.score == 0.8  # 4/5
    assert result.passed is True


def test_no_citable_claims_fails() -> None:
    plain = SectionDraft(section_id="s1", content_md="No citations here.", sources=[], revision=0)
    result = groundedness_grader(make_run(drafts=[plain]), judge=FakeJudge([]))
    assert result.score == 0.0
    assert result.passed is False
    assert "no citable claims" in result.detail


def test_seeded_sampling_is_reproducible() -> None:
    # 8 claims but only 5 sampled — the selection must be identical for the same seed.
    run = make_run(drafts=[_draft_with_n_claims(8)], seed=42)
    always_true = [ClaimGrounded(supported=True, reason="r")] * 8

    j1 = FakeJudge(list(always_true))
    j2 = FakeJudge(list(always_true))
    groundedness_grader(run, judge=j1)
    groundedness_grader(run, judge=j2)

    assert j1.seen == j2.seen  # same claims, same order
    assert len(j1.seen) == 5
