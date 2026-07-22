"""Global renumbering + dedup across 3 sections with overlapping source URLs."""

import re

from app.graph.nodes.writer import merge_sections
from app.graph.state import SectionDraft, SectionPlan, Source


def _src(url: str, title: str) -> Source:
    return Source(url=url, title=title, snippet="snip", tool="web_search")


def test_three_sections_dedup_and_global_remap() -> None:
    plan = [
        SectionPlan(id="s1", title="One", objective="o", suggested_queries=["q"]),
        SectionPlan(id="s2", title="Two", objective="o", suggested_queries=["q"]),
        SectionPlan(id="s3", title="Three", objective="o", suggested_queries=["q"]),
    ]
    a = _src("https://a.com", "A")  # shared across all three sections
    b = _src("https://b.com", "B")
    c = _src("https://c.com", "C")
    drafts = [
        SectionDraft(section_id="s1", content_md="alpha [1].", sources=[a], revision=0),
        # local [1]=B (new), [2]=A (shared)
        SectionDraft(
            section_id="s2", content_md="beta [1] and alpha [2].", sources=[b, a], revision=0
        ),
        # local [1]=A (shared), [2]=C (new)
        SectionDraft(
            section_id="s3", content_md="alpha [1] and gamma [2].", sources=[a, c], revision=0
        ),
    ]

    body, sources, stripped = merge_sections(plan, drafts)

    # Duplicate URLs collapse: A (first seen in s1), B (s2), C (s3) → 3 unique.
    assert [s.url for s in sources] == ["https://a.com", "https://b.com", "https://c.com"]
    assert stripped == 0
    # Each section's local markers remap to the correct global indices.
    assert "alpha [1]." in body                       # s1: A → 1
    assert "beta [2] and alpha [1]." in body          # s2: B → 2, A → 1
    assert "alpha [1] and gamma [3]." in body         # s3: A → 1, C → 3
    # Plan order preserved.
    assert body.index("## 1. One") < body.index("## 2. Two") < body.index("## 3. Three")
    # No dangling marker.
    markers = [int(m) for m in re.findall(r"\[(\d+)\]", body)]
    assert markers and max(markers) <= len(sources)
