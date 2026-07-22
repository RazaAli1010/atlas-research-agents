"""ResearchState graph state — single source of truth (SHARED CONTEXT §5).

All features use these exact field names and constants. No feature may add or
rename a state field without updating §5 first.
"""

import operator
from typing import Annotated, Literal

from pydantic import BaseModel, field_validator
from typing_extensions import TypedDict

# --- Hard limits (SHARED CONTEXT §5) ---
MAX_SECTIONS = 6
MAX_REVISIONS_PER_SECTION = 2
MAX_TOOL_CALLS_PER_WORKER = 8
RUN_COST_CEILING_USD = 1.50
MAX_SNIPPET_CHARS = 300


class Source(BaseModel):
    url: str
    title: str
    snippet: str  # <=300 chars, our own summary — never long verbatim quotes
    tool: Literal["web_search", "rag", "calculator"]

    @field_validator("snippet")
    @classmethod
    def _clamp_snippet(cls, v: str) -> str:
        """Structurally enforce the ≤300-char summary bound on every Source (§5)."""
        return v[:MAX_SNIPPET_CHARS]


class SectionPlan(BaseModel):
    id: str  # "s1", "s2", ...
    title: str
    objective: str  # what this section must answer
    suggested_queries: list[str]


class SectionDraft(BaseModel):
    section_id: str
    content_md: str  # markdown with [n] citation markers
    sources: list[Source]
    revision: int  # 0 = first draft


class Review(BaseModel):
    section_id: str
    verdict: Literal["approved", "revise"]
    score: float  # 0-1
    feedback: str  # concrete revision instructions when verdict == "revise"


class UsageEvent(BaseModel):
    node: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


class ToolCallRecord(BaseModel):
    """One worker tool invocation (F8).

    The append-only ground truth of what tools actually returned this run: the
    anti-fabrication grader checks every cited source URL against the union of
    ``urls`` here, and trajectory stats count these grouped by ``section_id``.
    """

    section_id: str
    tool: Literal["web_search", "rag", "calculator"]
    urls: list[str]  # URLs this call returned; [] for calculator / no results


class ResearchState(TypedDict):
    topic: str
    plan: list[SectionPlan]
    plan_approved: bool
    drafts: Annotated[list[SectionDraft], operator.add]  # reducer: append (parallel workers)
    reviews: Annotated[list[Review], operator.add]
    revision_counts: dict[str, int]  # section_id -> revisions used
    final_report_md: str
    usage_log: Annotated[list[UsageEvent], operator.add]
    # anti-fabrication ground truth + trajectory stats; append reducer like drafts (F8)
    tool_calls: Annotated[list[ToolCallRecord], operator.add]
    status: Literal[
        "planning",
        "awaiting_approval",
        "researching",
        "reviewing",
        "writing",
        "done",
        "failed",
    ]
