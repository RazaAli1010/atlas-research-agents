"""Role->model routing + usage tracking. Stubbed in F2, fully built in F9.

Every LLM call must go through this router; nodes never instantiate model clients
directly (SHARED CONTEXT §2.5).

F2 stub behaviour:
- ``get_model`` returns one configured chat model for every role (the model named
  by ``settings.DEFAULT_MODEL``).
- ``track_usage`` reads token usage off a LangChain ``AIMessage`` and prices it
  from ``MODEL_PRICES``.

The public signatures here are final — F9 replaces only the internals (real
role->model routing, richer pricing / rate-limit handling).
"""

from typing import Literal

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage

from app.config import settings
from app.graph.state import UsageEvent

Role = Literal["planner", "worker", "reviewer", "writer"]

# Per-1M-token prices in USD, keyed by bare (undated) model id: (input, output).
# OpenAI returns dated model names (e.g. "gpt-4o-mini-2024-07-18"); ``_price_for``
# matches those against these prefixes. F9 may relocate this table.
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
}

# Lazily-built, cached model instance (one for all roles in F2).
_model: BaseChatModel | None = None


def get_model(role: Role) -> BaseChatModel:
    """Return the chat model for ``role``.

    F2 ignores ``role`` and returns a single cached model configured from
    ``settings.DEFAULT_MODEL``. F9 introduces real per-role routing behind this
    same signature.
    """
    global _model
    if _model is None:
        # Pass the key explicitly: pydantic-settings loads it into ``settings`` but
        # does not set the OS env var the OpenAI SDK looks for.
        _model = init_chat_model(settings.DEFAULT_MODEL, api_key=settings.OPENAI_API_KEY)
    return _model


def _price_for(model_name: str) -> tuple[float, float]:
    """(input, output) per-1M USD for ``model_name``.

    Exact match first, then prefix match so dated OpenAI ids resolve to their
    base price. Unknown models price at zero.
    """
    if model_name in MODEL_PRICES:
        return MODEL_PRICES[model_name]
    for key, price in MODEL_PRICES.items():
        if model_name.startswith(key):
            return price
    return (0.0, 0.0)


def track_usage(node: str, response: AIMessage) -> UsageEvent:
    """Build a ``UsageEvent`` from an ``AIMessage``'s token usage and pricing.

    ``response.usage_metadata`` may be ``None`` (provider reported no usage) —
    treated as zero tokens. The model id is read from ``response_metadata`` and
    falls back to the configured default.
    """
    usage = response.usage_metadata
    input_tokens = usage["input_tokens"] if usage else 0
    output_tokens = usage["output_tokens"] if usage else 0

    model_name = response.response_metadata.get("model_name") or settings.DEFAULT_MODEL
    price_in, price_out = _price_for(model_name)
    cost_usd = input_tokens / 1e6 * price_in + output_tokens / 1e6 * price_out

    return UsageEvent(
        node=node,
        model=model_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )
