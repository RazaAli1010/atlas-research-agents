"""Tiny CLI to exercise the F2 walking skeleton end-to-end.

Usage:
    uv run python -m app.graph.demo "Compare vector database pricing for a startup"

Builds the planner -> writer graph with the config-selected checkpointer, invokes
it, and prints the plan outline plus total cost. When ``LANGSMITH_TRACING`` is on,
the run is traceable in the LangSmith ``atlas`` project with named nodes.
"""

import os
import sys
from typing import cast
from uuid import uuid4

from app.config import settings
from app.graph.builder import build_graph
from app.graph.state import ResearchState
from app.persistence.checkpointer import checkpointer_cx


def _enable_langsmith() -> None:
    """Export LangSmith env from settings so runs are traced (§2.9)."""
    if not settings.LANGSMITH_TRACING:
        return
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_PROJECT"] = settings.LANGSMITH_PROJECT
    if settings.LANGSMITH_API_KEY:
        os.environ["LANGSMITH_API_KEY"] = settings.LANGSMITH_API_KEY


def _seed_state(topic: str) -> ResearchState:
    return {
        "topic": topic,
        "plan": [],
        "plan_approved": False,
        "drafts": [],
        "reviews": [],
        "revision_counts": {},
        "final_report_md": "",
        "usage_log": [],
        "status": "planning",
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2 or not argv[1].strip():
        print('usage: python -m app.graph.demo "<research topic>"', file=sys.stderr)
        return 2

    topic = argv[1]
    _enable_langsmith()

    with checkpointer_cx() as cp:
        graph = build_graph(checkpointer=cp)
        final = cast(
            ResearchState,
            graph.invoke(
                _seed_state(topic),
                config={"configurable": {"thread_id": str(uuid4())}},
            ),
        )

    print(f"\nTopic: {topic}\n")
    print("Plan outline:")
    for i, section in enumerate(final["plan"], start=1):
        print(f"  {i}. {section.title}")

    total_cost = sum(e.cost_usd for e in final["usage_log"])
    print(f"\ntotal_cost_usd: {total_cost:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
