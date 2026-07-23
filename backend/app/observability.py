"""LangSmith tracing enablement (§2.9 — observability from day one).

Exports the LangSmith env vars from :class:`~app.config.Settings` so LangGraph
runs are traced and shipped to the ``atlas`` project. A no-op when
``LANGSMITH_TRACING`` is off. Shared by the FastAPI server (``main.create_app``),
the CLI demo, and the eval harness so all entrypoints trace identically.
"""

from __future__ import annotations

import os

from app.config import Settings


def enable_langsmith(settings: Settings) -> None:
    """Export LangSmith env from ``settings`` so graph runs are traced."""
    if not settings.LANGSMITH_TRACING:
        return
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_PROJECT"] = settings.LANGSMITH_PROJECT
    if settings.LANGSMITH_API_KEY:
        os.environ["LANGSMITH_API_KEY"] = settings.LANGSMITH_API_KEY
