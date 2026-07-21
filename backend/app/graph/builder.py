"""build_graph() -> compiled LangGraph graph.

Topology (§6): ``START -> planner -> approval_gate(interrupt) -> [fan_out] worker×N
-> reviewer -> {revise loop | writer} -> END``. The parallel workers fan back in at
``reviewer`` via the ``drafts``/``usage_log`` append reducers. The approval gate
(F5) pauses the run for human plan review before any worker runs. Uses LangGraph 1.x
APIs only — no imports from ``langgraph.prebuilt`` (§2.1).
"""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.nodes.approval import approval_gate
from app.graph.nodes.planner import planner
from app.graph.nodes.reviewer import reviewer
from app.graph.nodes.worker import worker
from app.graph.nodes.writer import writer
from app.graph.routing import fan_out, route_after_review
from app.graph.state import ResearchState


def build_graph(checkpointer: BaseCheckpointSaver | None = None) -> CompiledStateGraph:
    """Compile the planner -> worker×N -> writer graph.

    A checkpointer is mandatory in real runs (interrupt/resume needs one), but is
    optional here so callers can pass ``MemorySaver`` in tests or the
    config-selected saver in the demo.
    """
    graph = StateGraph(ResearchState)
    graph.add_node("planner", planner)
    graph.add_node("approval_gate", approval_gate)
    # worker's input is a Send payload (section/topic/…), not the full state
    # schema, so its signature intentionally diverges from the node type.
    graph.add_node("worker", worker)  # type: ignore[arg-type]
    graph.add_node("reviewer", reviewer)
    graph.add_node("writer", writer)

    graph.add_edge(START, "planner")
    # planner -> approval_gate: the run pauses at the interrupt for human review.
    graph.add_edge("planner", "approval_gate")
    # After approval, fan_out returns one Send("worker", ...) per section (parallel).
    graph.add_conditional_edges("approval_gate", fan_out, ["worker"])
    graph.add_edge("worker", "reviewer")  # all workers of a wave fan in here
    # route_after_review re-sends failing sections (revise cycle, ≤ budget) or
    # advances to the writer once every section is settled.
    graph.add_conditional_edges("reviewer", route_after_review, ["worker", "writer"])
    graph.add_edge("writer", END)

    return graph.compile(checkpointer=checkpointer)
