"""RunDetail.sources — the writer's global deduped source list exposed on run detail (F12).

Two levels: a pure unit test proving ``report_sources`` equals the writer's own merge
output (so ``sources[i]`` ↔ report marker ``[i+1]``), and an async API test proving the
field is wired onto ``GET /api/runs/{id}`` with structural parity to a re-derivation.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.graph.nodes.writer import _select_drafts, merge_sections, report_sources
from app.graph.state import Review, SectionDraft, SectionPlan, Source
from tests.api_helpers import build_app, client_for, patch_models, wait_for_status

_MARKER_RE = re.compile(r"\[(\d+)\]")


def test_report_sources_matches_writer_merge() -> None:
    plan = [
        SectionPlan(id="s1", title="A", objective="o", suggested_queries=[]),
        SectionPlan(id="s2", title="B", objective="o", suggested_queries=[]),
    ]
    drafts = [
        SectionDraft(
            section_id="s1",
            content_md="Alpha [1] and beta [2].",
            revision=0,
            sources=[
                Source(url="http://x", title="X", snippet="x", tool="web_search"),
                Source(url="http://y", title="Y", snippet="y", tool="rag"),
            ],
        ),
        SectionDraft(
            section_id="s2",
            content_md="Gamma reuses [1].",
            revision=0,
            # Shared URL with s1 → dedups to the same global source.
            sources=[Source(url="http://x", title="X", snippet="x", tool="web_search")],
        ),
    ]
    reviews = [
        Review(section_id="s1", verdict="approved", score=0.9, feedback=""),
        Review(section_id="s2", verdict="approved", score=0.9, feedback=""),
    ]

    chosen, _ = _select_drafts(plan, drafts, reviews)
    sections_md, expected_sources, _ = merge_sections(plan, chosen)

    sources = report_sources(plan, drafts, reviews)
    assert sources == expected_sources
    # Dedup collapsed the shared URL: x(1), y(2).
    assert [s.url for s in sources] == ["http://x", "http://y"]
    # Every remapped marker resolves within the global source range.
    markers = [int(m) for m in _MARKER_RE.findall(sections_md)]
    assert markers, "expected citation markers in the merged body"
    assert all(1 <= n <= len(sources) for n in markers)


async def test_run_detail_exposes_sources(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    patch_models(monkeypatch)
    app = build_app(tmp_path)

    async with client_for(app) as client:
        run_id = (
            await client.post("/api/runs", json={"topic": "Compare vector DBs"})
        ).json()["run_id"]
        await wait_for_status(client, run_id, "awaiting_approval")
        await client.post(f"/api/runs/{run_id}/resume", json={"action": "approve"})
        await wait_for_status(client, run_id, "done")

        detail = (await client.get(f"/api/runs/{run_id}")).json()

    assert "sources" in detail
    # Structural parity: the served list equals a re-derivation from the same state.
    plan = [SectionPlan(**p) for p in detail["plan"]]
    drafts = [SectionDraft(**d) for d in detail["drafts"]]
    reviews = [Review(**r) for r in detail["reviews"]]
    expected = [s.model_dump() for s in report_sources(plan, drafts, reviews)]
    assert detail["sources"] == expected

    # Every citation marker in the report resolves to a source (F7 guarantee, re-checked).
    markers = [int(m) for m in _MARKER_RE.findall(detail["final_report_md"])]
    assert all(1 <= n <= len(detail["sources"]) for n in markers)
