"""The report follows the fixed structure contract exactly (AC-3)."""

import re

import pytest

import app.graph.nodes.writer as writer_mod
from app.graph.nodes.writer import writer
from app.graph.state import SectionDraft, SectionPlan, Source
from tests.fakes import FakeModel, ai


def _headings(md: str) -> list[str]:
    """All level-1/2 ATX headings in document order."""
    return re.findall(r"^(#{1,2} .+)$", md, flags=re.MULTILINE)


def test_structure_contract_heading_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        writer_mod, "get_model", lambda _role: FakeModel([ai(content="An executive summary.")])
    )

    plan = [
        SectionPlan(id="s1", title="Pricing", objective="o", suggested_queries=["q"]),
        SectionPlan(id="s2", title="Scale", objective="o", suggested_queries=["q"]),
    ]
    drafts = [
        SectionDraft(
            section_id="s1",
            content_md="Cheap [1].",
            sources=[Source(url="https://a.com", title="A", snippet="s", tool="web_search")],
            revision=0,
        ),
        SectionDraft(
            section_id="s2",
            content_md="Scales [1].",
            sources=[Source(url="https://b.com", title="B", snippet="s", tool="web_search")],
            revision=0,
        ),
    ]

    out = writer({"topic": "Vector DBs", "plan": plan, "drafts": drafts, "reviews": []})  # type: ignore[arg-type]
    headings = _headings(out["final_report_md"])

    assert headings == [
        "# Vector DBs",
        "## Executive summary",
        "## 1. Pricing",
        "## 2. Scale",
        "## Limitations",
        "## Sources",
    ]
    # Each contract heading appears exactly once.
    for h in ("## Executive summary", "## Limitations", "## Sources"):
        assert headings.count(h) == 1
