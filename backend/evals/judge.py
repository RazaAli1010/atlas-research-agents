"""LLM-as-judge model helper for the eval graders (F8).

The coverage and groundedness graders need a chat model, but they are **not** graph
nodes, so SHARED CONTEXT §2.5 (nodes never instantiate models directly) does not
govern them, and F9 owns ``app/llm/router.py``. This thin helper keeps judge-model
selection 12-factor (env-driven via ``EVAL_JUDGE_MODEL`` / ``EVAL_SMOKE_MODEL``) and
in one place. Tests monkeypatch ``get_judge_model``.
"""

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel

from app.config import settings


def get_judge_model(cheap: bool = False) -> BaseChatModel:
    """Return the LLM-judge chat model.

    ``cheap=True`` selects ``EVAL_SMOKE_MODEL`` (used by ``run_benchmark.py --smoke``);
    otherwise the strong ``EVAL_JUDGE_MODEL``. The API key is passed explicitly:
    pydantic-settings loads it into ``settings`` but does not export it to the env the
    OpenAI SDK reads (mirrors ``app.llm.router.get_model``).
    """
    model_id = settings.EVAL_SMOKE_MODEL if cheap else settings.EVAL_JUDGE_MODEL
    return init_chat_model(model_id, api_key=settings.OPENAI_API_KEY)
