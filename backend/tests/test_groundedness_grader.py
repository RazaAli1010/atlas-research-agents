"""groundedness_grader samples cited claims and checks support (F8, AC-1 sampling)."""

from app.graph.state import SectionDraft, Source, ToolCallRecord
from evals.graders import ClaimGrounded, groundedness_grader
from tests.eval_helpers import make_run
from tests.fakes import FakeJudge


def _draft_with_n_claims(n: int) -> SectionDraft:
    body = " ".join(f"Fact number {k} holds [1]." for k in range(n))
    src = Source(url="https://a.com", title="A", snippet="Supporting evidence.", tool="web_search")
    return SectionDraft(section_id="s1", content_md=body, sources=[src], revision=0)


def test_score_is_fraction_supported() -> None:
    run = make_run(drafts=[_draft_with_n_claims(5)])
    supported = ClaimGrounded(supported=True, reason="r")
    unsupported = ClaimGrounded(supported=False, reason="r")
    judge = FakeJudge([supported] * 4 + [unsupported])
    result = groundedness_grader(run, judge=judge)
    assert result.score == 0.8  # 4/5
    assert result.passed is True


def test_no_citable_claims_fails() -> None:
    plain = SectionDraft(section_id="s1", content_md="No citations here.", sources=[], revision=0)
    result = groundedness_grader(make_run(drafts=[plain]), judge=FakeJudge([]))
    assert result.score == 0.0
    assert result.passed is False
    assert "no citable claims" in result.detail


def test_judges_against_full_tool_content_not_clamped_snippet() -> None:
    # The worker read a long source; the stored snippet is clamped to 300 chars, so the
    # supporting fact falls past the truncation. The grader must judge against the full
    # tool-result content (from tool_calls), not the snippet.
    full = "Datadog lists at $15 per host per month on the Pro plan. " + "padding. " * 60
    src = Source(url="https://a.com", title="A", snippet=full, tool="web_search")
    draft = SectionDraft(
        section_id="s1",
        content_md="Datadog Pro is $15 per host per month [1].",
        sources=[src],
        revision=0,
    )
    tool_calls = [
        ToolCallRecord(
            section_id="s1",
            tool="web_search",
            urls=["https://a.com"],
            contents={"https://a.com": full},
        )
    ]
    run = make_run(drafts=[draft], tool_calls=tool_calls)
    judge = FakeJudge([ClaimGrounded(supported=True, reason="r")])

    result = groundedness_grader(run, judge=judge)

    assert result.passed is True
    assert src.snippet != full  # snippet really was truncated by the 300-char clamp
    assert full in judge.seen[0]  # the judge saw the full evidence, not the snippet


def test_multi_marker_claim_shows_all_cited_sources() -> None:
    # A sentence citing [1][2] must be judged against BOTH sources, not just the first.
    src1 = Source(url="https://a.com", title="A", snippet="s1", tool="web_search")
    src2 = Source(url="https://b.com", title="B", snippet="s2", tool="web_search")
    draft = SectionDraft(
        section_id="s1",
        content_md="Kafka sustains higher throughput than RabbitMQ [1][2].",
        sources=[src1, src2],
        revision=0,
    )
    tool_calls = [
        ToolCallRecord(
            section_id="s1",
            tool="web_search",
            urls=["https://a.com", "https://b.com"],
            contents={
                "https://a.com": "Kafka is a log-based broker.",
                "https://b.com": "Benchmarks show Kafka's higher throughput.",
            },
        )
    ]
    run = make_run(drafts=[draft], tool_calls=tool_calls)
    judge = FakeJudge([ClaimGrounded(supported=True, reason="r")])

    groundedness_grader(run, judge=judge)

    assert "Kafka is a log-based broker." in judge.seen[0]
    assert "Benchmarks show Kafka's higher throughput." in judge.seen[0]


def test_seeded_sampling_is_reproducible() -> None:
    # 8 claims but only 5 sampled — the selection must be identical for the same seed.
    run = make_run(drafts=[_draft_with_n_claims(8)], seed=42)
    always_true = [ClaimGrounded(supported=True, reason="r")] * 8

    j1 = FakeJudge(list(always_true))
    j2 = FakeJudge(list(always_true))
    groundedness_grader(run, judge=j1)
    groundedness_grader(run, judge=j2)

    assert j1.seen == j2.seen  # same claims, same order
    assert len(j1.seen) == 5
