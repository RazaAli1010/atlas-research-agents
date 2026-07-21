"""Writer node — F3 mechanical merge of worker drafts into a cited report.

Deterministic, no LLM (narrative synthesis is a later feature). It merges the
per-section ``SectionDraft``s in plan order, builds a single deduplicated numbered
source list, and remaps each section's local ``[n]`` markers to the global index so
every citation in the report resolves to an entry in the closing ``## Sources``
list.
"""

import re

from app.graph.state import ResearchState, SectionDraft, SectionPlan, Source

_CITATION_RE = re.compile(r"\[(\d+)\]")


def _source_key(source: Source) -> str:
    """Dedup key: URL for web/rag sources, the snippet for calculator sources."""
    return source.url or f"{source.tool}:{source.snippet}"


def _best_drafts(drafts: list[SectionDraft]) -> dict[str, SectionDraft]:
    """Highest-revision draft per section id (a revised section supersedes its earlier draft)."""
    best: dict[str, SectionDraft] = {}
    for draft in drafts:
        current = best.get(draft.section_id)
        if current is None or draft.revision > current.revision:
            best[draft.section_id] = draft
    return best


def merge_drafts(
    plan: list[SectionPlan], drafts: list[SectionDraft]
) -> tuple[str, list[Source]]:
    """Merge drafts in plan order into report Markdown + a deduplicated source list.

    Local ``[n]`` markers (1-based into each draft's own ``sources``) are remapped
    to global 1-based indices into the returned source list.
    """
    by_section = _best_drafts(drafts)

    global_sources: list[Source] = []
    global_index: dict[str, int] = {}

    def _global_idx(source: Source) -> int:
        key = _source_key(source)
        if key not in global_index:
            global_sources.append(source)
            global_index[key] = len(global_sources)
        return global_index[key]

    lines: list[str] = []
    for i, section in enumerate(plan, start=1):
        lines.append(f"## {i}. {section.title}")
        draft = by_section.get(section.id)
        if draft is None:
            lines.append("_No draft was produced for this section._")
            lines.append("")
            continue

        # Map this draft's local index -> global index, then rewrite [n] markers.
        local_to_global = {
            local: _global_idx(src) for local, src in enumerate(draft.sources, start=1)
        }

        def _remap(match: re.Match[str], mapping: dict[int, int] = local_to_global) -> str:
            local = int(match.group(1))
            return f"[{mapping[local]}]" if local in mapping else match.group(0)

        lines.append(_CITATION_RE.sub(_remap, draft.content_md))
        lines.append("")

    lines.append("## Sources")
    if global_sources:
        for n, source in enumerate(global_sources, start=1):
            if source.tool == "calculator":
                lines.append(f"{n}. {source.snippet} _(calculator)_")
            elif source.url:
                lines.append(f"{n}. [{source.title or source.url}]({source.url})")
            else:
                lines.append(f"{n}. {source.title or source.snippet}")
    else:
        lines.append("_No sources were cited._")

    return "\n".join(lines).rstrip() + "\n", global_sources


def writer(state: ResearchState) -> dict:
    """Merge drafts into ``final_report_md`` with a deduplicated numbered source list."""
    topic = state["topic"]
    plan = state.get("plan") or []
    drafts = state.get("drafts") or []

    body, _sources = merge_drafts(plan, drafts)
    report = f"# {topic}\n\n{body}"
    return {"final_report_md": report, "status": "done"}
