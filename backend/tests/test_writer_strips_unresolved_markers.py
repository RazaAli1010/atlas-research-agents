"""Unresolved [n] markers are stripped and reported under Limitations (AC-1)."""

import re

import pytest

import app.graph.nodes.writer as writer_mod
from app.graph.nodes.writer import writer
from app.graph.state import SectionDraft, SectionPlan, Source
from tests.fakes import FakeModel, ai


def test_unresolved_marker_stripped_and_noted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(writer_mod, "get_model", lambda _role: FakeModel([ai(content="Summary.")]))

    plan = [SectionPlan(id="s1", title="Pricing", objective="o", suggested_queries=["q"])]
    # One source, but the draft cites a bogus [5] alongside the valid [1].
    drafts = [
        SectionDraft(
            section_id="s1",
            content_md="Fact [1] and bogus [5].",
            sources=[Source(url="https://a.com", title="A", snippet="s", tool="web_search")],
            revision=0,
        )
    ]

    out = writer({"topic": "T", "plan": plan, "drafts": drafts, "reviews": []})  # type: ignore[arg-type]
    body = out["final_report_md"]

    # The bogus marker is gone; the valid one survives, cleanly (no double space).
    assert "[5]" not in body
    assert "Fact [1] and bogus." in body
    # Zero dangling markers: every [n] resolves to the single source.
    markers = [int(m) for m in re.findall(r"\[(\d+)\]", body)]
    assert markers and max(markers) <= 1
    # The removal is reported under Limitations.
    limitations = body[body.index("## Limitations") : body.index("## Sources")]
    assert "removed" in limitations
    assert "citation marker" in limitations
