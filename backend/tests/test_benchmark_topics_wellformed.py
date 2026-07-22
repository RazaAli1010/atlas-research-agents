"""benchmark_topics.jsonl is well-formed: 40 rows, 10 per category (F8)."""

from collections import Counter

from evals.run_benchmark import CATEGORIES, load_topics


def test_forty_topics_ten_per_category() -> None:
    topics = load_topics()
    assert len(topics) == 40
    by_cat = Counter(t.category for t in topics)
    assert set(by_cat) == set(CATEGORIES)
    assert all(by_cat[c] == 10 for c in CATEGORIES)


def test_every_topic_has_3_to_5_cover_points() -> None:
    for t in load_topics():
        assert t.topic.strip(), "empty topic"
        assert t.category in CATEGORIES, f"bad category {t.category!r}"
        assert 3 <= len(t.must_cover) <= 5, f"{t.topic!r} has {len(t.must_cover)} must_cover points"
        assert all(p.strip() for p in t.must_cover)
