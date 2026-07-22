"""Project per-config cost from an existing benchmark run — no new API calls (F9).

The F8 benchmark stored real per-node costs (``cost_per_node`` in ``results.jsonl``).
Those runs used the F2 stub router, i.e. every role ran on ``DEFAULT_MODEL``
(``gpt-4o-mini``) — so an existing results dir *is* the all-cheap config, measured.

Cost is a pure function of ``tokens x price``. The ``gpt-4o`` : ``gpt-4o-mini`` price
ratio is **uniform** across input and output tokens (2.50/0.15 == 10.00/0.60 == 16.667),
so a node's cheap-tier cost can be converted to its strong-tier cost by a single multiply
— no input/output token split needed. That lets us re-price the measured baseline into the
routed and all-strong configs exactly, without re-running the graph.

**This projects COST only.** It assumes identical token trajectories across model tiers;
it says nothing about success/quality, which genuinely requires live runs on each config.

Usage (from ``backend/``):
    uv run python evals/project_costs.py                        # newest results dir
    uv run python evals/project_costs.py --results-dir evals/results/20260722-090349
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import mean

# Import the single source of truth for prices so the projection tracks any edit to it.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.llm.router import MODEL_PRICES  # noqa: E402

# The tiers the routed config mixes. Baseline runs are priced at CHEAP for every role.
STRONG = "gpt-4o"
CHEAP = "gpt-4o-mini"
# Roles kept on the strong tier under the routed default; the worker stays cheap.
STRONG_ROLES = ("planner", "reviewer", "writer")


def _price_ratio(strong: str, cheap: str) -> float:
    """Strong/cheap price multiplier, requiring a uniform input==output ratio.

    A uniform ratio is what makes a split-free re-price exact. If a future MODEL_PRICES
    edit breaks that, fail loudly rather than emit a silently-wrong number.
    """
    (si, so), (ci, co) = MODEL_PRICES[strong], MODEL_PRICES[cheap]
    r_in, r_out = si / ci, so / co
    if abs(r_in - r_out) > 1e-9:
        raise ValueError(
            f"non-uniform price ratio ({r_in:.4f} in vs {r_out:.4f} out) for "
            f"{strong}/{cheap}: split-free projection is invalid — re-run the live "
            "benchmark instead."
        )
    return r_in


def _config_cost(cost_per_node: dict[str, float], ratio: float, mode: str) -> float:
    """Total run cost under ``mode`` given cheap-tier measured per-node costs.

    mode: "cheap" (as measured), "strong" (every node x ratio), or
    "routed" (STRONG_ROLES x ratio, worker stays cheap).
    """
    total = 0.0
    for node, cost in cost_per_node.items():
        if mode == "strong":
            total += cost * ratio
        elif mode == "routed":
            total += cost * ratio if node in STRONG_ROLES else cost
        else:  # cheap — the measured baseline
            total += cost
    return total


def load_costs(results_dir: Path) -> list[dict[str, float]]:
    """Per-node cost dicts for runs that actually produced usage (drop errored 0-cost rows)."""
    rows: list[dict[str, float]] = []
    for line in (results_dir / "results.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        per_node = rec.get("cost_per_node") or {}
        if per_node:  # skip runs that errored before any priced LLM call
            rows.append(per_node)
    return rows


def _newest_results_dir(root: Path) -> Path:
    dirs = [d for d in root.iterdir() if d.is_dir() and (d / "results.jsonl").exists()]
    if not dirs:
        raise FileNotFoundError(f"no results.jsonl under {root}")
    return max(dirs, key=lambda d: d.name)


def project(results_dir: Path) -> dict[str, float]:
    """Mean cost/run for each config + the routed-vs-strong saving, from one results dir."""
    ratio = _price_ratio(STRONG, CHEAP)
    rows = load_costs(results_dir)
    if not rows:
        raise ValueError(f"no priced runs in {results_dir}")
    cheap = mean(_config_cost(r, ratio, "cheap") for r in rows)
    routed = mean(_config_cost(r, ratio, "routed") for r in rows)
    strong = mean(_config_cost(r, ratio, "strong") for r in rows)
    return {
        "n": len(rows),
        "ratio": ratio,
        "all_strong": strong,
        "routed": routed,
        "all_cheap": cheap,
        "routed_saving_pct": (1 - routed / strong) * 100 if strong else 0.0,
        "cheap_saving_pct": (1 - cheap / strong) * 100 if strong else 0.0,
    }


def _render(p: dict[str, float], results_dir: Path) -> str:
    return (
        f"Source: {results_dir}  (n={int(p['n'])} priced runs)\n"
        f"gpt-4o / gpt-4o-mini price ratio: {p['ratio']:.3f}x (uniform in/out)\n\n"
        f"  all-gpt-4o       mean $/run : ${p['all_strong']:.4f}   (projected)\n"
        f"  routed (default) mean $/run : ${p['routed']:.4f}   (projected)\n"
        f"  all-gpt-4o-mini  mean $/run : ${p['all_cheap']:.4f}   (MEASURED)\n\n"
        f"  routed vs all-gpt-4o  cost saving : {p['routed_saving_pct']:.1f}%\n"
        f"  all-mini vs all-4o    cost saving : {p['cheap_saving_pct']:.1f}%\n"
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Project F9 routing cost from a benchmark run.")
    parser.add_argument(
        "--results-dir",
        default=None,
        help="a results/{timestamp} dir (default: newest under evals/results)",
    )
    args = parser.parse_args(argv)
    results_dir = (
        Path(args.results_dir)
        if args.results_dir
        else _newest_results_dir(Path(__file__).parent / "results")
    )
    print(_render(project(results_dir), results_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
