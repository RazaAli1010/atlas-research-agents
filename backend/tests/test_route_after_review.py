"""route_after_review re-sends only failing sections with budget left, else writer."""

from app.graph.routing import route_after_review
from app.graph.state import MAX_REVISIONS_PER_SECTION, Review, SectionDraft, SectionPlan


def _plan(*ids: str) -> list[SectionPlan]:
    return [
        SectionPlan(id=sid, title=sid.upper(), objective="o", suggested_queries=["q"])
        for sid in ids
    ]


def _draft(sid: str, revision: int = 0) -> SectionDraft:
    return SectionDraft(section_id=sid, content_md="Body.", sources=[], revision=revision)


def _review(sid: str, verdict: str, score: float = 0.5) -> Review:
    return Review(section_id=sid, verdict=verdict, score=score, feedback="fix pricing")  # type: ignore[arg-type]


def test_revise_within_budget_sends_worker() -> None:
    state = {
        "topic": "Vector DB pricing",
        "plan": _plan("s1"),
        "drafts": [_draft("s1", 0)],
        "reviews": [_review("s1", "revise")],
        "revision_counts": {"s1": 0},
        "usage_log": [],
    }

    result = route_after_review(state)  # type: ignore[arg-type]

    assert isinstance(result, list) and len(result) == 1
    send = result[0]
    assert send.node == "worker"
    assert send.arg["section"].id == "s1"
    assert send.arg["topic"] == "Vector DB pricing"
    assert send.arg["feedback"] == "fix pricing"
    assert send.arg["previous_draft"].section_id == "s1"
    assert "usage_log" in send.arg


def test_only_failing_sections_resent() -> None:
    state = {
        "topic": "T",
        "plan": _plan("s1", "s2"),
        "drafts": [_draft("s1"), _draft("s2")],
        "reviews": [_review("s1", "approved", 0.9), _review("s2", "revise")],
        "revision_counts": {"s1": 0, "s2": 0},
        "usage_log": [],
    }

    result = route_after_review(state)  # type: ignore[arg-type]

    assert isinstance(result, list)
    assert [s.arg["section"].id for s in result] == ["s2"]  # approved s1 not re-sent


def test_budget_exhausted_goes_to_writer() -> None:
    state = {
        "topic": "T",
        "plan": _plan("s1"),
        "drafts": [_draft("s1", MAX_REVISIONS_PER_SECTION)],
        "reviews": [_review("s1", "revise")],
        "revision_counts": {"s1": MAX_REVISIONS_PER_SECTION},
        "usage_log": [],
    }

    assert route_after_review(state) == "writer"  # type: ignore[arg-type]


def test_all_approved_goes_to_writer() -> None:
    state = {
        "topic": "T",
        "plan": _plan("s1"),
        "drafts": [_draft("s1")],
        "reviews": [_review("s1", "approved", 0.9)],
        "revision_counts": {"s1": 0},
        "usage_log": [],
    }

    assert route_after_review(state) == "writer"  # type: ignore[arg-type]


def test_uses_highest_revision_previous_draft() -> None:
    state = {
        "topic": "T",
        "plan": _plan("s1"),
        "drafts": [_draft("s1", 0), _draft("s1", 1)],
        "reviews": [_review("s1", "revise"), _review("s1", "revise")],
        "revision_counts": {"s1": 1},
        "usage_log": [],
    }

    result = route_after_review(state)  # type: ignore[arg-type]

    assert isinstance(result, list)
    assert result[0].arg["previous_draft"].revision == 1  # latest draft carried back
