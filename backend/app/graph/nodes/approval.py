"""Approval gate node: ``interrupt()`` for human plan review — F5.

The graph pauses here after planning so the human can review or edit the plan
before any expensive research runs. The node is *trivially idempotent* (§2.3): the
single ``interrupt()`` is the first statement and the only work before the branch is
serialising ``state["plan"]``, which has no side effects — so LangGraph re-executing
the node from the top on resume is safe.

Resume payload (delivered via ``Command(resume=...)`` from the caller):

* ``{"action": "approve"}`` — keep the plan as-is.
* ``{"action": "edit", "plan": [ {id, title, objective, suggested_queries}, ... ]}``
  — replace the plan; the edited list is clamped to ``MAX_SECTIONS``.

Either way the node marks the plan approved and advances ``status`` to
``"researching"`` so the fan-out (``routing.fan_out``, wired onto this node in the
builder) dispatches one worker per section.
"""

from langgraph.types import interrupt

from app.graph.state import MAX_SECTIONS, ResearchState, SectionPlan


def approval_gate(state: ResearchState) -> dict:
    """Pause for human approval; resume with the approve/edit decision.

    No LLM call is made, so nothing is written to ``usage_log`` (§2.6).
    """
    decision = interrupt({"plan": [s.model_dump() for s in state["plan"]]})
    if decision["action"] == "edit":
        plan = [SectionPlan(**s) for s in decision["plan"]][:MAX_SECTIONS]
        return {"plan": plan, "plan_approved": True, "status": "researching"}
    return {"plan_approved": True, "status": "researching"}
