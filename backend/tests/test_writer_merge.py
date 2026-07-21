"""merge_drafts dedupes sources globally and remaps [n] markers to global indices."""

from app.graph.nodes.writer import merge_drafts, writer
from app.graph.state import MAX_REVISIONS_PER_SECTION, Review, SectionDraft, SectionPlan, Source


def _src(url: str, title: str) -> Source:
    return Source(url=url, title=title, snippet="snip", tool="web_search")


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

    body, sources = merge_drafts(plan, drafts)

    # Global dedup: shared.com counted once → 2 unique sources.
    assert [s.url for s in sources] == ["https://shared.com", "https://other.com"]
    # s1 marker stays [1]; s2's local [1] (shared) remaps to global [1], [2] -> [2].
    assert "Costs are low [1]." in body
    assert "Scales well [1] and further [2]." in body
    # Plan order preserved and a single Sources list.
    assert body.index("## 1. Pricing") < body.index("## 2. Scale") < body.index("## Sources")
    assert body.count("## Sources") == 1
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

    body, _ = merge_drafts(plan, drafts)

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


def test_writer_prefers_approved_over_higher_revision() -> None:
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
    assert "**Limitations:**" not in body  # section did reach the bar


def test_writer_adds_limitations_note() -> None:
    plan = [SectionPlan(id="s1", title="Pricing", objective="o", suggested_queries=["q"])]
    drafts = [
        SectionDraft(section_id="s1", content_md=f"rev{r} body", sources=[], revision=r)
        for r in range(MAX_REVISIONS_PER_SECTION + 1)
    ]
    reviews = [_review("s1", "revise", 0.4) for _ in drafts]

    out = writer(_state(plan, drafts, reviews, {"s1": MAX_REVISIONS_PER_SECTION}))  # type: ignore[arg-type]

    body = out["final_report_md"]
    assert "**Limitations:**" in body
    assert "Pricing" in body
    # Note sits between the title and the first section heading.
    assert body.index("# Topic") < body.index("**Limitations:**") < body.index("## 1.")
