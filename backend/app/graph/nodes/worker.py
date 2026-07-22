"""Worker node: researches one section with a hand-written, bounded tool loop (F3).

Reached via the ``Send`` API (one worker per section). Implements an explicit
ReAct-style loop — model with ``.bind_tools(...)`` called in a loop until it stops
requesting tools or the ``MAX_TOOL_CALLS_PER_WORKER`` budget is exhausted. No
prebuilt agent constructors / ``langgraph.prebuilt`` (SHARED CONTEXT §2.1) — this
is deliberately the from-scratch version.

Citation numbering is worker-owned: sources are de-duplicated and numbered as tools
return, and each ``ToolMessage`` shows the model the assigned ``[n]`` so the final
prose's markers always resolve to ``draft.sources[n-1]``.

Payload (Send): ``{"section": SectionPlan, "topic": str, "usage_log": [...],
"feedback"?: str, "previous_draft"?: SectionDraft}``. Output: one ``SectionDraft``
appended to ``drafts`` plus the model-call ``usage_log`` events.
"""

from typing import Any, cast

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.graph.state import (
    MAX_SNIPPET_CHARS,
    MAX_TOOL_CALLS_PER_WORKER,
    RUN_COST_CEILING_USD,
    SectionDraft,
    SectionPlan,
    Source,
    UsageEvent,
)
from app.llm.router import get_model, track_usage
from app.tools import TOOL_NAME_TO_SOURCE_TOOL, get_worker_tools

_SNIPPET_CHARS = MAX_SNIPPET_CHARS

_COST_NOTE = (
    "> _Note: run cost ceiling reached; drafted from context without tool research._"
)
_GAP_NOTE = "_No external sources were retrievable for this section._"
_FALLBACK_BODY = "_The researcher could not produce a draft for this section._"

_FIRST_SYSTEM = (
    "You are a research worker for an autonomous research agent. Research the given "
    "section thoroughly using the available tools, then write the section body in "
    "Markdown. Cite every factual claim with a [n] marker, where n is the number "
    "shown next to a source in the tool results (e.g. [1], [2]). Only cite numbers "
    "that actually appeared in tool results — never invent citations. Output only "
    "the section body: no title heading, no preamble."
)
_CAPPED_SYSTEM = (
    "You are a research worker for an autonomous research agent. The run's cost "
    "ceiling has been reached, so you have NO tools available. Draft the section "
    "body in Markdown from your own knowledge. Do not fabricate citations or "
    "sources. Output only the section body: no title heading, no preamble."
)
_REVISION_SYSTEM = (
    "You are a research worker revising a section for an autonomous research agent. "
    "You are given your previous draft and the reviewer's feedback. Produce an "
    "improved draft that addresses every point of feedback. You may call the "
    "available tools again to fill gaps. Keep valid [n] citation markers that refer "
    "to numbers shown in tool results; only cite numbers that appeared. Output only "
    "the section body: no title heading, no preamble."
)


def _snippet(text: str) -> str:
    """Our own ≤300-char summary of tool content (never a long verbatim quote, §5)."""
    collapsed = " ".join(text.split())
    return collapsed[:_SNIPPET_CHARS]


def _register(
    key: str, source: Source, sources: list[Source], seen: dict[str, int]
) -> int:
    """Return the 1-based citation index for ``key``, appending ``source`` if new."""
    if key in seen:
        return seen[key]
    idx = len(sources) + 1
    sources.append(source)
    seen[key] = idx
    return idx


def _collect(
    tool_name: str,
    args: dict[str, Any],
    result: Any,
    sources: list[Source],
    seen: dict[str, int],
) -> str:
    """Fold a tool result into ``sources`` and return ToolMessage content with [n]s."""
    source_tool = TOOL_NAME_TO_SOURCE_TOOL.get(tool_name, "web_search")

    if source_tool == "calculator":
        expr = str(args.get("expression", "")).strip()
        value = str(result)
        idx = _register(
            f"calc:{expr}",
            Source(
                url="",
                title="Calculator",
                snippet=_snippet(f"{expr} = {value}"),
                tool="calculator",
            ),
            sources,
            seen,
        )
        return f"[{idx}] {expr} = {value}"

    items = result if isinstance(result, list) else []
    if not items:
        return "No results."
    lines: list[str] = []
    for r in items:
        url = str(r.get("url", ""))
        title = str(r.get("title", ""))
        content = str(r.get("content", ""))
        key = url or f"{source_tool}:{title}"
        idx = _register(
            key,
            Source(
                url=url,
                title=title,
                snippet=_snippet(content),
                tool=cast(Any, source_tool),
            ),
            sources,
            seen,
        )
        lines.append(f"[{idx}] {title} ({url})\n{content}")
    return "\n\n".join(lines)


def _build_messages(
    section: SectionPlan, topic: str, payload: dict[str, Any], cost_capped: bool
) -> list[Any]:
    """First-draft, cost-capped, or revision prompt depending on the payload."""
    feedback = payload.get("feedback")
    previous_draft = payload.get("previous_draft")
    section_brief = (
        f"Research topic: {topic}\n\n"
        f"Section: {section.title}\n"
        f"Objective: {section.objective}\n"
        f"Suggested queries: {', '.join(section.suggested_queries)}"
    )

    if feedback and previous_draft is not None:
        prev_content = getattr(previous_draft, "content_md", "")
        human = (
            f"{section_brief}\n\n"
            f"--- Your previous draft ---\n{prev_content}\n\n"
            f"--- Reviewer feedback ---\n{feedback}\n\n"
            "Revise the section to address the feedback."
        )
        return [SystemMessage(_REVISION_SYSTEM), HumanMessage(human)]

    system = _CAPPED_SYSTEM if cost_capped else _FIRST_SYSTEM
    return [SystemMessage(system), HumanMessage(f"{section_brief}\n\nWrite the section.")]


def _last_text(messages: list[Any]) -> str:
    """Text content of the last AIMessage, if any."""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and isinstance(msg.content, str) and msg.content.strip():
            return msg.content
    return ""


def _finalize_body(content: str, cost_capped: bool, has_sources: bool) -> str:
    """Apply the cost-ceiling flag / source-gap note to the section body."""
    body = content.strip() or _FALLBACK_BODY
    if cost_capped:
        return f"{_COST_NOTE}\n\n{body}"
    if not has_sources:
        return f"{body}\n\n{_GAP_NOTE}"
    return body


def worker(payload: dict[str, Any]) -> dict[str, Any]:
    """Research one section and return a single ``SectionDraft``.

    Deterministic and side-effect-free before producing the draft (safe to re-run
    from the top on resume). All model calls go through the router and log usage.
    """
    section: SectionPlan = payload["section"]
    topic: str = payload["topic"]

    accrued = sum(e.cost_usd for e in payload.get("usage_log", []))
    cost_capped = accrued >= RUN_COST_CEILING_USD

    tools = get_worker_tools()
    tools_by_name = {t.name: t for t in tools}

    base = get_model("worker")
    model = base if cost_capped else base.bind_tools(tools)

    messages = _build_messages(section, topic, payload, cost_capped)
    usage: list[UsageEvent] = []
    sources: list[Source] = []
    seen: dict[str, int] = {}
    calls = 0

    while True:
        ai = cast(AIMessage, model.invoke(messages))
        usage.append(track_usage("worker", ai))
        messages.append(ai)

        tool_calls = ai.tool_calls or []
        if cost_capped or not tool_calls or calls >= MAX_TOOL_CALLS_PER_WORKER:
            break

        for tc in tool_calls:
            if calls >= MAX_TOOL_CALLS_PER_WORKER:
                break
            calls += 1
            tool = tools_by_name.get(tc["name"])
            if tool is None:
                messages.append(
                    ToolMessage(content="Unknown tool.", tool_call_id=tc["id"])
                )
                continue
            result = tool.invoke(tc["args"])
            tm_content = _collect(tc["name"], tc["args"], result, sources, seen)
            messages.append(ToolMessage(content=tm_content, tool_call_id=tc["id"]))

    content = _last_text(messages)
    if not content:
        # The loop stopped on the tool-call budget with no prose answer — force one
        # final, tool-free answer so a draft is always produced.
        forced = cast(AIMessage, base.invoke(messages + [HumanMessage(
            "Write the section now using the sources gathered above."
        )]))
        usage.append(track_usage("worker", forced))
        content = forced.content if isinstance(forced.content, str) else ""

    previous_draft = payload.get("previous_draft")
    revision = (getattr(previous_draft, "revision", -1) + 1) if previous_draft is not None else 0

    draft = SectionDraft(
        section_id=section.id,
        content_md=_finalize_body(content, cost_capped, has_sources=bool(sources)),
        sources=sources,
        revision=revision,
    )
    # NOTE: intentionally does not write `status`. It is a scalar (LastValue)
    # channel per §5, so N parallel workers writing it would be an illegal
    # concurrent update. `status` is owned by single-writer nodes (planner/writer);
    # only the reduced channels (drafts, usage_log) are written here.
    return {"drafts": [draft], "usage_log": usage}
