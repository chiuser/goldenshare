from __future__ import annotations

from datetime import date, datetime, timezone

from src.biz.services.wealth.news_intelligence.contracts import (
    ImportanceDimension,
    NewsSourceType,
)
from src.biz.services.wealth.news_intelligence.evaluation import (
    candidate_recall,
    classification_metrics,
    krippendorff_alpha_nominal,
    pairwise_clustering_metrics,
    ranking_metrics,
    summary_audit_metrics,
)
from src.biz.services.wealth.news_intelligence.ranking import (
    delivery_candidates,
    rank_events,
)
from src.biz.services.wealth.news_intelligence.replay import (
    clean_candidate,
    freeze_news_item,
)
from src.biz.services.wealth.news_intelligence.sampling import (
    select_formal_calibration_set,
    select_taxonomy_pilot,
)


def _population(per_source: int):
    items = []
    for source_type in NewsSourceType:
        for index in range(per_source):
            length = (100, 900, 1_500)[index % 3]
            content = ("人工智能和资本市场政策。" * (length // 12 + 1))[
                :length
            ] + "。第二句。"
            item = freeze_news_item(
                source_type=source_type,
                source_key=f"{source_type.value}-{index}",
                title=f"样本 {index}",
                content=content,
                source_name="test",
                published_at=None
                if source_type is NewsSourceType.CCTV_NEWS
                else datetime(2026, 9, 20, 9, tzinfo=timezone.utc),
                content_date=date(2026, 9, 20)
                if source_type is NewsSourceType.CCTV_NEWS
                else None,
                fetched_at=datetime(2026, 9, 20, 10, tzinfo=timezone.utc),
                replay_assignment="TEST",
            )
            items.append(item)
    decisions = tuple(clean_candidate(item) for item in items)
    return tuple(items), decisions


def test_pilot_is_deterministic_and_has_exact_source_quotas() -> None:
    items, decisions = _population(80)
    first = select_taxonomy_pilot(items, decisions)
    second = select_taxonomy_pilot(items, decisions)
    assert [item.item.sample_id for item in first] == [
        item.item.sample_id for item in second
    ]
    assert sum(item.sample_group == "TUTORIAL" for item in first) == 20
    for source_type in NewsSourceType:
        assert (
            sum(
                item.sample_group == "BLIND_PILOT"
                and item.item.source_type is source_type
                for item in first
            )
            == 40
        )


def test_formal_set_uses_frozen_320_320_160_quotas() -> None:
    items, decisions = _population(400)
    selected = select_formal_calibration_set(items, decisions)
    assert len(selected) == 800
    assert sum(item.item.source_type is NewsSourceType.NEWS for item in selected) == 320
    assert (
        sum(item.item.source_type is NewsSourceType.MAJOR_NEWS for item in selected)
        == 320
    )
    assert (
        sum(item.item.source_type is NewsSourceType.CCTV_NEWS for item in selected)
        == 160
    )


def test_quality_metrics_are_reproducible() -> None:
    metrics = classification_metrics(
        [{"A"}, {"B"}],
        [{"A"}, {"A", "B"}],
        core_labels=frozenset({"A", "B"}),
    )
    assert metrics.core_recall == 1.0
    assert candidate_recall([{"A"}, {"B"}], [{"A", "C"}, {"C"}]) == 0.5
    assert krippendorff_alpha_nominal([("A", "A"), ("B", "B")]) == 1.0
    cluster_metrics = pairwise_clustering_metrics(
        {"a": "one", "b": "one", "c": "two"},
        {"a": "one", "b": "one", "c": "three"},
    )
    assert cluster_metrics["f1"] == 1.0
    ranks = ranking_metrics(
        ("a", "b", "c"),
        relevant_ids=frozenset({"a", "c"}),
        relevance_grades={"a": 3, "c": 2},
        critical_ids=frozenset({"c", "missing"}),
    )
    assert ranks["critical_miss_count"] == 1
    audit = summary_audit_metrics(
        ({"numeric_or_entity_error": False, "unsupported_claim": False},)
    )
    assert audit["passed"] is True


def test_seven_dimension_score_and_top_limits() -> None:
    limits = {
        "potential_impact": 30,
        "impact_scope": 15,
        "urgency": 15,
        "user_relevance": 15,
        "novelty": 10,
        "source_corroboration": 10,
        "source_credibility": 5,
    }
    events = []
    for index in range(40):
        dimensions = {
            name: ImportanceDimension(
                bucket="test", score=max(0, limit - index % 3), reason="evidence"
            )
            for name, limit in limits.items()
        }
        events.append(
            (
                f"event-{index:02d}",
                f"topic-{index % 8}",
                f"entity-{index % 10}",
                dimensions,
            )
        )
    ranked = rank_events(events)
    assert len(ranked) == 30
    assert len(delivery_candidates(ranked)) == 15
    assert {event.raw_rank for event in ranked}
