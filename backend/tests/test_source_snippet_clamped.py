"""Source.snippet is structurally clamped to ≤300 chars on every construction."""

from app.graph.state import MAX_SNIPPET_CHARS, Source


def test_snippet_truncated_to_limit() -> None:
    src = Source(url="https://u.com", title="t", snippet="x" * 500, tool="web_search")
    assert len(src.snippet) == MAX_SNIPPET_CHARS == 300


def test_short_snippet_unchanged() -> None:
    src = Source(url="https://u.com", title="t", snippet="brief", tool="web_search")
    assert src.snippet == "brief"
