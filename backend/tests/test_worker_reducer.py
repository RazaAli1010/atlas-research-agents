"""Parallel worker drafts accumulate in `drafts` via the operator.add reducer."""

import operator

import pytest

from app.graph.nodes import worker as worker_mod
from app.graph.nodes.worker import worker
from app.graph.state import SectionDraft, SectionPlan
from tests.fakes import FakeModel, ai


def _plan(n: int) -> list[SectionPlan]:
    return [
        SectionPlan(id=f"s{i}", title=f"Title {i}", objective="obj", suggested_queries=["q"])
        for i in range(1, n + 1)
    ]


def test_parallel_drafts_accumulate(monkeypatch: pytest.MonkeyPatch) -> None:
    # Fake model answers immediately with no tool calls.
    monkeypatch.setattr(
        worker_mod, "get_model", lambda _role: FakeModel([ai(content="Section body.")])
    )

    updates = [worker({"section": s, "topic": "T", "usage_log": []}) for s in _plan(3)]

    merged: list[SectionDraft] = []
    for update in updates:
        merged = operator.add(merged, update["drafts"])

    assert [d.section_id for d in merged] == ["s1", "s2", "s3"]
    assert all(d.revision == 0 for d in merged)
