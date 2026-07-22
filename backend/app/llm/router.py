"""Role->model routing + usage tracking. Stubbed in F2, real routing in F9.

Every LLM call must go through this router; nodes never instantiate model clients
directly (SHARED CONTEXT §2.5).

F9 behaviour (public signatures unchanged from the F2 stub — that was the point):
- ``get_model(role)`` resolves the role to a provider-prefixed model id via
  ``settings.MODEL_ROUTING`` (falling back to ``settings.DEFAULT_MODEL`` for roles
  not present in the map) and caches one built client per role.
- ``track_usage`` reads token usage off a LangChain ``AIMessage`` and prices it
  from ``MODEL_PRICES`` — unchanged.

OpenAI is the sole provider (§3), so every routed model uses ``OPENAI_API_KEY``.
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
# matches those against these prefixes. Every model reachable via the default
# MODEL_ROUTING must appear here (a zero-priced model would silently defeat the
# RUN_COST_CEILING_USD guard in the worker).
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),  # cheap tier — default worker model
    "gpt-4o": (2.50, 10.00),      # strong tier — default planner/reviewer/writer model
}

# Lazily-built chat clients, cached per role (F9 routes each role independently).
_models: dict[str, BaseChatModel] = {}


def get_model(role: Role) -> BaseChatModel:
    """Return the chat model for ``role``, building and caching it on first use.

    The model id comes from ``settings.MODEL_ROUTING[role]``, falling back to
    ``settings.DEFAULT_MODEL`` for a role not present in the map. Signature is
    unchanged from the F2 stub; only the routing internals are real now.
    """
    if role not in ("planner", "worker", "reviewer", "writer"):
        raise ValueError(f"unknown role: {role!r}")
    if role not in _models:
        model_id = settings.MODEL_ROUTING.get(role, settings.DEFAULT_MODEL)
        # Pass the key explicitly: pydantic-settings loads it into ``settings`` but
        # does not set the OS env var the OpenAI SDK looks for.
        _models[role] = init_chat_model(model_id, api_key=settings.OPENAI_API_KEY)
    return _models[role]


def _reset_models() -> None:
    """Clear the per-role model cache (test hook — cache must not leak between cases)."""
    _models.clear()


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
