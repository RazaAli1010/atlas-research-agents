# Atlas evaluation summary

- **Run at:** 20260722-090349
- **Runs:** 4
- **Seed:** 42
- **Success rate:** 0.0%
- **Latency p50 / p95 (s):** 146.3 / 158.4
- **Mean cost per run:** $0.0240

## Failure taxonomy (by first-failing grader)

| First-failing grader | Runs | % of all runs |
| -------------------- | ---- | ------------- |
| groundedness         | 4    | 100.0%        |

## Per-category success

| Category        | Runs | Success rate |
| --------------- | ---- | ------------ |
| how_it_works    | 1    | 0.0%         |
| market_overview | 1    | 0.0%         |
| pricing_quant   | 1    | 0.0%         |
| tech_comparison | 1    | 0.0%         |

---

## Per-run detail

- **Compare Apache Kafka and RabbitMQ for a real-time messaging pipeline** (tech_comparison) — success=False; scores={'structure': 1.0, 'citation': 1.0, 'coverage': 1.0, 'groundedness': 0.2}; cost=$0.0284; 158s; revision_loops=12
- **Overview of the commercial drone delivery market** (market_overview) — success=False; scores={'structure': 1.0, 'citation': 1.0, 'coverage': 1.0, 'groundedness': 0.2}; cost=$0.0245; 154s; revision_loops=10
- **How does DNS resolution work** (how_it_works) — success=False; scores={'structure': 1.0, 'citation': 1.0, 'coverage': 1.0, 'groundedness': 0.4}; cost=$0.0206; 146s; revision_loops=8
- **Compare the cost of Datadog versus self-hosted Prometheus for 200 hosts** (pricing_quant) — success=False; scores={'structure': 1.0, 'citation': 1.0, 'coverage': 1.0, 'groundedness': 0.0}; cost=$0.0223; 134s; revision_loops=9
