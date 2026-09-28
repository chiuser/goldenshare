from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src.biz.services.wealth.news_intelligence.contracts import (
    CandidateStatus,
    NewsSourceType,
)
from src.biz.services.wealth.news_intelligence.policy import build_label_candidates
from src.biz.services.wealth.news_intelligence.replay import (
    build_replay_windows,
    clean_candidate,
    cluster_candidates,
    freeze_news_item,
    mark_exact_duplicates,
)


def _item(
    key: str,
    *,
    source_type: NewsSourceType = NewsSourceType.NEWS,
    title: str = "央行宣布降准",
    content: str = "人民银行宣布降低存款准备金率。政策将于明日生效。",
    published_at: datetime | None = datetime(2026, 9, 20, 9, tzinfo=timezone.utc),
    content_date: date | None = None,
):
    if source_type is NewsSourceType.CCTV_NEWS:
        published_at = None
        content_date = content_date or date(2026, 9, 20)
    return freeze_news_item(
        source_type=source_type,
        source_key=key,
        title=title,
        content=content,
        source_name="unit-test",
        published_at=published_at,
        content_date=content_date,
        fetched_at=datetime(2026, 9, 20, 10, tzinfo=timezone.utc),
        replay_assignment="TEST",
    )


def test_five_replay_windows_include_cross_day_0800_window() -> None:
    windows = build_replay_windows(date(2026, 9, 20))
    assert [window.end_at.hour for window in windows] == [8, 12, 16, 20, 22]
    assert windows[0].start_at.date() == date(2026, 9, 19)
    assert windows[0].start_at.hour == 22
    assert all(window.timezone == "Asia/Shanghai" for window in windows)


def test_sample_id_is_stable_and_input_hash_detects_content_change() -> None:
    first = _item("abc", content="正文一。正文二。")
    repeated = _item("abc", content="正文一。正文二。")
    changed = _item("abc", content="正文已经变化。正文二。")
    assert first.sample_id == repeated.sample_id == changed.sample_id == "m1:news:abc"
    assert first.input_hash == repeated.input_hash
    assert first.input_hash != changed.input_hash


def test_cctv_requires_content_date_and_never_intraday_time() -> None:
    item = _item("cctv", source_type=NewsSourceType.CCTV_NEWS)
    assert item.published_at is None
    assert item.content_date == date(2026, 9, 20)
    with pytest.raises(ValueError, match="content_date"):
        freeze_news_item(
            source_type=NewsSourceType.CCTV_NEWS,
            source_key="invalid",
            title="title",
            content="content",
            source_name="cctv",
            published_at=None,
            content_date=None,
            fetched_at=datetime.now(timezone.utc),
            replay_assignment="TEST",
        )


def test_summary_boundary_rejects_short_and_single_sentence_long_text() -> None:
    short = clean_candidate(_item("short", content="短讯。"))
    single_sentence = clean_candidate(_item("single", content="长" * 900 + "。"))
    eligible = clean_candidate(
        _item("eligible", content="甲" * 500 + "。" + "乙" * 400 + "。")
    )
    assert not short.summary_eligible
    assert not single_sentence.summary_eligible
    assert eligible.summary_eligible


def test_empty_and_exact_duplicate_candidates_are_retained_with_reasons() -> None:
    empty = clean_candidate(_item("empty", title="", content=""))
    first = clean_candidate(_item("first"))
    duplicate = clean_candidate(_item("duplicate"))
    items = (_item("empty", title="", content=""), _item("first"), _item("duplicate"))
    decisions = mark_exact_duplicates(items, (empty, first, duplicate))
    assert decisions[0].status is CandidateStatus.EXCLUDED
    assert decisions[0].exclusion_code == "INVALID_CONTENT_EMPTY"
    assert decisions[2].status is CandidateStatus.EXCLUDED
    assert decisions[2].exclusion_code == "EXACT_DUPLICATE"
    assert decisions[2].exact_duplicate_of == first.sample_id


def test_exact_duplicate_does_not_discard_independent_source_corroboration() -> None:
    news = _item("news-copy")
    major = _item("major-copy", source_type=NewsSourceType.MAJOR_NEWS)
    decisions = mark_exact_duplicates(
        (news, major),
        (clean_candidate(news), clean_candidate(major)),
    )
    assert all(decision.status is CandidateStatus.ELIGIBLE for decision in decisions)


def test_conservative_clustering_refuses_numeric_conflict() -> None:
    first = _item("one", content="公司收入增长10%。事件发生。")
    second = _item("two", content="公司收入增长20%。事件发生。")
    decisions = tuple(clean_candidate(item) for item in (first, second))
    clusters = cluster_candidates(
        (first, second),
        decisions,
        {first.sample_id: (1.0, 0.0), second.sample_id: (1.0, 0.0)},
        similarity_threshold=0.8,
    )
    assert len(clusters) == 2


def test_label_candidate_caps_and_priority_recall_rules() -> None:
    labels = build_label_candidates(
        "央行降准并支持人工智能芯片产业",
        "证监会同时发布资本市场新规，涉及半导体、AI和公开市场操作。",
    )
    assert len(labels.primary_topics) <= 4
    assert len(labels.event_types) <= 6
    assert "ECONOMY_BUSINESS_FINANCE" in labels.primary_topics
    assert "SCIENCE_TECHNOLOGY" in labels.primary_topics
    assert "ECONOMY.MONETARY_POLICY" in labels.matched_rules
    assert "TECH.ARTIFICIAL_INTELLIGENCE" in labels.matched_rules
