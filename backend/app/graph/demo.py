"""Tiny CLI to exercise the graph end-to-end.

Usage:
    uv run python -m app.graph.demo "Compare vector database pricing for a startup"
    uv run python -m app.graph.demo "<topic>" --interactive [--thread <id>]

Builds the planner -> approval_gate -> worker×N -> reviewer -> writer graph with the
config-selected checkpointer and invokes it. Without ``--interactive`` the graph pauses
at the approval interrupt and the demo auto-approves so the run completes in one shot.
With ``--interactive`` it prints the plan and waits for the human's ``y`` (approve) or
``e`` (edit) decision, then resumes with ``Command(resume=...)``.

Passing ``--thread <id>`` pins the ``thread_id`` so the run can be killed at the pause
and resumed by a *fresh process* over the same checkpointer file (durability proof).
When ``LANGSMITH_TRACING`` is on, the run is traceable in the LangSmith ``atlas``
project with named nodes.
"""

import sys
from typing import cast
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from app.config import settings
from app.graph.builder import build_graph
from app.graph.state import ResearchState
from app.observability import enable_langsmith
from app.persistence.checkpointer import checkpointer_cx


def _enable_langsmith() -> None:
    """Export LangSmith env from settings so runs are traced (§2.9)."""
    enable_langsmith(settings)


def _seed_state(topic: str) -> ResearchState:
    return {
        "topic": topic,
        "plan": [],
        "plan_approved": False,
        "drafts": [],
        "reviews": [],
        "revision_counts": {},
        "final_report_md": "",
        "usage_log": [],
        "tool_calls": [],
        "status": "planning",
    }


def _flag_value(argv: list[str], name: str) -> str | None:
    """Return the value following ``--name`` on the command line, if present."""
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


def _print_plan(plan: list[dict]) -> None:
    print("\nProposed plan:")
    for i, section in enumerate(plan, start=1):
        print(f"  {i}. {section['title']} — {section['objective']}")


def _human_decision(plan: list[dict]) -> dict:
    """Prompt for approve (y) / edit (e) and build the resume payload."""
    choice = input("\nApprove this plan? [y = approve / e = edit]: ").strip().lower()
    if choice == "e":
        n = int(input(f"keep N sections (1-{len(plan)}): ").strip())
        edited = plan[: max(1, min(n, len(plan)))]
        return {"action": "edit", "plan": edited}
    return {"action": "approve"}


def _print_summary(topic: str, final: ResearchState) -> None:
    print(f"\nTopic: {topic}\n")
    print("Plan outline:")
    for i, section in enumerate(final["plan"], start=1):
        print(f"  {i}. {section.title}")

    print(f"\nDrafts produced: {len(final['drafts'])}")
    print("\n" + "=" * 72)
    print(final["final_report_md"])
    print("=" * 72)

    total_cost = sum(e.cost_usd for e in final["usage_log"])
    print(f"\ntotal_cost_usd: {total_cost:.4f}")


def main(argv: list[str]) -> int:
    positional = [a for a in argv[1:] if not a.startswith("--")]
    if not positional or not positional[0].strip():
        print(
            'usage: python -m app.graph.demo "<research topic>" '
            "[--interactive] [--thread <id>]",
            file=sys.stderr,
        )
        return 2

    topic = positional[0]
    interactive = "--interactive" in argv
    thread_id = _flag_value(argv, "--thread") or str(uuid4())
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    _enable_langsmith()

    with checkpointer_cx() as cp:
        graph = build_graph(checkpointer=cp)

        # Run until the approval interrupt (or resume an already-paused thread).
        snap = graph.get_state(config)
        if not snap.interrupts:
            graph.invoke(_seed_state(topic), config=config)
            snap = graph.get_state(config)

        if snap.interrupts:
            plan = snap.interrupts[0].value["plan"]
            _print_plan(plan)
            decision = _human_decision(plan) if interactive else {"action": "approve"}
            graph.invoke(Command(resume=decision), config=config)

        final = cast(ResearchState, graph.get_state(config).values)

    _print_summary(topic, final)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
