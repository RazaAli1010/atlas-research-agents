"""Builders for F8 grader/harness tests (not collected — no ``test_`` prefix).

A coherent default run: a structure-compliant report whose two `[n]` markers,
draft sources, and tool-call URLs all line up, so each grader passes on the default
and tests only override the one thing they exercise.
"""

from typing import Any

from app.graph.state import SectionDraft, SectionPlan, Source, ToolCallRecord
from evals.graders import EvalRun

VALID_REPORT = """# Vector DBs

## Executive summary

Vector databases vary in price and scale.

## 1. Pricing

Pinecone is cheap [1].

## 2. Scale

Weaviate scales well [2].

## Limitations

None.

## Sources

1. [A](https://a.com)
2. [B](https://b.com)
"""


def default_plan() -> list[SectionPlan]:
    return [
        SectionPlan(id="s1", title="Pricing", objective="o", suggested_queries=["q"]),
        SectionPlan(id="s2", title="Scale", objective="o", suggested_queries=["q"]),
    ]


def default_drafts() -> list[SectionDraft]:
    src_a = Source(url="https://a.com", title="A", snippet="Pinecone is cheap.", tool="web_search")
    src_b = Source(url="https://b.com", title="B", snippet="Weaviate scales.", tool="web_search")
    return [
        SectionDraft(
            section_id="s1", content_md="Pinecone is cheap [1].", sources=[src_a], revision=0
        ),
        SectionDraft(
            section_id="s2", content_md="Weaviate scales well [1].", sources=[src_b], revision=0
        ),
    ]


def default_tool_calls() -> list[ToolCallRecord]:
    return [
        ToolCallRecord(section_id="s1", tool="web_search", urls=["https://a.com"]),
        ToolCallRecord(section_id="s2", tool="web_search", urls=["https://b.com"]),
    ]


def make_run(**overrides: Any) -> EvalRun:
    """A coherent default :class:`EvalRun`; pass overrides to exercise one grader."""
    base: dict[str, Any] = {
        "topic": "Vector DBs",
        "category": "tech_comparison",
        "must_cover": ["price", "scale", "latency"],
        "report_md": VALID_REPORT,
        "plan": default_plan(),
        "drafts": default_drafts(),
        "reviews": [],
        "revision_counts": {"s1": 0, "s2": 0},
        "usage_log": [],
        "tool_calls": default_tool_calls(),
        "wall_time_s": 1.0,
        "seed": 0,
    }
    base.update(overrides)
    return EvalRun(**base)
