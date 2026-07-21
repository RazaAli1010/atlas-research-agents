"""Conditional-edge functions + Send fan-out (F3).

``fan_out`` turns the approved plan into one parallel ``Send("worker", ...)`` per
section. The reviewer loop's routing (resending workers with feedback) arrives in
F4; F3 only implements the initial fan-out.
"""

from langgraph.types import Send

from app.graph.state import ResearchState


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
