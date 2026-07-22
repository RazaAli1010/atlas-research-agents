"""Grader library for the F8 evaluation harness.

Two programmatic graders (``structure``, ``citation``) and two LLM-as-judge graders
(``coverage``, ``groundedness``), each returning a uniform :class:`GraderResult`. The
fixed success rule (:func:`is_success`) — structure AND citation pass, coverage ≥ 0.8,
groundedness ≥ 0.8 — and ``GRADER_ORDER`` (which drives the failure-taxonomy table)
live here so the harness never re-implements them.

The LLM graders take an optional pre-built ``judge`` model (so the harness can thread a
cheap ``--smoke`` model through, and tests can pass a scripted fake); when omitted they
build the strong judge via :func:`evals.judge.get_judge_model`.
"""

from __future__ import annotations

import random
import re
from typing import cast

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel

from app.graph.state import (
    Review,
    SectionDraft,
    SectionPlan,
    ToolCallRecord,
    UsageEvent,
)
from evals.judge import get_judge_model

# Writer's placeholder for a section that produced no draft (writer.py) — exempt from
# the "≥1 source per section" citation check (there is no research to cite).
_NO_DRAFT_MARKER = "_No draft was produced for this section._"

_HEADING_RE = re.compile(r"^(#{1,2} .+)$", re.MULTILINE)
_MARKER_RE = re.compile(r"\[(\d+)\]")
_SOURCE_ITEM_RE = re.compile(r"^\d+\. ", re.MULTILINE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

GRADER_ORDER = ["structure", "citation", "coverage", "groundedness"]

_GROUNDEDNESS_SAMPLE = 5
_PASS_THRESHOLD = 0.8


class GraderResult(BaseModel):
    name: str
    passed: bool
    score: float  # 0..1
    detail: str


class EvalRun(BaseModel):
    """Everything a grader may read, assembled from one run's final graph state."""

    topic: str
    category: str
    must_cover: list[str]
    report_md: str
    plan: list[SectionPlan]
    drafts: list[SectionDraft]
    reviews: list[Review]
    revision_counts: dict[str, int]
    usage_log: list[UsageEvent]
    tool_calls: list[ToolCallRecord]
    wall_time_s: float
    seed: int  # per-run seed for reproducible grader sampling


# --- LLM-judge structured-output schemas -------------------------------------------


class CoverageVerdict(BaseModel):
    covered: list[bool]  # one flag per must_cover point, in order
    notes: str


class ClaimGrounded(BaseModel):
    supported: bool
    reason: str


# --- programmatic graders -----------------------------------------------------------


def structure_grader(run: EvalRun) -> GraderResult:
    """Report obeys the F7 structure contract: H1 → Exec summary → numbered sections
    → Limitations → Sources, in order, the three fixed headings once each."""
    headings = _HEADING_RE.findall(run.report_md)
    problems: list[str] = []

    if not headings or not headings[0].startswith("# "):
        problems.append("missing H1 title as first heading")

    for fixed in ("## Executive summary", "## Limitations", "## Sources"):
        if headings.count(fixed) != 1:
            problems.append(f"{fixed!r} must appear exactly once")

    # Only check ordering when the fixed anchors are each present exactly once.
    if not problems or all("appear exactly once" not in p for p in problems):
        i_exec = headings.index("## Executive summary")
        i_lim = headings.index("## Limitations")
        i_src = headings.index("## Sources")
        if i_exec != 1:
            problems.append("Executive summary must immediately follow the H1 title")
        if not i_exec < i_lim < i_src:
            problems.append("headings out of order (exec → limitations → sources)")
        if i_src != len(headings) - 1:
            problems.append("Sources must be the last heading")

        sections = headings[i_exec + 1 : i_lim]
        if not sections:
            problems.append("no numbered sections")
        for n, heading in enumerate(sections, start=1):
            if not re.match(rf"^## {n}\. .+", heading):
                problems.append(f"section {n} heading malformed: {heading!r}")

    passed = not problems
    return GraderResult(
        name="structure",
        passed=passed,
        score=1.0 if passed else 0.0,
        detail="ok" if passed else "; ".join(problems),
    )


def _section_bodies(md: str) -> list[tuple[str, str]]:
    """Split the report into (heading, body) pairs for each ``## n. title`` section."""
    pairs: list[tuple[str, str]] = []
    matches = list(re.finditer(r"^## \d+\. .+$", md, re.MULTILINE))
    for i, m in enumerate(matches):
        start = m.end()
        # Body runs up to the next section heading, else the next H2 (Limitations).
        next_start = (
            matches[i + 1].start()
            if i + 1 < len(matches)
            else _next_h2(md, start)
        )
        pairs.append((m.group(0), md[start:next_start]))
    return pairs


def _next_h2(md: str, start: int) -> int:
    """Offset of the next ``## `` heading after ``start`` (or end of string)."""
    m = re.search(r"^## .+$", md[start:], re.MULTILINE)
    return start + m.start() if m else len(md)


def citation_grader(run: EvalRun) -> GraderResult:
    """No dangling markers, ≥1 source per real section, and no fabricated source URLs."""
    md = run.report_md
    failures: list[str] = []

    # (a) no dangling markers: every [n] in the BODY resolves into the numbered Sources
    # list. Scan only the region *before* "## Sources": that list uses [title](url) link
    # syntax and a source title may itself contain a bracketed number (e.g. a year like
    # [2026]), which is not a citation marker and must not be counted as dangling.
    src_start = md.find("## Sources")
    body_region = md[:src_start] if src_start != -1 else md
    n_sources = len(_SOURCE_ITEM_RE.findall(md[src_start:])) if src_start != -1 else 0
    dangling = sorted(
        {int(n) for n in _MARKER_RE.findall(body_region) if not 1 <= int(n) <= n_sources}
    )
    if dangling:
        failures.append(f"dangling markers {dangling} (only {n_sources} sources)")

    # (b) ≥1 source per section that has a real draft.
    uncited = [
        heading
        for heading, body in _section_bodies(md)
        if _NO_DRAFT_MARKER not in body and not _MARKER_RE.search(body)
    ]
    if uncited:
        failures.append(f"sections with no citation: {uncited}")

    # (c) anti-fabrication: every cited web/rag URL appeared in an actual tool result.
    ground = {u for r in run.tool_calls for u in r.urls}
    fabricated = sorted(
        {
            s.url
            for d in run.drafts
            for s in d.sources
            if s.tool in ("web_search", "rag") and s.url and s.url not in ground
        }
    )
    if fabricated:
        failures.append(f"fabricated source URLs (absent from tool results): {fabricated}")

    passed = not failures
    score = (3 - len(failures)) / 3
    return GraderResult(
        name="citation",
        passed=passed,
        score=score,
        detail="ok" if passed else "; ".join(failures),
    )


# --- LLM-judge graders --------------------------------------------------------------

_COVERAGE_SYSTEM = (
    "You are an evaluation judge. You are given a research report and a list of key "
    "points a good report on this topic MUST address. For each point, decide whether "
    "the report substantively addresses it (true) or not (false). Return one boolean "
    "per point, in the same order, plus brief notes."
)

_GROUNDEDNESS_SYSTEM = (
    "You are an evaluation judge checking for hallucination. You are given a CLAIM "
    "from a research report and the SOURCE MATERIAL it cites (the full text of the "
    "cited source(s)). Decide whether the source material supports the claim (true) "
    "or not (false), and give a brief reason. Judge only against the material "
    "provided — do not use outside knowledge."
)


def coverage_grader(run: EvalRun, judge: BaseChatModel | None = None) -> GraderResult:
    """Fraction of ``must_cover`` points the report addresses (LLM judge). Pass ≥ 0.8."""
    if not run.must_cover:
        return GraderResult(name="coverage", passed=True, score=1.0, detail="no points to cover")

    model = (judge or get_judge_model()).with_structured_output(CoverageVerdict)
    points = "\n".join(f"{i}. {p}" for i, p in enumerate(run.must_cover, start=1))
    verdict = cast(
        CoverageVerdict,
        model.invoke(
            [
                ("system", _COVERAGE_SYSTEM),
                ("human", f"--- Report ---\n{run.report_md}\n\n--- Points ---\n{points}"),
            ]
        ),
    )
    # Defensive: align the judge's list length to the number of points.
    covered = (verdict.covered + [False] * len(run.must_cover))[: len(run.must_cover)]
    score = sum(covered) / len(run.must_cover)
    return GraderResult(
        name="coverage",
        passed=score >= _PASS_THRESHOLD,
        score=score,
        detail=f"{sum(covered)}/{len(run.must_cover)} points covered",
    )


def _url_to_content(tool_calls: list[ToolCallRecord]) -> dict[str, str]:
    """Fold every tool call's ``contents`` into a single url -> full-text map.

    This is the un-truncated evidence the worker actually read. When the same URL is
    returned by more than one call, keep the longest text (most complete evidence).
    """
    mapping: dict[str, str] = {}
    for record in tool_calls:
        for url, content in record.contents.items():
            if content and len(content) > len(mapping.get(url, "")):
                mapping[url] = content
    return mapping


def _citable_claims(
    drafts: list[SectionDraft], url_to_content: dict[str, str]
) -> list[tuple[str, str]]:
    """(claim sentence, supporting evidence) pairs across all drafts.

    A claim is a sentence carrying ≥1 ``[n]`` marker; its evidence is the full
    tool-result content of *every* source it cites that resolves into the draft's own
    sources (all markers, not just the first — a sentence citing ``[3][7]`` is judged
    against both). Falls back to the stored 300-char snippet when full content is
    unavailable for that source (e.g. a calculator result, which has no URL).
    """
    claims: list[tuple[str, str]] = []
    for draft in drafts:
        for sentence in _SENTENCE_SPLIT_RE.split(draft.content_md):
            evidence: list[str] = []
            seen: set[int] = set()
            for n in (int(x) for x in _MARKER_RE.findall(sentence)):
                if 1 <= n <= len(draft.sources) and n not in seen:
                    seen.add(n)
                    src = draft.sources[n - 1]
                    full = url_to_content.get(src.url, "") if src.url else ""
                    evidence.append(full or src.snippet)
            if evidence:
                claims.append((sentence.strip(), "\n\n---\n\n".join(evidence)))
    return claims


def groundedness_grader(run: EvalRun, judge: BaseChatModel | None = None) -> GraderResult:
    """Sample ≤5 cited claims and check each is supported by its cited source(s).

    Judges against the full tool-result content the worker read (via ``tool_calls``),
    not the 300-char ``Source.snippet``, so support that fell past the snippet
    truncation is not counted as a hallucination. Pass ≥ 0.8.
    """
    claims = _citable_claims(run.drafts, _url_to_content(run.tool_calls))
    if not claims:
        return GraderResult(
            name="groundedness", passed=False, score=0.0, detail="no citable claims"
        )

    rng = random.Random(run.seed)
    sample = rng.sample(claims, min(_GROUNDEDNESS_SAMPLE, len(claims)))

    model = (judge or get_judge_model()).with_structured_output(ClaimGrounded)
    supported = 0
    for claim, evidence in sample:
        verdict = cast(
            ClaimGrounded,
            model.invoke(
                [
                    ("system", _GROUNDEDNESS_SYSTEM),
                    ("human", f"--- Claim ---\n{claim}\n\n--- Source material ---\n{evidence}"),
                ]
            ),
        )
        supported += int(verdict.supported)

    score = supported / len(sample)
    return GraderResult(
        name="groundedness",
        passed=score >= _PASS_THRESHOLD,
        score=score,
        detail=f"{supported}/{len(sample)} sampled claims grounded",
    )


# --- orchestration + success rule ---------------------------------------------------


def run_all_graders(run: EvalRun, judge: BaseChatModel | None = None) -> list[GraderResult]:
    """Run all four graders and return results in ``GRADER_ORDER``."""
    return [
        structure_grader(run),
        citation_grader(run),
        coverage_grader(run, judge),
        groundedness_grader(run, judge),
    ]


def is_success(results: list[GraderResult]) -> tuple[bool, str | None]:
    """Fixed success rule → ``(success, first_failing_grader | None)``.

    Success iff structure AND citation pass and coverage/groundedness score ≥ 0.8.
    ``first_failing`` is the earliest grader in ``GRADER_ORDER`` that fails.
    """
    by_name = {r.name: r for r in results}
    ok = {
        "structure": by_name["structure"].passed,
        "citation": by_name["citation"].passed,
        "coverage": by_name["coverage"].score >= _PASS_THRESHOLD,
        "groundedness": by_name["groundedness"].score >= _PASS_THRESHOLD,
    }
    for name in GRADER_ORDER:
        if not ok[name]:
            return False, name
    return True, None
