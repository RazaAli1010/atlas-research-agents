"""Benchmark CLI for the Atlas evaluation harness (F8).

Runs N benchmark topics through the full graph (auto-approving each plan via
programmatic resume), grades every run, and emits ``results.jsonl`` + a markdown
``summary.md`` under ``evals/results/{timestamp}/``.

Usage (from ``backend/``):
    uv run python evals/run_benchmark.py --n 10
    uv run python evals/run_benchmark.py --smoke        # 3 topics, cheap judge
    uv run python evals/run_benchmark.py --category pricing_quant --n 5

Determinism: topic selection and grader sampling are fully reproducible given
``--seed``; the underlying LLM/tool outputs are not (inherent).
"""

from __future__ import annotations

import sys
from pathlib import Path

# --- import bootstrap: allow `python evals/run_benchmark.py` (script dir is evals/) ---
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import argparse  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import random  # noqa: E402
import time  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from concurrent.futures import ThreadPoolExecutor, as_completed  # noqa: E402
from datetime import UTC, datetime  # noqa: E402
from hashlib import sha256  # noqa: E402
from typing import Any  # noqa: E402
from uuid import uuid4  # noqa: E402

from langchain_core.runnables import RunnableConfig  # noqa: E402
from langgraph.types import Command  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from app.config import settings  # noqa: E402
from app.graph.builder import build_graph  # noqa: E402
from app.graph.demo import _seed_state  # noqa: E402  (shared seed shape, incl. tool_calls)
from app.persistence.checkpointer import checkpointer_cx  # noqa: E402
from evals.graders import EvalRun, is_success, run_all_graders  # noqa: E402
from evals.judge import get_judge_model  # noqa: E402

CATEGORIES = ["tech_comparison", "market_overview", "how_it_works", "pricing_quant"]
TOPICS_PATH = Path(__file__).parent / "benchmark_topics.jsonl"
TEMPLATE_PATH = Path(__file__).parent / "report_template.md"


class BenchmarkTopic(BaseModel):
    topic: str
    category: str
    must_cover: list[str]


class RunResult(BaseModel):
    """One benchmarked run — the shape of a ``results.jsonl`` line."""

    topic: str
    category: str
    success: bool
    first_failing: str | None
    grader_scores: dict[str, float]
    grader_passed: dict[str, bool]
    grader_details: dict[str, str]
    wall_time_s: float
    cost_usd: float
    revision_loops: int
    tool_calls_per_section: dict[str, int]
    cost_per_node: dict[str, float]
    error: str | None = None


# --- topic loading + deterministic selection ---------------------------------------


def load_topics(path: Path = TOPICS_PATH) -> list[BenchmarkTopic]:
    """Parse ``benchmark_topics.jsonl`` in file order."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return [BenchmarkTopic.model_validate_json(line) for line in lines if line.strip()]


def select_topics(
    topics: list[BenchmarkTopic], n: int, seed: int, category: str | None = None
) -> list[BenchmarkTopic]:
    """Deterministically pick ``n`` topics: filter, canonical-sort, seeded sample."""
    pool = [t for t in topics if category is None or t.category == category]
    pool = sorted(pool, key=lambda t: t.topic)
    return random.Random(seed).sample(pool, min(n, len(pool)))


# --- one run ------------------------------------------------------------------------


def _per_run_seed(seed: int, topic: str) -> int:
    """Stable grader-sampling seed for a (run seed, topic) pair."""
    return int(sha256(f"{seed}:{topic}".encode()).hexdigest()[:8], 16)


def _build_eval_run(
    topic: BenchmarkTopic, values: dict[str, Any], wall_s: float, run_seed: int
) -> EvalRun:
    return EvalRun(
        topic=topic.topic,
        category=topic.category,
        must_cover=topic.must_cover,
        report_md=values.get("final_report_md", ""),
        plan=values.get("plan", []),
        drafts=values.get("drafts", []),
        reviews=values.get("reviews", []),
        revision_counts=values.get("revision_counts", {}),
        usage_log=values.get("usage_log", []),
        tool_calls=values.get("tool_calls", []),
        wall_time_s=wall_s,
        seed=run_seed,
    )


def _trajectory(values: dict[str, Any]) -> tuple[int, dict[str, int], dict[str, float], float]:
    """Revision loops, tool-calls-per-section, cost-per-node, total cost — from state."""
    revision_loops = sum(values.get("revision_counts", {}).values())
    tool_calls_per_section = dict(Counter(r.section_id for r in values.get("tool_calls", [])))
    cost_per_node: dict[str, float] = defaultdict(float)
    for event in values.get("usage_log", []):
        cost_per_node[event.node] += event.cost_usd
    total_cost = sum(event.cost_usd for event in values.get("usage_log", []))
    return revision_loops, tool_calls_per_section, dict(cost_per_node), total_cost


def run_one(topic: BenchmarkTopic, seed: int, judge_cheap: bool) -> RunResult:
    """Drive one topic through the graph (auto-approve), grade it, return a RunResult.

    Any per-run failure (graph error, cost-ceiling abort) becomes a failed RunResult so
    one bad topic never aborts the batch.
    """
    thread_id = str(uuid4())
    run_seed = _per_run_seed(seed, topic.topic)
    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id},
        "metadata": {"eval_topic": topic.topic, "eval_category": topic.category, "eval_seed": seed},
        "tags": ["atlas-eval"],
    }
    t0 = time.perf_counter()
    try:
        judge = get_judge_model(cheap=judge_cheap)
        with checkpointer_cx() as cp:
            graph = build_graph(cp)
            graph.invoke(_seed_state(topic.topic), config=config)
            if graph.get_state(config).interrupts:
                graph.invoke(Command(resume={"action": "approve"}), config=config)
            values = graph.get_state(config).values

        wall = time.perf_counter() - t0
        eval_run = _build_eval_run(topic, values, wall, run_seed)
        results = run_all_graders(eval_run, judge=judge)
        success, first_failing = is_success(results)
        revision_loops, tool_calls_per_section, cost_per_node, cost_usd = _trajectory(values)
        return RunResult(
            topic=topic.topic,
            category=topic.category,
            success=success,
            first_failing=first_failing,
            grader_scores={r.name: r.score for r in results},
            grader_passed={r.name: r.passed for r in results},
            grader_details={r.name: r.detail for r in results},
            wall_time_s=wall,
            cost_usd=cost_usd,
            revision_loops=revision_loops,
            tool_calls_per_section=tool_calls_per_section,
            cost_per_node=cost_per_node,
        )
    except Exception as exc:  # noqa: BLE001 — one topic must not abort the batch
        return RunResult(
            topic=topic.topic,
            category=topic.category,
            success=False,
            first_failing="error",
            grader_scores={},
            grader_passed={},
            grader_details={},
            wall_time_s=time.perf_counter() - t0,
            cost_usd=0.0,
            revision_loops=0,
            tool_calls_per_section={},
            cost_per_node={},
            error=f"{type(exc).__name__}: {exc}",
        )


# --- summary rendering --------------------------------------------------------------


def _percentile(values_sorted: list[float], q: float) -> float:
    """Nearest-rank percentile (safe for n < 2)."""
    if not values_sorted:
        return 0.0
    idx = min(max(math.ceil(q * len(values_sorted)) - 1, 0), len(values_sorted) - 1)
    return values_sorted[idx]


def _failure_taxonomy_table(results: list[RunResult]) -> str:
    failures = Counter(r.first_failing for r in results if not r.success)
    if not failures:
        return "_No failures._"
    total = len(results)
    lines = ["| First-failing grader | Runs | % of all runs |", "| --- | --- | --- |"]
    for name, count in failures.most_common():
        lines.append(f"| {name} | {count} | {count / total * 100:.1f}% |")
    return "\n".join(lines)


def _per_category_table(results: list[RunResult]) -> str:
    by_cat: dict[str, list[RunResult]] = defaultdict(list)
    for r in results:
        by_cat[r.category].append(r)
    lines = ["| Category | Runs | Success rate |", "| --- | --- | --- |"]
    for cat in sorted(by_cat):
        runs = by_cat[cat]
        rate = sum(r.success for r in runs) / len(runs)
        lines.append(f"| {cat} | {len(runs)} | {rate * 100:.1f}% |")
    return "\n".join(lines)


def render_summary(results: list[RunResult], timestamp: str, seed: int) -> str:
    """Fill ``report_template.md`` with aggregate stats + the two tables."""
    n = len(results)
    success_rate = sum(r.success for r in results) / n if n else 0.0
    latencies = sorted(r.wall_time_s for r in results)
    mean_cost = sum(r.cost_usd for r in results) / n if n else 0.0
    return TEMPLATE_PATH.read_text(encoding="utf-8").format(
        timestamp=timestamp,
        n_runs=n,
        seed=seed,
        success_rate=f"{success_rate * 100:.1f}%",
        p50_latency_s=f"{_percentile(latencies, 0.5):.1f}",
        p95_latency_s=f"{_percentile(latencies, 0.95):.1f}",
        mean_cost_usd=f"${mean_cost:.4f}",
        failure_taxonomy_table=_failure_taxonomy_table(results),
        per_category_table=_per_category_table(results),
    )


def write_outputs(results: list[RunResult], out_root: str, timestamp: str, seed: int) -> Path:
    out_dir = Path(out_root) / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "results.jsonl").open("w", encoding="utf-8") as fh:
        for result in results:
            fh.write(result.model_dump_json() + "\n")
    (out_dir / "summary.md").write_text(render_summary(results, timestamp, seed), encoding="utf-8")
    return out_dir


# --- LangSmith (best-effort) --------------------------------------------------------


def _maybe_enable_langsmith(timestamp: str) -> None:
    """Trace every run into one run-scoped experiment project (skipped if tracing off)."""
    if not settings.LANGSMITH_TRACING:
        return
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_PROJECT"] = f"atlas-eval-{timestamp}"
    if settings.LANGSMITH_API_KEY:
        os.environ["LANGSMITH_API_KEY"] = settings.LANGSMITH_API_KEY


# --- CLI ----------------------------------------------------------------------------


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Atlas evaluation benchmark (F8).")
    parser.add_argument("--n", type=int, default=40, help="number of topics to run")
    parser.add_argument("--category", choices=CATEGORIES, default=None, help="filter to a category")
    parser.add_argument("--seed", type=int, default=42, help="seed for topic selection + sampling")
    parser.add_argument("--concurrency", type=int, default=3, help="max concurrent runs")
    parser.add_argument("--smoke", action="store_true", help="3 topics with the cheap judge model")
    parser.add_argument("--out", default="evals/results", help="results output root")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    n = 3 if args.smoke else args.n
    seed = 42 if args.smoke else args.seed
    judge_cheap = args.smoke

    topics = load_topics()
    selected = select_topics(topics, n, seed, args.category)
    if not selected:
        print("No topics matched the selection.", file=sys.stderr)
        return 1

    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    _maybe_enable_langsmith(timestamp)

    print(f"Running {len(selected)} topic(s), concurrency {args.concurrency}, seed {seed}...")
    indexed: dict[int, RunResult] = {}
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(run_one, t, seed, judge_cheap): i for i, t in enumerate(selected)}
        for future in as_completed(futures):
            i = futures[future]
            indexed[i] = future.result()
            print(f"  [{len(indexed)}/{len(selected)}] {selected[i].topic[:60]}")

    results = [indexed[i] for i in range(len(selected))]  # deterministic input order
    out_dir = write_outputs(results, args.out, timestamp, seed)

    successes = sum(r.success for r in results)
    print(f"\nResults written to: {out_dir}")
    print(f"Success rate: {successes}/{len(results)} ({successes / len(results) * 100:.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
