"""select_topics is deterministic given the same flags (F8, AC-1)."""

from evals.run_benchmark import BenchmarkTopic, load_topics, select_topics


def _fake_topics() -> list[BenchmarkTopic]:
    return [
        BenchmarkTopic(topic=f"Topic {i}", category=cat, must_cover=["a", "b", "c"])
        for cat in ("tech_comparison", "market_overview")
        for i in range(10)
    ]


def test_same_flags_same_selection() -> None:
    topics = _fake_topics()
    first = select_topics(topics, n=5, seed=42)
    second = select_topics(topics, n=5, seed=42)
    assert [t.topic for t in first] == [t.topic for t in second]


def test_different_seed_can_differ() -> None:
    topics = _fake_topics()
    a = [t.topic for t in select_topics(topics, n=5, seed=1)]
    b = [t.topic for t in select_topics(topics, n=5, seed=2)]
    assert a != b  # extremely unlikely to coincide across 20 topics


def test_category_filter_restricts_pool() -> None:
    topics = _fake_topics()
    selected = select_topics(topics, n=10, seed=42, category="market_overview")
    assert selected and all(t.category == "market_overview" for t in selected)


def test_n_larger_than_pool_returns_all() -> None:
    topics = _fake_topics()
    selected = select_topics(topics, n=999, seed=42, category="tech_comparison")
    assert len(selected) == 10  # 10 in that category, no error


def test_real_benchmark_file_loads_and_selects() -> None:
    topics = load_topics()
    selected = select_topics(topics, n=4, seed=7)
    assert len(selected) == 4
