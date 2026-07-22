"""The executive summary is capped at 150 words regardless of model output."""

from app.graph.nodes.writer import _executive_summary
from tests.fakes import FakeModel, ai


def test_summary_capped_at_150_words() -> None:
    model = FakeModel([ai(content="word " * 300)])  # 300 words in

    summary, usage = _executive_summary("Topic", "## 1. Sec\nbody", model)

    assert len(summary.split()) <= 150
    # Usage is tracked so the run's cost accounting stays complete (§2.6).
    assert usage.node == "writer"


def test_short_summary_passes_through() -> None:
    model = FakeModel([ai(content="Short and sweet.")])

    summary, _usage = _executive_summary("Topic", "sections", model)

    assert summary == "Short and sweet."
