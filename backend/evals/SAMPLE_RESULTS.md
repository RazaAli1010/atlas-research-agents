# Atlas evaluation summary

- **Run at:** 20260722-143657
- **Runs:** 4
- **Seed:** 42
- **Success rate:** 25.0%
- **Latency p50 / p95 (s):** 60.8 / 121.2
- **Mean cost per run:** $0.0883

## Change from previous run (groundedness optimization)

Same 4 topics, same seed (42), strong judge. Prior run: `20260722-090349`.

| Topic | Groundedness (before → after) | Revision loops (before → after) |
| --- | --- | --- |
| Kafka vs RabbitMQ (tech_comparison) | 0.2 → 0.4 | 12 → 7 |
| Commercial drone delivery (market_overview) | 0.2 → 0.4 | 10 → 4 |
| DNS resolution (how_it_works) | 0.4 → **0.8 ✓ pass** | 8 → 2 |
| Datadog vs Prometheus (pricing_quant) | 0.0 → 0.4 | 9 → 2 |

- **Success rate:** 0.0% → **25.0%** (DNS now clears the 0.8 bar).
- **Groundedness:** improved on all 4 topics.
- **Revision loops:** 39 → **15 total (−62%)** — the no-progress early-stop + reviewer calibration.
- **Latency p50:** 146.3s → **60.8s (−58%)**.
- **Per-run graph cost:** $0.0240 → $0.0883 (up — needs verification; see notes below the table).

> Single sample per topic (n=1), so absolute numbers are noisy. The groundedness and
> revision-loop gains are consistent across all four topics; the cost increase is a
> surprise (loops fell, yet graph cost rose) and warrants a per-node re-run to confirm.

## Failure taxonomy (by first-failing grader)

| First-failing grader | Runs | % of all runs |
| --- | --- | --- |
| groundedness | 3 | 75.0% |

## Per-category success

| Category | Runs | Success rate |
| --- | --- | --- |
| how_it_works | 1 | 100.0% |
| market_overview | 1 | 0.0% |
| pricing_quant | 1 | 0.0% |
| tech_comparison | 1 | 0.0% |

---

## Per-run detail

- **Compare Apache Kafka and RabbitMQ for a real-time messaging pipeline** (tech_comparison) — success=False; scores={'structure': 1.0, 'citation': 1.0, 'coverage': 1.0, 'groundedness': 0.4}; cost=$0.1373; 121s; revision_loops=7
- **Overview of the commercial drone delivery market** (market_overview) — success=False; scores={'structure': 1.0, 'citation': 1.0, 'coverage': 1.0, 'groundedness': 0.4}; cost=$0.0942; 90s; revision_loops=4
- **How does DNS resolution work** (how_it_works) — success=True; scores={'structure': 1.0, 'citation': 1.0, 'coverage': 1.0, 'groundedness': 0.8}; cost=$0.0669; 60s; revision_loops=2
- **Compare the cost of Datadog versus self-hosted Prometheus for 200 hosts** (pricing_quant) — success=False; scores={'structure': 1.0, 'citation': 1.0, 'coverage': 1.0, 'groundedness': 0.4}; cost=$0.0548; 60s; revision_loops=2
