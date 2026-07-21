"""Shared test doubles (not collected by pytest — no ``test_`` prefix).

A scripted fake chat model and helpers for the worker's tool-calling loop, plus a
counting fake tool for exercising the tool-call budget.
"""

from typing import Any

from langchain_core.messages import AIMessage

from app.graph.state import Review


def ai(content: str = "", tool_calls: list[dict[str, Any]] | None = None) -> AIMessage:
    """Build an AIMessage with usage metadata track_usage can read."""
    return AIMessage(
        content=content,
        tool_calls=tool_calls or [],
        usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        response_metadata={"model_name": "gpt-4o-mini"},
    )


def tool_call(name: str, args: dict[str, Any], call_id: str = "c1") -> dict[str, Any]:
    """A LangChain tool-call dict for an AIMessage."""
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


class FakeModel:
    """Returns scripted AIMessages in order; the last response repeats forever."""

    def __init__(self, responses: list[AIMessage]) -> None:
        self._responses = list(responses)
        self._i = 0
        self.last_messages: list[Any] = []

    def bind_tools(self, _tools: Any) -> "FakeModel":
        return self

    def invoke(self, messages: Any) -> AIMessage:
        self.last_messages = list(messages)
        response = self._responses[min(self._i, len(self._responses) - 1)]
        self._i += 1
        return response


class FakeReviewModel:
    """Structured-output fake for the reviewer node.

    Returns scripted ``Review``s in order (the last repeats forever, like
    ``FakeModel``). ``get_model("reviewer")`` returns this; ``reviewer`` then calls
    ``.with_structured_output(Review, include_raw=True).invoke(...)`` and expects the
    planner-style ``{"parsed", "raw"}`` dict. ``calls`` counts model invocations —
    with a single-section plan this equals the number of reviewer passes.
    """

    def __init__(self, reviews: list[Review]) -> None:
        self._reviews = list(reviews)
        self._i = 0
        self.calls = 0

    def with_structured_output(self, _schema: Any, include_raw: bool = False) -> "FakeReviewModel":
        assert include_raw is True  # required so usage_metadata is reachable
        return self

    def invoke(self, _messages: Any) -> dict[str, Any]:
        review = self._reviews[min(self._i, len(self._reviews) - 1)]
        self._i += 1
        self.calls += 1
        return {"parsed": review, "raw": ai("")}


class CountingTool:
    """A minimal fake tool that counts invocations and returns one canned source."""

    def __init__(self, name: str = "web_search") -> None:
        self.name = name
        self.count = 0

    def invoke(self, _args: dict[str, Any]) -> list[dict[str, str]]:
        self.count += 1
        return [{"url": "https://example.com/a", "title": "A", "content": "content"}]
