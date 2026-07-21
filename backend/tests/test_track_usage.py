"""track_usage prices token usage from MODEL_PRICES, incl. dated OpenAI ids."""

from langchain_core.messages import AIMessage

from app.llm.router import MODEL_PRICES, track_usage


def _msg(model_name: str, in_tok: int, out_tok: int) -> AIMessage:
    return AIMessage(
        content="",
        usage_metadata={
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "total_tokens": in_tok + out_tok,
        },
        response_metadata={"model_name": model_name},
    )


def test_cost_matches_hand_computation() -> None:
    price_in, price_out = MODEL_PRICES["gpt-4o-mini"]
    event = track_usage("planner", _msg("gpt-4o-mini", 1_000_000, 500_000))

    expected = 1.0 * price_in + 0.5 * price_out
    assert event.cost_usd == expected
    assert event.node == "planner"


def test_dated_model_name_matches_by_prefix() -> None:
    price_in, _ = MODEL_PRICES["gpt-4o-mini"]
    event = track_usage("planner", _msg("gpt-4o-mini-2024-07-18", 1_000_000, 0))

    assert event.cost_usd == price_in


def test_unknown_model_prices_zero() -> None:
    event = track_usage("planner", _msg("some-unknown-model", 1_000_000, 1_000_000))
    assert event.cost_usd == 0.0


def test_missing_usage_metadata_is_zero() -> None:
    msg = AIMessage(content="", response_metadata={"model_name": "gpt-4o-mini"})
    event = track_usage("writer", msg)

    assert event.input_tokens == 0
    assert event.output_tokens == 0
    assert event.cost_usd == 0.0
