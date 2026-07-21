"""Revision payload switches the prompt and increments the draft revision."""

import pytest
from langchain_core.messages import SystemMessage

from app.graph.nodes import worker as worker_mod
from app.graph.nodes.worker import worker
from app.graph.state import SectionDraft, SectionPlan
from tests.fakes import FakeModel, ai


def test_revision_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    model = FakeModel([ai(content="Improved body.")])
    monkeypatch.setattr(worker_mod, "get_worker_tools", lambda: [])
    monkeypatch.setattr(worker_mod, "get_model", lambda _role: model)

    section = SectionPlan(id="s1", title="T", objective="o", suggested_queries=["q"])
    previous = SectionDraft(section_id="s1", content_md="Old body [1].", sources=[], revision=0)

    out = worker(
        {
            "section": section,
            "topic": "T",
            "usage_log": [],
            "feedback": "Add pricing detail.",
            "previous_draft": previous,
        }
    )

    draft = out["drafts"][0]
    assert draft.revision == 1
    # The revision system prompt was used (not the first-draft prompt).
    system = next(m for m in model.last_messages if isinstance(m, SystemMessage))
    assert "revising" in system.content.lower()
