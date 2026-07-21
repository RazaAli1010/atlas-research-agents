"""Conditional-edge functions + Send fan-out (F3) + reviewer loop routing (F4).

``fan_out`` turns the approved plan into one parallel ``Send("worker", ...)`` per
section. ``route_after_review`` is the reviewer loop's conditional edge: it re-sends
only the sections that still need work and still have revision budget, else routes
to the writer.
"""

from langgraph.types import Send

from app.graph.state import (
    MAX_REVISIONS_PER_SECTION,
    ResearchState,
    Review,
    SectionDraft,
)


def fan_out(state: ResearchState) -> list[Send]:
    """One ``Send`` to the worker per planned section (parallel branches).

    Each payload carries its ``section`` and the shared ``topic``, plus a snapshot
    of the accumulated ``usage_log`` so the worker can read run cost and enforce
    the cost ceiling deterministically.
    """
    topic = state["topic"]
    base_usage = state.get("usage_log", [])
    return [
        Send("worker", {"section": section, "topic": topic, "usage_log": base_usage})
        for section in state["plan"]
    ]


def _latest_review_by_section(reviews: list[Review]) -> dict[str, Review]:
    """Most recent ``Review`` per ``section_id`` (reviews accrue in wave order)."""
    latest: dict[str, Review] = {}
    for review in reviews:
        latest[review.section_id] = review
    return latest


def _latest_draft_by_section(drafts: list[SectionDraft]) -> dict[str, SectionDraft]:
    """Highest-``revision`` draft per ``section_id``."""
    latest: dict[str, SectionDraft] = {}
    for draft in drafts:
        current = latest.get(draft.section_id)
        if current is None or draft.revision > current.revision:
            latest[draft.section_id] = draft
    return latest


def route_after_review(state: ResearchState) -> list[Send] | str:
    """Re-send failing sections with budget left; otherwise route to ``writer``.

    This is the *sole* revision-budget gate — the loop-termination guarantee.
    ``revision_counts[sid]`` is the number of revisions already produced (highest
    draft revision), maintained by the reviewer. A section is re-sent iff its latest
    verdict is ``revise`` and it has produced fewer than ``MAX_REVISIONS_PER_SECTION``
    revisions. Approved and budget-exhausted sections are left alone, so each section
    is dispatched at most ``1 + MAX_REVISIONS_PER_SECTION`` times.
    """
    topic = state["topic"]
    plan_by_id = {section.id: section for section in state["plan"]}
    latest_review = _latest_review_by_section(state.get("reviews", []))
    latest_draft = _latest_draft_by_section(state.get("drafts", []))
    counts = state.get("revision_counts", {})
    usage = state.get("usage_log", [])

    sends: list[Send] = []
    for sid, review in latest_review.items():
        if review.verdict != "revise":
            continue  # approved: never re-sent
        if counts.get(sid, 0) >= MAX_REVISIONS_PER_SECTION:
            continue  # budget exhausted: give up, keep the best draft
        sends.append(
            Send(
                "worker",
                {
                    "section": plan_by_id[sid],
                    "topic": topic,
                    "usage_log": usage,
                    "feedback": review.feedback,
                    "previous_draft": latest_draft[sid],
                },
            )
        )

    return sends if sends else "writer"
