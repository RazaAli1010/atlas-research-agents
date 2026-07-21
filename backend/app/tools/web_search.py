"""Web search tool (Tavily) — F3.

Wraps ``langchain_tavily.TavilySearch`` in our own ``@tool`` so the worker always
receives a normalized ``[{"url", "title", "content"}]`` shape with bounded content.
On zero results or any client/network error it returns ``[]`` — the worker notes
the gap rather than crashing (graceful degradation, AC-3).
"""

import logging
import os
from typing import Any

from langchain_core.tools import tool
from langchain_tavily import TavilySearch

from app.config import settings

logger = logging.getLogger(__name__)

# TavilySearch reads TAVILY_API_KEY from the environment; pydantic-settings loads
# it into ``settings`` but does not export it to os.environ, so bridge it here
# (mirrors the OpenAI-key handling in app.llm.router). setdefault so a real env
# var or CI job env still wins.
os.environ.setdefault("TAVILY_API_KEY", settings.TAVILY_API_KEY)

_MAX_RESULTS = 5
_CONTENT_CHARS = 1000

# Module-singleton client (read-only, safe to share across parallel workers).
_client = TavilySearch(max_results=_MAX_RESULTS)


@tool
def web_search(query: str) -> list[dict[str, str]]:
    """Search the public web for up-to-date information and return top results.

    Use this to find current facts, pricing, documentation, comparisons, and news
    that you do not already know. Prefer specific queries over broad ones.

    Args:
        query: The search query, e.g. "Pinecone serverless pricing 2026".

    Returns:
        A list of up to 5 results, each ``{"url", "title", "content"}`` where
        ``content`` is a snippet truncated to 1000 characters. Empty list if
        nothing is found or the search backend is unavailable.
    """
    try:
        raw: dict[str, Any] = _client.invoke({"query": query})
    except Exception:  # noqa: BLE001 — degrade gracefully on any client/network error
        logger.warning("web_search failed for query %r; returning no results", query)
        return []

    results = raw.get("results") or []
    normalized: list[dict[str, str]] = []
    for r in results:
        normalized.append(
            {
                "url": r.get("url", ""),
                "title": r.get("title", ""),
                "content": (r.get("content") or "")[:_CONTENT_CHARS],
            }
        )
    return normalized
