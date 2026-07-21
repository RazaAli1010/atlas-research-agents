"""Reviewer node: grades each section's latest draft and drives self-correction (F4).

Runs after every worker wave fans in. For each section whose newest draft has not
yet been graded, it produces one ``Review`` via structured output (§2.7 — never
regex/``json.loads`` on prose), appends usage, and recomputes ``revision_counts``.

The reviewer NEVER decides the revision budget — that is the sole responsibility of
``routing.route_after_review`` (single budget gate = termination proof). Here
``revision_counts[sid]`` is defined as *revisions produced so far* = the section's
highest draft ``revision`` (0 = only the original draft). It is a pure function of
``drafts``, so the node is safe to re-execute.

Verdict is normalized server-side from the score (``score < 0.7`` ⇒ ``revise``) so
the rubric is deterministic regardless of what the model puts in its ``verdict``
field; feedback is guaranteed non-empty on a ``revise``.
"""

from typing import Any, cast

from langchain_core.messages import AIMessage

from app.graph.state import ResearchState, Review, SectionDraft, Source
from app.llm.router import get_model, track_usage

_SCORE_THRESHOLD = 0.7
_REVISE_FALLBACK = (
    "The section does not yet meet the quality bar. Improve objective coverage, "
    "ensure every factual claim carries a [n] citation that resolves to a listed "
    "source, and tighten coherence."
)

_REVIEW_SYSTEM = (
    "You are the reviewer for an autonomous research agent. Grade the draft section "
    "against its objective using this rubric: (a) objective coverage — does it fully "
    "answer what the section must answer; (b) citations — is every factual claim "
    "backed by a [n] marker; (c) sourcing — do all cited [n] markers resolve to an "
    "entry in the provided sources list (no fabricated or dangling citations); "
    "(d) coherence — is it well-structured and readable. Return a score in [0,1] "
    "(1 = excellent), a verdict, and, when the draft needs work, concrete and "
    "actionable revision feedback naming exactly what to fix. Score below 0.7 means "
    "the section must be revised."
)


def _by_section(items: list[Any]) -> dict[str, list[Any]]:
    """Group drafts or reviews by ``section_id`` in insertion order."""
    grouped: dict[str, list[Any]] = {}
    for item in items:
        grouped.setdefault(item.section_id, []).append(item)
    return grouped


def _latest(drafts: list[SectionDraft]) -> SectionDraft:
    """Highest-``revision`` draft in a per-section list."""
    return max(drafts, key=lambda d: d.revision)


def _render_sources(sources: list[Source]) -> str:
    """Number the draft's sources so the reviewer can check [n] markers resolve."""
    if not sources:
        return "(none)"
    return "\n".join(
        f"[{i}] {s.title or s.url or s.snippet} ({s.tool}) {s.url}".rstrip()
        for i, s in enumerate(sources, start=1)
    )


def _brief(objective: str, draft: SectionDraft) -> str:
    return (
        f"Section objective: {objective}\n\n"
        f"--- Draft (revision {draft.revision}) ---\n{draft.content_md}\n\n"
        f"--- Sources cited by [n] markers ---\n{_render_sources(draft.sources)}\n\n"
        "Grade this draft."
    )


def reviewer(state: ResearchState) -> dict:
    """Grade every unreviewed latest draft and recompute the revision counter."""
    drafts_by_section = _by_section(state.get("drafts", []))
    reviews_by_section = _by_section(state.get("reviews", []))
    objectives = {section.id: section.objective for section in state.get("plan", [])}

    model = get_model("reviewer").with_structured_output(Review, include_raw=True)

    new_reviews: list[Review] = []
    usage = []
    for sid, drafts in drafts_by_section.items():
        # A section needs grading iff its newest draft has not been reviewed yet.
        if len(drafts) <= len(reviews_by_section.get(sid, [])):
            continue

        draft = _latest(drafts)
        result = cast(
            dict[str, Any],
            model.invoke(
                [
                    ("system", _REVIEW_SYSTEM),
                    ("human", _brief(objectives.get(sid, ""), draft)),
                ]
            ),
        )
        parsed: Review = result["parsed"]
        raw: AIMessage = result["raw"]

        score = min(max(parsed.score, 0.0), 1.0)
        verdict = "approved" if score >= _SCORE_THRESHOLD else "revise"
        feedback = parsed.feedback.strip()
        if verdict == "revise" and not feedback:
            feedback = _REVISE_FALLBACK

        new_reviews.append(
            Review(section_id=sid, verdict=verdict, score=score, feedback=feedback)
        )
        usage.append(track_usage("reviewer", raw))

    # revision_counts = revisions produced so far per section (= highest draft
    # revision). Pure function of drafts; the budget gate lives in routing.
    revision_counts = {
        sid: max(d.revision for d in drafts) for sid, drafts in drafts_by_section.items()
    }

    return {
        "reviews": new_reviews,
        "usage_log": usage,
        "revision_counts": revision_counts,
        "status": "reviewing",
    }
