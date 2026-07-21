"""Planner node: decomposes the topic into 3-6 research sections (F2).

Uses structured output (``.with_structured_output``) — never regex/``json.loads``
on prose (SHARED CONTEXT §2.7). ``include_raw=True`` is required so the underlying
``AIMessage`` (and its token usage) is reachable for cost tracking.
"""

from typing import Any, cast

from langchain_core.messages import AIMessage
from pydantic import BaseModel

from app.graph.state import MAX_SECTIONS, ResearchState, SectionPlan
from app.llm.router import get_model, track_usage

_SYSTEM = (
    "You are the planning supervisor for an autonomous research agent. "
    "Decompose the user's research topic into 3 to 6 focused, non-overlapping "
    "sections that together fully answer it. For each section provide a short "
    "title, an objective stating exactly what the section must answer, and 2-4 "
    "concrete search queries a researcher would run. Order sections logically."
)


class PlannerOutput(BaseModel):
    """Structured-output wrapper for the planner's list of sections."""

    sections: list[SectionPlan]


def planner(state: ResearchState) -> dict:
    """Produce ``plan`` from ``topic`` and record token usage."""
    model = get_model("planner").with_structured_output(PlannerOutput, include_raw=True)
    # include_raw=True yields {"raw", "parsed", "parsing_error"}; cast the union.
    result = cast(
        dict[str, Any],
        model.invoke(
            [
                ("system", _SYSTEM),
                ("human", f"Research topic:\n{state['topic']}"),
            ]
        ),
    )

    parsed: PlannerOutput = result["parsed"]
    raw: AIMessage = result["raw"]

    # Clamp to the hard limit, then re-id sequentially so ids stay canonical.
    sections = parsed.sections[:MAX_SECTIONS]
    for i, section in enumerate(sections, start=1):
        section.id = f"s{i}"

    return {
        "plan": sections,
        "status": "awaiting_approval",
        "usage_log": [track_usage("planner", raw)],
    }
