"""Writer node — F7 analyst-grade report assembly.

The writer picks the best draft per section (F3 selection logic, unchanged), then:

1. **Merges** section bodies in plan order, remapping each worker's *local* ``[n]``
   markers to a single deduplicated global source list; markers that do not resolve
   to one of the draft's own sources are *stripped* (never passed through, so a
   hallucinated ``[9]`` can neither dangle nor collide with a valid global index).
2. **Summarizes** — an LLM (via ``get_model("writer")``) writes a ≤150-word executive
   summary of the merged research. This is the only non-deterministic step and the
   one that lights up the F6 writer ``token`` SSE stream.
3. **Validates** — a post-write pass asserts every ``[n]`` in the summary + section
   bodies is in ``1..len(sources)``; any that are not are stripped and counted.
4. **Assembles** the fixed structure contract: ``# {topic}`` → ``## Executive summary``
   → numbered sections → ``## Limitations`` (always present; ``None.`` when empty) →
   ``## Sources``. Removed markers and budget-exhausted sections are reported in
   *Limitations*.
"""

import re
from typing import Any, cast

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.graph.state import (
    MAX_REVISIONS_PER_SECTION,
    ResearchState,
    Review,
    SectionDraft,
    SectionPlan,
    Source,
    UsageEvent,
)
from app.llm.router import get_model, track_usage

_SUMMARY_WORD_LIMIT = 150

_WRITER_SYSTEM = (
    "You are the writer for an autonomous research agent. Write a tight executive "
    "summary of the research below in at most 150 words. Plain prose, no headings, "
    "no bullet lists, and do NOT include any [n] citation markers. State the key "
    "findings and the bottom-line recommendation."
)

# Optional single leading space is captured (group 1) so a *kept* marker preserves its
# spacing while a *stripped* marker leaves no double space: "low [9]." -> "low.".
_CITATION_RE = re.compile(r"(\s?)\[(\d+)\]")


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


def merge_sections(
    plan: list[SectionPlan], drafts: list[SectionDraft]
) -> tuple[str, list[Source], int]:
    """Merge drafts in plan order into numbered section bodies + a deduped source list.

    Returns ``(sections_md, global_sources, stripped)``. Local ``[n]`` markers (1-based
    into each draft's own ``sources``) are remapped to global 1-based indices into the
    returned source list; a marker whose local index is not present in the draft's
    sources is *removed* and counted in ``stripped``. This function emits **only** the
    ``## {i}. {title}`` section bodies — the ``## Sources`` block is rendered by the
    assembler so it can sit after *Limitations*.
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

    stripped = 0
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
            nonlocal stripped
            ws, local = match.group(1), int(match.group(2))
            if local in mapping:
                return f"{ws}[{mapping[local]}]"
            stripped += 1
            return ""

        lines.append(_CITATION_RE.sub(_remap, draft.content_md))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n", global_sources, stripped


def _validate_markers(text: str, num_sources: int) -> tuple[str, int]:
    """Strip any ``[n]`` outside ``1..num_sources``; return ``(cleaned, stripped)``.

    Belt-and-suspenders over :func:`merge_sections` — also catches markers the LLM
    summary may have introduced. Guarantees zero dangling markers in the report.
    """
    stripped = 0

    def _check(match: re.Match[str]) -> str:
        nonlocal stripped
        ws, n = match.group(1), int(match.group(2))
        if 1 <= n <= num_sources:
            return f"{ws}[{n}]"
        stripped += 1
        return ""

    return _CITATION_RE.sub(_check, text), stripped


def _cap_words(text: str, limit: int = _SUMMARY_WORD_LIMIT) -> str:
    """Collapse whitespace and keep the first ``limit`` words (append ``…`` if cut)."""
    words = text.split()
    if len(words) <= limit:
        return " ".join(words)
    return " ".join(words[:limit]) + "…"  # attached, so the cap stays exactly `limit` words


def _executive_summary(
    topic: str, sections_md: str, model: Any
) -> tuple[str, UsageEvent]:
    """LLM-write a ≤150-word executive summary of the merged sections + usage."""
    ai = cast(
        AIMessage,
        model.invoke(
            [
                SystemMessage(_WRITER_SYSTEM),
                HumanMessage(f"Research topic: {topic}\n\n{sections_md}"),
            ]
        ),
    )
    content = ai.content if isinstance(ai.content, str) else ""
    return _cap_words(content), track_usage("writer", ai)


def _build_limitations(
    plan: list[SectionPlan], exhausted: set[str], stripped: int
) -> str:
    """Compose the *Limitations* body; ``"None."`` when there is nothing to report."""
    sentences: list[str] = []
    if exhausted:
        titles = ", ".join(s.title for s in plan if s.id in exhausted)
        sentences.append(
            "The following sections did not reach the reviewer's quality bar within "
            f"the revision budget: {titles}. Their best available drafts are included."
        )
    if stripped > 0:
        sentences.append(
            f"{stripped} citation marker(s) that did not resolve to a source were removed."
        )
    return " ".join(sentences) if sentences else "None."


def _render_sources(sources: list[Source]) -> str:
    """Render the numbered ``## Sources`` list body (global order)."""
    if not sources:
        return "_No sources were cited._"
    lines: list[str] = []
    for n, source in enumerate(sources, start=1):
        if source.tool == "calculator":
            lines.append(f"{n}. {source.snippet} _(calculator)_")
        elif source.url:
            lines.append(f"{n}. [{source.title or source.url}]({source.url})")
        else:
            lines.append(f"{n}. {source.title or source.snippet}")
    return "\n".join(lines)


def assemble_report(
    topic: str,
    summary_md: str,
    sections_md: str,
    limitations_md: str,
    sources: list[Source],
) -> str:
    """Assemble the fixed structure contract into a single Markdown document."""
    parts = [
        f"# {topic}",
        "",
        "## Executive summary",
        "",
        summary_md,
        "",
        sections_md.rstrip(),
        "",
        "## Limitations",
        "",
        limitations_md,
        "",
        "## Sources",
        "",
        _render_sources(sources),
    ]
    return "\n".join(parts).rstrip() + "\n"


def report_sources(
    plan: list[SectionPlan],
    drafts: list[SectionDraft],
    reviews: list[Review],
) -> list[Source]:
    """The report's global deduped source list; index ``i`` ↔ citation marker ``[i+1]``.

    Reuses the writer's own selection + merge so the list is identical to the one
    embedded in ``final_report_md`` (both derive from the same ``plan``/``drafts``/
    ``reviews``). Used by the API layer to expose ``RunDetail.sources`` (F12) without
    re-implementing dedup/numbering on the frontend.
    """
    chosen, _ = _select_drafts(plan, drafts, reviews)
    _, sources, _ = merge_sections(plan, chosen)
    return sources


def writer(state: ResearchState) -> dict:
    """Assemble ``final_report_md`` from the selected per-section drafts.

    Deterministic except for the LLM executive summary. Prefers each section's
    highest-revision approved draft (else best-scoring); reports budget-exhausted
    sections and any stripped citation markers under *Limitations*. The source list
    is deduplicated and numbered, and every ``[n]`` in the output resolves.
    """
    topic = state["topic"]
    plan = state.get("plan") or []
    drafts = state.get("drafts") or []
    reviews = state.get("reviews") or []

    chosen, exhausted = _select_drafts(plan, drafts, reviews)
    sections_md, sources, stripped = merge_sections(plan, chosen)

    summary_md, usage = _executive_summary(topic, sections_md, get_model("writer"))

    # Post-write validation: no [n] may fall outside the global source range.
    summary_md, s_sum = _validate_markers(summary_md, len(sources))
    sections_md, s_sec = _validate_markers(sections_md, len(sources))
    stripped += s_sum + s_sec

    limitations_md = _build_limitations(plan, exhausted, stripped)
    report = assemble_report(topic, summary_md, sections_md, limitations_md, sources)
    return {"final_report_md": report, "status": "done", "usage_log": [usage]}
