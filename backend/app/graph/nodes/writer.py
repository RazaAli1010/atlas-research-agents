"""Writer node — F2 stub: renders the plan as a Markdown outline.

The real writer (LLM synthesis of approved drafts with a deduplicated numbered
source list) arrives in F5. This stub proves the graph reaches ``writer`` and
populates ``final_report_md``. It already folds in any ``drafts`` so the shape is
forward-compatible, though F2 produces none.
"""

from app.graph.state import ResearchState


def writer(state: ResearchState) -> dict:
    """Concatenate the plan (and any drafts) into ``final_report_md``."""
    topic = state["topic"]
    drafts_by_section = {d.section_id: d for d in state.get("drafts") or []}

    lines: list[str] = [f"# {topic}", ""]
    for i, section in enumerate(state.get("plan") or [], start=1):
        lines.append(f"## {i}. {section.title}")
        lines.append(section.objective)
        draft = drafts_by_section.get(section.id)
        if draft is not None:
            lines.append("")
            lines.append(draft.content_md)
        lines.append("")

    return {"final_report_md": "\n".join(lines).rstrip() + "\n", "status": "done"}
