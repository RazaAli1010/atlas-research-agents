"""web_search normalizes Tavily results and truncates content; empty -> []."""

import importlib
from typing import Any

import pytest

from app.tools.web_search import web_search

# The package exposes a `web_search` tool that shadows the submodule name, so import
# the module explicitly to reach its private `_client`.
ws_mod = importlib.import_module("app.tools.web_search")


class _FakeClient:
    """Stand-in for TavilySearch (a pydantic model that rejects attr assignment)."""

    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error

    def invoke(self, _query: dict[str, str]) -> Any:
        if self._error is not None:
            raise self._error
        return self._result


def test_normalizes_and_truncates(monkeypatch: pytest.MonkeyPatch) -> None:
    long_content = "x" * 5000
    canned = {
        "results": [
            {"url": "https://a.com", "title": "A", "content": long_content, "score": 0.9},
            {"url": "https://b.com", "title": "B", "content": "short"},
        ]
    }
    monkeypatch.setattr(ws_mod, "_client", _FakeClient(result=canned))

    out = web_search.invoke({"query": "anything"})

    assert [r["url"] for r in out] == ["https://a.com", "https://b.com"]
    assert set(out[0].keys()) == {"url", "title", "content"}
    assert len(out[0]["content"]) == 1000  # truncated


def test_empty_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ws_mod, "_client", _FakeClient(result={"results": []}))
    assert web_search.invoke({"query": "anything"}) == []


def test_client_error_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ws_mod, "_client", _FakeClient(error=RuntimeError("network down")))
    assert web_search.invoke({"query": "anything"}) == []
