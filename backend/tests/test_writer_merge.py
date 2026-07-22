"""merge_sections dedupes sources globally and remaps [n] markers; writer assembles
the fixed report structure (executive summary + Limitations section)."""

import pytest

import app.graph.nodes.writer as writer_mod
from app.graph.nodes.writer import merge_sections, writer
from app.graph.state import MAX_REVISIONS_PER_SECTION, Review, SectionDraft, SectionPlan, Source
from tests.fakes import FakeModel, ai


def _src(url: str, title: str) -> Source:
    return Source(url=url, title=title, snippet="snip", tool="web_search")


def _patch_writer_model(monkeypatch: pytest.MonkeyPatch, summary: str = "Summary.") -> None:
    """Writer now calls an LLM for the executive summary — feed it a scripted reply."""
    monkeypatch.setattr(writer_mod, "get_model", lambda _role: FakeModel([ai(content=summary)]))


def test_merge_dedupes_and_remaps() -> None:
    plan = [
        SectionPlan(id="s1", title="Pricing", objective="o", suggested_queries=["q"]),
        SectionPlan(id="s2", title="Scale", objective="o", suggested_queries=["q"]),
    ]
    # s1 cites its own [1]; s2 cites [1] (shared URL) and [2] (new URL).
    drafts = [
        SectionDraft(
            section_id="s1",
            content_md="Costs are low [1].",
            sources=[_src("https://shared.com", "Shared")],
            revision=0,
        ),
        SectionDraft(
            section_id="s2",
            content_md="Scales well [1] and further [2].",
            sources=[_src("https://shared.com", "Shared"), _src("https://other.com", "Other")],
            revision=0,
        ),
    ]

    body, sources, stripped = merge_sections(plan, drafts)

    # Global dedup: shared.com counted once → 2 unique sources.
    assert [s.url for s in sources] == ["https://shared.com", "https://other.com"]
    assert stripped == 0
    # s1 marker stays [1]; s2's local [1] (shared) remaps to global [1], [2] -> [2].
    assert "Costs are low [1]." in body
    assert "Scales well [1] and further [2]." in body
    # Plan order preserved; merge_sections emits section bodies only (no ## Sources).
    assert body.index("## 1. Pricing") < body.index("## 2. Scale")
    assert "## Sources" not in body
    # No dangling citation index (max marker <= number of sources).
    import re

    markers = [int(m) for m in re.findall(r"\[(\d+)\]", body)]
    assert markers and max(markers) <= len(sources)


def test_highest_revision_wins() -> None:
    plan = [SectionPlan(id="s1", title="T", objective="o", suggested_queries=["q"])]
    drafts = [
        SectionDraft(section_id="s1", content_md="old", sources=[], revision=0),
        SectionDraft(section_id="s1", content_md="new", sources=[], revision=1),
    ]

    body, _sources, _stripped = merge_sections(plan, drafts)

    assert "new" in body
    assert "old" not in body


def _review(sid: str, verdict: str, score: float) -> Review:
    return Review(section_id=sid, verdict=verdict, score=score, feedback="fb")  # type: ignore[arg-type]


def _state(
    plan: list[SectionPlan],
    drafts: list[SectionDraft],
    reviews: list[Review],
    counts: dict,
) -> dict:
    return {
        "topic": "Topic",
        "plan": plan,
        "drafts": drafts,
        "reviews": reviews,
        "revision_counts": counts,
    }


def test_writer_prefers_approved_over_higher_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_writer_model(monkeypatch)
    plan = [SectionPlan(id="s1", title="T", objective="o", suggested_queries=["q"])]
    drafts = [
        SectionDraft(section_id="s1", content_md="rev0 body", sources=[], revision=0),
        SectionDraft(section_id="s1", content_md="APPROVED body", sources=[], revision=1),
        SectionDraft(section_id="s1", content_md="rev2 body", sources=[], revision=2),
    ]
    reviews = [
        _review("s1", "revise", 0.4),
        _review("s1", "approved", 0.9),
        _review("s1", "revise", 0.5),
    ]

    out = writer(_state(plan, drafts, reviews, {"s1": 2}))  # type: ignore[arg-type]

    body = out["final_report_md"]
    assert "APPROVED body" in body  # highest-revision approved, not the later rev2
    assert "rev2 body" not in body
    # Section reached the bar and nothing was stripped → empty Limitations.
    assert "## Limitations\n\nNone." in body


def test_writer_adds_limitations_note(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_writer_model(monkeypatch)
    plan = [SectionPlan(id="s1", title="Pricing", objective="o", suggested_queries=["q"])]
    drafts = [
        SectionDraft(section_id="s1", content_md=f"rev{r} body", sources=[], revision=r)
        for r in range(MAX_REVISIONS_PER_SECTION + 1)
    ]
    reviews = [_review("s1", "revise", 0.4) for _ in drafts]

    out = writer(_state(plan, drafts, reviews, {"s1": MAX_REVISIONS_PER_SECTION}))  # type: ignore[arg-type]

    body = out["final_report_md"]
    # Limitations is now a dedicated section (before Sources), naming the section.
    assert "## Limitations" in body
    assert "quality bar" in body
    assert "Pricing" in body
    assert (
        body.index("## Executive summary")
        < body.index("## Limitations")
        < body.index("## Sources")
    )
