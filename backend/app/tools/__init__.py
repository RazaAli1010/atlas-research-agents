"""Research tools (web search, RAG retriever, calculator).

``get_worker_tools()`` is the single source the worker binds. It always includes
web search and the calculator; RAG is appended only when configured (see
``rag.rag_tool_or_none``). ``TOOL_NAME_TO_SOURCE_TOOL`` maps each tool's ``.name``
to the ``Source.tool`` literal so the worker can tag collected sources.
"""

from langchain_core.tools import BaseTool

from app.tools.calculator import calculator
from app.tools.rag import rag_search, rag_tool_or_none
from app.tools.web_search import web_search

# Tool .name → Source.tool literal (SHARED CONTEXT §5).
TOOL_NAME_TO_SOURCE_TOOL: dict[str, str] = {
    web_search.name: "web_search",
    rag_search.name: "rag",
    calculator.name: "calculator",
}


def get_worker_tools() -> list[BaseTool]:
    """Assemble the enabled toolset for the worker.

    web_search + calculator are always present; rag_search is included only when
    ``RAG_SERVICE_URL`` is set (else the graph runs without it).
    """
    tools: list[BaseTool] = [web_search, calculator]
    rag = rag_tool_or_none()
    if rag is not None:
        tools.append(rag)
    return tools


__all__ = [
    "TOOL_NAME_TO_SOURCE_TOOL",
    "calculator",
    "get_worker_tools",
    "rag_search",
    "web_search",
]
