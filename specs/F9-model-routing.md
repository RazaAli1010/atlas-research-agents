## F9 — Model routing & cost optimization

**Goal:** Route each graph role to a cost-appropriate model behind the existing `get_model(role)` stub, and measure the saving with the F8 benchmark so the project can state a real "cut cost X% via model routing" number without dropping success rate.

**Depends on:** F2 (router stub + `get_model`/`track_usage`/`MODEL_PRICES`), F5/F6 (`RunDetail` on `GET /api/runs/{id}`), F8 (`evals/run_benchmark.py`, `RunResult`, benchmark topics).

> **Provider resolution (decided).** The F9 description named `anthropic:claude-sonnet-4-6` / `anthropic:claude-haiku-4-5`, which conflicts with SHARED CONTEXT §3 ("OpenAI is the sole provider, no Anthropic") and the installed router (passes `api_key=settings.OPENAI_API_KEY`, no `langchain-anthropic` dep, no `ANTHROPIC_API_KEY`). Per user decision, **stay single-provider OpenAI**: map the strong tier to `openai:gpt-4o` and the cheap tier to `openai:gpt-4o-mini`. The cost-optimization story is identical (expensive vs cheap tier); §3 is honored; no new dependency or key. Anthropic is explicitly out of scope.

### Context digest

Exact contracts this feature touches — use these names verbatim.

- **Router (`app/llm/router.py`)** — public signatures are FINAL; F9 replaces only internals:
  - `Role = Literal["planner", "worker", "reviewer", "writer"]`
  - `get_model(role: Role) -> BaseChatModel` — currently caches ONE `_model` from `settings.DEFAULT_MODEL` for all roles.
  - `track_usage(node: str, response: AIMessage) -> UsageEvent` — **unchanged in F9.** Reads `response.response_metadata["model_name"]` (bare, sometimes dated OpenAI id), prices via `_price_for`, falls back to `settings.DEFAULT_MODEL`.
  - `_price_for(model_name)` — exact match then **prefix** match against `MODEL_PRICES`, else `(0.0, 0.0)`.
  - `MODEL_PRICES: dict[str, tuple[float, float]]` — per-1M USD `(input, output)`, keyed by **bare/undated** model id. Currently `{"gpt-4o-mini": (0.15, 0.60), "gpt-4o": (2.50, 10.00)}`.
  - Model is built via `init_chat_model(<provider:model>, api_key=settings.OPENAI_API_KEY)` — provider-prefixed strings.
- **Nodes calling the router** (must remain untouched): `planner.py:33 get_model("planner")`, `reviewer.py:83 get_model("reviewer")`, `worker.py:211 get_model("worker")`, `writer.py:301 get_model("writer")`.
- **Config (`app/config.py`)** — `Settings(BaseSettings)`, `DEFAULT_MODEL: str = "openai:gpt-4o-mini"`, `EVAL_JUDGE_MODEL: str = "openai:gpt-4o"`, `EVAL_SMOKE_MODEL`. `get_settings()` builds a fresh instance (tests use it to control env).
- **Cost ceiling** — `RUN_COST_CEILING_USD = 1.50` (`app/graph/state.py`). Enforced in `worker.py:205-206`: `accrued = sum(e.cost_usd for e in payload["usage_log"]); cost_capped = accrued >= RUN_COST_CEILING_USD`. Reads priced `usage_log` — stays correct for any config as long as `MODEL_PRICES` covers the routed models. **Worker code is NOT modified.**
- **API (`app/api/routes_runs.py`)** — `RunDetail` pydantic model with `RunDetail.from_row_and_state(row, values)`; already carries `usage_log: list[UsageEvent]`. `UsageEvent(node, model, input_tokens, output_tokens, cost_usd)` (§5).
- **Benchmark (`evals/run_benchmark.py`)** — `run_benchmark.py --n 20` runs full graph per topic (auto-approves), writes `evals/results/{timestamp}/results.jsonl` + `summary.md`. `RunResult` already records `cost_usd`, `cost_per_node`, `wall_time_s`, `success`. Judge model is `EVAL_JUDGE_MODEL` (`get_judge_model`), **independent of `MODEL_ROUTING`** — keep it fixed across configs so grading is fair. `--n 40` default; `--seed 42` default; topics in 4 categories (`tech_comparison`, `market_overview`, `how_it_works`, `pricing_quant`).
- **Principles:** §2.5 every LLM call goes through the router; §2.6 cost/token tracking mandatory; §2.8 12-factor config via `pydantic-settings`, update `.env.example`.

### Context deltas

Two changes to shared contracts — apply to SHARED CONTEXT / mirrors before/with implementation:

1. **New config env var** `MODEL_ROUTING` (JSON, optional, defaulted). Add to §3 config list and to `backend/.env.example` with the default JSON commented.
2. **New `RunDetail` field** `cost_breakdown: dict[str, float]` on `GET /api/runs/{id}` (§7). Node→summed-cost map derived from `usage_log`. Update the note in §7 that `RunDetail` gains `cost_breakdown`, and add a mirror note for frontend `types.ts` (F11 consumes it — F11 owns the actual TS edit; F9 only records the note).

No state-schema (§5) change: `cost_breakdown` is a **derived API field**, never stored in `ResearchState`.

### Scope

1. **`app/config.py` — add `MODEL_ROUTING`.**
   - Field: `MODEL_ROUTING: dict[str, str] = {default map}` where default is
     `{"planner": "openai:gpt-4o", "reviewer": "openai:gpt-4o", "writer": "openai:gpt-4o", "worker": "openai:gpt-4o-mini"}`.
   - pydantic-settings JSON-decodes a dict field from its env value automatically, so `MODEL_ROUTING='{"worker":"openai:gpt-4o-mini",...}'` in `.env`/env overrides it. (No `NoDecode` — unlike `CORS_ORIGINS`, JSON is the intended env format here.)
   - `@field_validator("MODEL_ROUTING")` rejecting **unknown roles**: every key must be in `{"planner","worker","reviewer","writer"}`; raise `ValueError(f"unknown role(s) in MODEL_ROUTING: {bad}")` otherwise. Partial maps are allowed (missing roles fall back to `DEFAULT_MODEL` in `get_model`).
2. **`app/llm/router.py` — real per-role routing.**
   - Replace the single `_model` global with a per-role cache: `_models: dict[str, BaseChatModel] = {}`.
   - `get_model(role)`:
     ```python
     def get_model(role: Role) -> BaseChatModel:
         if role not in ("planner", "worker", "reviewer", "writer"):
             raise ValueError(f"unknown role: {role!r}")
         if role not in _models:
             model_id = settings.MODEL_ROUTING.get(role, settings.DEFAULT_MODEL)
             _models[role] = init_chat_model(model_id, api_key=settings.OPENAI_API_KEY)
         return _models[role]
     ```
   - Add `def _reset_models() -> None: _models.clear()` for tests (cache must not leak across settings changes). Docstring: signature unchanged from F2; only internals routed.
   - **`track_usage` and `_price_for` unchanged.**
3. **`app/llm/router.py` — extend `MODEL_PRICES`.** Ensure every model reachable via the default `MODEL_ROUTING` has a price. `gpt-4o` and `gpt-4o-mini` are already present with correct rates — keep them explicit (add a comment tying them to the routed tiers). No zero-priced routed model may exist under the default config.
4. **`app/api/routes_runs.py` — `cost_breakdown` on `RunDetail`.**
   - Add field `cost_breakdown: dict[str, float]`.
   - In `from_row_and_state`, derive it from `usage_log`:
     ```python
     breakdown: dict[str, float] = {}
     for ev in values.get("usage_log") or []:
         breakdown[ev.node] = breakdown.get(ev.node, 0.0) + ev.cost_usd
     ```
     Set `cost_breakdown=breakdown`. Keys are node names (`"planner"`, `"worker"`, `"reviewer"`, `"writer"`); values sum `cost_usd` per node.
5. **`backend/.env.example`** — add `MODEL_ROUTING` with the default JSON (commented) and a one-line explanation that it maps role→`init_chat_model` id and is OpenAI-only (§3).
6. **`evals/EXPERIMENTS.md` — protocol + results (new file).** Document and run the 3-config comparison (see Verify). Each config = one `run_benchmark.py --n 20 --seed 42` invocation with `MODEL_ROUTING` set in the environment; `EVAL_JUDGE_MODEL` held constant. Record per config: success rate, mean cost/run, p50 & p95 latency, and the source `results/{timestamp}/` dir. End with a **Decision** line: the routed default is chosen iff its success rate is within 3 points of all-`gpt-4o` at materially lower mean cost; otherwise state the fallback and update the default `MODEL_ROUTING` accordingly.

### Out of scope

- Adding Anthropic or any second provider / second API key (contradicts §3; not this feature).
- Streaming/rate-limit/retry handling in the router beyond routing (the F2 docstring mentioned it; defer — no feature owns it yet, note in `EXPERIMENTS.md` as future work).
- Frontend `types.ts` / cost-breakdown UI — **F11** owns rendering; F9 only ships the API field + mirror note.
- Changing any graph node, `track_usage`, the state schema, or the benchmark grader logic.
- Per-run dynamic model selection (routing is static per role via config).

### Implementation notes

- **Verified versions:** `langgraph>=1.0,<2.0`, `langchain>=1.0,<2.0`, `langchain-openai` (pyproject). `init_chat_model` lives in `langchain.chat_models` and accepts provider-prefixed ids (`"openai:gpt-4o"`) + `api_key=`. Confirmed against the installed router import (`from langchain.chat_models import init_chat_model`).
- **`MODEL_PRICES` keys stay bare/undated.** `track_usage` reads `response_metadata["model_name"]` (e.g. `gpt-4o-2024-08-06`), and `_price_for` prefix-matches. Do NOT key `MODEL_PRICES` by the provider-prefixed routing string — that would silently zero-price and break the cost ceiling.
- **Cache determinism:** `_models` is process-global and memoizes per role; changing `settings.MODEL_ROUTING` after first `get_model` call has no effect until `_reset_models()`. Tests that vary routing must construct settings first and call `_reset_models()`. The 3 benchmark configs run as **separate processes** (env set before `python evals/run_benchmark.py`), so caching is a non-issue there.
- **Cost ceiling invariance:** because `MODEL_PRICES` covers both routed models, `worker.py`'s `accrued >= RUN_COST_CEILING_USD` check keeps firing correctly under all-`gpt-4o` (hits ceiling sooner), routed, and all-`gpt-4o-mini` (rarely). No worker edit — verify by asserting no diff to `worker.py`.
- **Fair comparison:** the eval judge (`EVAL_JUDGE_MODEL=openai:gpt-4o`) grades all three configs and is not part of `MODEL_ROUTING`, so grading cost/quality is constant across rows. State this in `EXPERIMENTS.md`.
- **Cost of running the experiment:** 3 × 20 real graph runs hit the OpenAI + Tavily APIs and cost real money/time. Requires live `OPENAI_API_KEY` + `TAVILY_API_KEY`. Budget for it before the session; it cannot be faked (Verify requires real numbers).

### Test plan

`backend/tests/` (pytest). Use `get_settings()` to build settings from a controlled env and `_reset_models()` between cases.

- **`test_router_routing.py::test_routing_maps_roles_to_configured_models`** — set `MODEL_ROUTING` env to distinct ids per role; assert `get_model("planner")` vs `get_model("worker")` resolve to different configured model ids (assert on the built model's `model_name`/`model`, or monkeypatch `init_chat_model` to capture the id argument).
- **`test_router_routing.py::test_partial_routing_falls_back_to_default_model`** — `MODEL_ROUTING` omits `worker`; assert `get_model("worker")` uses `DEFAULT_MODEL`.
- **`test_config_routing.py::test_unknown_role_rejected`** — `MODEL_ROUTING='{"bogus":"openai:gpt-4o"}'` → `get_settings()` raises `ValidationError`/`ValueError` mentioning the bad role.
- **`test_config_routing.py::test_routing_json_parses`** — valid JSON env produces the expected `dict[str,str]`.
- **`test_router_routing.py::test_get_model_rejects_unknown_role`** — `get_model("nope")` raises `ValueError`.
- **`test_cost_breakdown.py::test_cost_breakdown_sums_per_node`** — build `RunDetail.from_row_and_state` with a `usage_log` of several `UsageEvent`s across `planner`/`worker`×2/`writer`; assert `cost_breakdown == {"planner": ..., "worker": <sum of both>, "writer": ...}` and that `sum(cost_breakdown.values())` matches total `usage_log` cost.
- **`test_cost_breakdown.py::test_cost_breakdown_empty_usage_log`** — empty `usage_log` → `cost_breakdown == {}`.

### Verify

```bash
cd backend
# 1. unit tests
uv run pytest tests/test_router_routing.py tests/test_config_routing.py tests/test_cost_breakdown.py -q
# 2. no node/worker code changed by this feature
git diff --stat -- app/graph/nodes/   # expect: no output (empty)
# 3. run the 3-config benchmark (real API calls) — each writes evals/results/{ts}/
MODEL_ROUTING='{"planner":"openai:gpt-4o","reviewer":"openai:gpt-4o","writer":"openai:gpt-4o","worker":"openai:gpt-4o"}' \
  uv run python evals/run_benchmark.py --n 20 --seed 42            # (a) all-gpt-4o
uv run python evals/run_benchmark.py --n 20 --seed 42             # (b) routed (default MODEL_ROUTING)
MODEL_ROUTING='{"planner":"openai:gpt-4o-mini","reviewer":"openai:gpt-4o-mini","writer":"openai:gpt-4o-mini","worker":"openai:gpt-4o-mini"}' \
  uv run python evals/run_benchmark.py --n 20 --seed 42            # (c) all-gpt-4o-mini
```

Expected: all unit tests pass; `git diff --stat -- app/graph/nodes/` is empty; `evals/EXPERIMENTS.md` contains a comparison table populated with the real success/mean-cost/p50/p95 numbers from the three `summary.md` outputs and a stated Decision. `GET /api/runs/{id}` responses include a non-empty `cost_breakdown` for a completed run.

### Acceptance criteria

- [ ] `MODEL_ROUTING` config drives role→model routing behind the unchanged `get_model(role)` signature; `git diff --stat -- app/graph/nodes/` shows no node changes.
- [ ] Config parsing works and an unknown role is rejected at `Settings` construction (`test_config_routing.py` passes).
- [ ] `get_model` returns per-role-distinct models under a routed config and falls back to `DEFAULT_MODEL` for unmapped roles (`test_router_routing.py` passes).
- [ ] `GET /api/runs/{id}` returns `cost_breakdown: {node: cost}` summing `usage_log` per node (`test_cost_breakdown.py` passes); §7 + F11 `types.ts` mirror note updated.
- [ ] `evals/EXPERIMENTS.md` contains the 3-config table (n≥20 each) with real numbers and a stated decision on the default.
- [ ] `RUN_COST_CEILING_USD` still enforced under all three configs (no `worker.py` change; `MODEL_PRICES` covers every routed model so no routed model prices at zero).
- [ ] `.env.example` documents `MODEL_ROUTING`; backend typechecks (`mypy`) and lints (`ruff`).
