"""Anti-fabrication grader catches a planted fake-source run (F8, AC-3).

The grader must compare cited source URLs against ``tool_calls`` — the independent
record of what tools actually returned — never against the draft sources themselves,
so a fabricated URL that never appeared in any tool result is caught.
"""

from app.graph.state import SectionDraft, Source, ToolCallRecord
from evals.graders import citation_grader
from tests.eval_helpers import make_run

_FAKE_URL = "https://totally-made-up-source.example/fabricated"


def _drafts_with_fake_source() -> list[SectionDraft]:
    return [
        SectionDraft(
            section_id="s1",
            content_md="Pinecone is cheap [1].",
            sources=[Source(url=_FAKE_URL, title="Fabricated", snippet="x", tool="web_search")],
            revision=0,
        ),
        SectionDraft(
            section_id="s2",
            content_md="Weaviate scales well [1].",
            sources=[Source(url="https://b.com", title="B", snippet="y", tool="web_search")],
            revision=0,
        ),
    ]


def test_planted_fake_source_is_caught() -> None:
    # tool_calls never returned _FAKE_URL, so citing it is fabrication.
    run = make_run(
        drafts=_drafts_with_fake_source(),
        tool_calls=[
            ToolCallRecord(section_id="s1", tool="web_search", urls=["https://a.com"]),
            ToolCallRecord(section_id="s2", tool="web_search", urls=["https://b.com"]),
        ],
    )
    result = citation_grader(run)
    assert result.passed is False
    assert "fabricated" in result.detail.lower()
    assert _FAKE_URL in result.detail


def test_control_run_with_real_sources_passes() -> None:
    # Same shape, but the tool actually returned the cited URL.
    run = make_run(
        drafts=_drafts_with_fake_source(),
        tool_calls=[
            ToolCallRecord(section_id="s1", tool="web_search", urls=[_FAKE_URL]),
            ToolCallRecord(section_id="s2", tool="web_search", urls=["https://b.com"]),
        ],
    )
    result = citation_grader(run)
    assert result.passed is True
