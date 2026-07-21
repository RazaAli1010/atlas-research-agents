"""build_graph() -> compiled LangGraph graph (F2 walking skeleton).

Topology: ``START -> planner -> writer -> END``. Later features extend this with
the approval interrupt, worker fan-out, and reviewer loop (§6). Uses LangGraph 1.x
APIs only — no imports from ``langgraph.prebuilt`` (§2.1).
"""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.nodes.planner import planner
from app.graph.nodes.writer import writer
from app.graph.state import ResearchState


def build_graph(checkpointer: BaseCheckpointSaver | None = None) -> CompiledStateGraph:
    """Compile the planner -> writer skeleton graph.

    A checkpointer is mandatory in real runs (interrupt/resume needs one), but is
    optional here so callers can pass ``MemorySaver`` in tests or the
    config-selected saver in the demo.
    """
    graph = StateGraph(ResearchState)
    graph.add_node("planner", planner)
    graph.add_node("writer", writer)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "writer")
    graph.add_edge("writer", END)

    return graph.compile(checkpointer=checkpointer)
