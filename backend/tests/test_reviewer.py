"""Reviewer grades only unreviewed latest drafts, normalizes verdict, tracks usage."""

import pytest

from app.graph.nodes import reviewer as reviewer_mod
from app.graph.nodes.reviewer import reviewer
from app.graph.state import Review, SectionDraft, SectionPlan
from tests.fakes import FakeReviewModel


def _plan(*ids: str) -> list[SectionPlan]:
    return [
        SectionPlan(id=sid, title=sid.upper(), objective="o", suggested_queries=["q"])
        for sid in ids
    ]


def _draft(sid: str, revision: int = 0) -> SectionDraft:
    return SectionDraft(section_id=sid, content_md="Body [1].", sources=[], revision=revision)


def _review(sid: str, verdict: str, score: float) -> Review:
    return Review(section_id=sid, verdict=verdict, score=score, feedback="fb")  # type: ignore[arg-type]


def test_grades_only_unreviewed_latest(monkeypatch: pytest.MonkeyPatch) -> None:
    # s1 already reviewed (1 draft, 1 review); s2 has a fresh unreviewed draft.
    fake = FakeReviewModel([_review("x", "revise", 0.4)])
    monkeypatch.setattr(reviewer_mod, "get_model", lambda _role: fake)

    state = {
        "topic": "T",
        "plan": _plan("s1", "s2"),
        "drafts": [_draft("s1"), _draft("s2")],
        "reviews": [_review("s1", "approved", 0.9)],
        "revision_counts": {},
        "usage_log": [],
    }

    out = reviewer(state)  # type: ignore[arg-type]

    assert [r.section_id for r in out["reviews"]] == ["s2"]  # only the fresh section
    assert len(out["usage_log"]) == 1  # one UsageEvent per graded section
    assert out["usage_log"][0].node == "reviewer"
    assert out["status"] == "reviewing"
    assert fake.calls == 1


def test_normalizes_verdict_and_feedback(monkeypatch: pytest.MonkeyPatch) -> None:
    # Model returns verdict="approved" but score 0.6 → server forces "revise".
    fake = FakeReviewModel(
        [Review(section_id="ignored", verdict="approved", score=0.6, feedback="  ")]
    )
    monkeypatch.setattr(reviewer_mod, "get_model", lambda _role: fake)

    out = reviewer(
        {
            "topic": "T",
            "plan": _plan("s1"),
            "drafts": [_draft("s1")],
            "reviews": [],
            "revision_counts": {},
            "usage_log": [],
        }  # type: ignore[arg-type]
    )

    review = out["reviews"][0]
    assert review.verdict == "revise"  # score < 0.7 wins over the model's verdict
    assert review.feedback.strip()  # non-empty on revise (fallback substituted)


def test_approves_above_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeReviewModel(
        [Review(section_id="ignored", verdict="revise", score=0.9, feedback="fb")]
    )
    monkeypatch.setattr(reviewer_mod, "get_model", lambda _role: fake)

    out = reviewer(
        {
            "topic": "T",
            "plan": _plan("s1"),
            "drafts": [_draft("s1")],
            "reviews": [],
            "revision_counts": {},
            "usage_log": [],
        }  # type: ignore[arg-type]
    )

    assert out["reviews"][0].verdict == "approved"


def test_revision_counts_from_drafts(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeReviewModel([_review("x", "revise", 0.4)])
    monkeypatch.setattr(reviewer_mod, "get_model", lambda _role: fake)

    out = reviewer(
        {
            "topic": "T",
            "plan": _plan("s1"),
            "drafts": [_draft("s1", 0), _draft("s1", 1)],  # two drafts → 1 revision
            "reviews": [_review("s1", "revise", 0.4)],  # rev0 already reviewed
            "revision_counts": {"s1": 0},
            "usage_log": [],
        }  # type: ignore[arg-type]
    )

    assert out["revision_counts"] == {"s1": 1}  # highest draft revision
