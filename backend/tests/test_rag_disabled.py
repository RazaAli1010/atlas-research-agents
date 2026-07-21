"""With RAG_SERVICE_URL unset, rag_search self-disables and the graph still builds."""

import logging

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.graph.builder import build_graph
from app.tools import get_worker_tools


def test_rag_excluded_when_unset(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Default test env leaves RAG_SERVICE_URL unset; assert it explicitly.
    monkeypatch.setattr("app.tools.rag.settings.RAG_SERVICE_URL", None)

    with caplog.at_level(logging.WARNING, logger="app.tools.rag"):
        tools = get_worker_tools()

    names = {t.name for t in tools}
    assert "rag_search" not in names
    assert {"web_search", "calculator"} <= names
    assert any("RAG_SERVICE_URL" in rec.message for rec in caplog.records)


def test_graph_builds_without_rag() -> None:
    # build_graph must not require the RAG tool.
    assert build_graph(MemorySaver()) is not None
