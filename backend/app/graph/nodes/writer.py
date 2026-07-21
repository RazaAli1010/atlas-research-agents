"""Writer node — F3 mechanical merge of worker drafts into a cited report.

Deterministic, no LLM (narrative synthesis is a later feature). It merges the
per-section ``SectionDraft``s in plan order, builds a single deduplicated numbered
source list, and remaps each section's local ``[n]`` markers to the global index so
every citation in the report resolves to an entry in the closing ``## Sources``
list.
"""

import re

from app.graph.state import (
    MAX_REVISIONS_PER_SECTION,
    ResearchState,
    Review,
    SectionDraft,
    SectionPlan,
    Source,
)

_LIMITATIONS_PREFIX = (
    "> **Limitations:** the following sections did not reach the reviewer's quality "
    "bar within the revision budget: {titles}. Their best available drafts are "
    "included below."
)

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


def _select_drafts(
    plan: list[SectionPlan],
    drafts: list[SectionDraft],
    reviews: list[Review],
) -> tuple[list[SectionDraft], set[str]]:
    """Pick the draft to publish per section and flag budget-exhausted sections.

    Reviews accrue in draft-revision order, so ``reviews_for[sid][k]`` pairs with the
    section's draft of ``revision == k``. Selection per section: the highest-revision
    draft with an ``approved`` paired review; else the draft whose paired review has
    the highest score; else (no reviews) the highest-revision draft.

    A section is *budget-exhausted-unapproved* when its latest review verdict is
    ``revise`` and it has already produced ``MAX_REVISIONS_PER_SECTION`` revisions
    (highest draft revision) — these get the Limitations note.
    """
    drafts_by_section: dict[str, list[SectionDraft]] = {}
    for draft in drafts:
        drafts_by_section.setdefault(draft.section_id, []).append(draft)

    reviews_by_section: dict[str, list[Review]] = {}
    for review in reviews:
        reviews_by_section.setdefault(review.section_id, []).append(review)

    chosen: list[SectionDraft] = []
    exhausted: set[str] = set()
    for section in plan:
        sec_drafts = sorted(
            drafts_by_section.get(section.id, []), key=lambda d: d.revision
        )
        if not sec_drafts:
            continue
        sec_reviews = reviews_by_section.get(section.id, [])

        approved_idx = [
            k
            for k, r in enumerate(sec_reviews)
            if r.verdict == "approved" and k < len(sec_drafts)
        ]
        if approved_idx:
            pick = sec_drafts[max(approved_idx)]  # highest-revision approved
        elif sec_reviews:
            best_k = max(range(len(sec_reviews)), key=lambda k: sec_reviews[k].score)
            pick = sec_drafts[min(best_k, len(sec_drafts) - 1)]  # best-scoring
        else:
            pick = sec_drafts[-1]  # highest revision, ungraded
        chosen.append(pick)

        # A limitation only when we are publishing a non-approved draft: no review
        # ever approved the section, its latest verdict is still revise, and it has
        # spent its full revision budget.
        if (
            not approved_idx
            and sec_reviews
            and sec_reviews[-1].verdict == "revise"
            and sec_drafts[-1].revision >= MAX_REVISIONS_PER_SECTION
        ):
            exhausted.add(section.id)

    return chosen, exhausted


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
    """Merge the selected per-section drafts into ``final_report_md``.

    Prefers each section's highest-revision approved draft (else best-scoring), and
    prepends a *Limitations* note when any section exhausted its revision budget
    without approval. The source list is deduplicated and numbered.
    """
    topic = state["topic"]
    plan = state.get("plan") or []
    drafts = state.get("drafts") or []
    reviews = state.get("reviews") or []

    chosen, exhausted = _select_drafts(plan, drafts, reviews)
    body, _sources = merge_drafts(plan, chosen)

    report = f"# {topic}\n\n"
    if exhausted:
        titles = ", ".join(s.title for s in plan if s.id in exhausted)
        report += _LIMITATIONS_PREFIX.format(titles=titles) + "\n\n"
    report += body
    return {"final_report_md": report, "status": "done"}
