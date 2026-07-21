"""RAG retriever tool — wraps the user's existing RAG app over HTTP (F3).

Self-disabling: if ``RAG_SERVICE_URL`` is unset the tool is never registered
(``rag_tool_or_none()`` returns ``None`` and logs a warning once) and the graph
runs without it. When set, ``rag_search`` POSTs the query and normalizes the
response to the same ``[{"url", "title", "content"}]`` shape as web_search.
"""

import logging
from typing import Any

import httpx
from langchain_core.tools import BaseTool, tool

from app.config import settings

logger = logging.getLogger(__name__)

_CONTENT_CHARS = 1000
_TIMEOUT_S = 10.0


@tool
def rag_search(query: str) -> list[dict[str, str]]:
    """Search the internal knowledge base for domain-specific documents.

    Use this for information likely to live in the organization's own corpus
    (internal docs, prior research, proprietary data) rather than on the public
    web. Complements ``web_search``.

    Args:
        query: The search query.

    Returns:
        A list of results, each ``{"url", "title", "content"}`` with ``content``
        truncated to 1000 characters. Empty list on error or timeout.
    """
    base_url = settings.RAG_SERVICE_URL
    if not base_url:
        # Should be unreachable — tool is only registered when the URL is set —
        # but guard so a direct call degrades instead of raising.
        return []

    try:
        resp = httpx.post(
            f"{base_url.rstrip('/')}/search",
            json={"query": query},
            timeout=_TIMEOUT_S,
        )
        resp.raise_for_status()
        payload: Any = resp.json()
    except (httpx.HTTPError, ValueError):
        logger.warning("rag_search failed for query %r; returning no results", query)
        return []

    # Accept either a bare list or {"results": [...]}.
    results = payload.get("results") if isinstance(payload, dict) else payload
    if not isinstance(results, list):
        return []

    normalized: list[dict[str, str]] = []
    for r in results:
        if not isinstance(r, dict):
            continue
        normalized.append(
            {
                "url": r.get("url", ""),
                "title": r.get("title", ""),
                "content": (r.get("content") or "")[:_CONTENT_CHARS],
            }
        )
    return normalized


def rag_tool_or_none() -> BaseTool | None:
    """Return the ``rag_search`` tool only if ``RAG_SERVICE_URL`` is configured.

    When unset, log a warning once and return ``None`` so the tool is omitted from
    the worker's toolset and the graph runs without RAG (AC-3).
    """
    if settings.RAG_SERVICE_URL:
        return rag_search
    logger.warning("RAG_SERVICE_URL is not set — rag_search tool disabled")
    return None
