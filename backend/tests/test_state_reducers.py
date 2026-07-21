"""The append reducers on ResearchState merge parallel-branch updates.

``drafts``/``reviews``/``usage_log`` use ``operator.add`` so two updates (as
produced by fan-out workers) concatenate rather than overwrite.
"""

import operator

import pytest

from app.graph.state import SectionDraft, UsageEvent


def _draft(section_id: str) -> SectionDraft:
    return SectionDraft(section_id=section_id, content_md="x", sources=[], revision=0)


def test_drafts_reducer_appends() -> None:
    branch_a = [_draft("s1")]
    branch_b = [_draft("s2")]

    merged = operator.add(branch_a, branch_b)

    assert [d.section_id for d in merged] == ["s1", "s2"]


def test_usage_log_reducer_appends() -> None:
    a = [UsageEvent(node="planner", model="m", input_tokens=1, output_tokens=1, cost_usd=0.1)]
    b = [UsageEvent(node="writer", model="m", input_tokens=2, output_tokens=2, cost_usd=0.2)]

    merged = operator.add(a, b)

    assert [e.node for e in merged] == ["planner", "writer"]
    assert sum(e.cost_usd for e in merged) == pytest.approx(0.3)
