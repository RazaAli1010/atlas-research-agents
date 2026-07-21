"""Shared test doubles (not collected by pytest — no ``test_`` prefix).

A scripted fake chat model and helpers for the worker's tool-calling loop, plus a
counting fake tool for exercising the tool-call budget.
"""

from typing import Any

from langchain_core.messages import AIMessage


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


class CountingTool:
    """A minimal fake tool that counts invocations and returns one canned source."""

    def __init__(self, name: str = "web_search") -> None:
        self.name = name
        self.count = 0

    def invoke(self, _args: dict[str, Any]) -> list[dict[str, str]]:
        self.count += 1
        return [{"url": "https://example.com/a", "title": "A", "content": "content"}]
