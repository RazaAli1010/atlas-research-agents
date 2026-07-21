"""build_graph() -> compiled LangGraph graph.

Topology (F3): ``START -> planner -> [fan_out] worker×N -> writer -> END``. The
parallel workers fan back in at ``writer`` via the ``drafts``/``usage_log`` append
reducers. Later features insert the approval interrupt (planner -> approval ->
fan_out) and the reviewer loop (§6). Uses LangGraph 1.x APIs only — no imports from
``langgraph.prebuilt`` (§2.1).
"""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.nodes.planner import planner
from app.graph.nodes.worker import worker
from app.graph.nodes.writer import writer
from app.graph.routing import fan_out
from app.graph.state import ResearchState


def build_graph(checkpointer: BaseCheckpointSaver | None = None) -> CompiledStateGraph:
    """Compile the planner -> worker×N -> writer graph.

    A checkpointer is mandatory in real runs (interrupt/resume needs one), but is
    optional here so callers can pass ``MemorySaver`` in tests or the
    config-selected saver in the demo.
    """
    graph = StateGraph(ResearchState)
    graph.add_node("planner", planner)
    # worker's input is a Send payload (section/topic/…), not the full state
    # schema, so its signature intentionally diverges from the node type.
    graph.add_node("worker", worker)  # type: ignore[arg-type]
    graph.add_node("writer", writer)

    graph.add_edge(START, "planner")
    # fan_out returns one Send("worker", ...) per section (parallel branches).
    graph.add_conditional_edges("planner", fan_out, ["worker"])
    graph.add_edge("worker", "writer")  # fan-in via append reducers
    graph.add_edge("writer", END)

    return graph.compile(checkpointer=checkpointer)
