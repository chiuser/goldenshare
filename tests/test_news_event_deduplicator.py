from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.biz.queries.wealth.market.news.news_event_deduplicator import (
    NewsEventCandidate,
    deduplicate_news_events,
)


BASE_TIME = datetime(2026, 8, 18, 9, 51, 19, tzinfo=timezone.utc)


def _candidate(
    news_id: str,
    *,
    published_at: datetime,
    title: str | None,
    content: str,
    source: str = "source",
) -> NewsEventCandidate:
    return NewsEventCandidate(
        news_id=news_id,
        publish_time=published_at,
        title=title,
        content=content,
        source=source,
        match_method="SHORT_NAME_EXACT",
    )


def test_news_event_deduplicator_collapses_multi_source_company_events() -> None:
    financial_title = "甲公司：2026年上半年净利润10.01亿元，同比下降47.55%"
    financial_body = (
        "甲公司公告，2026年上半年营业收入180.43亿元，同比下降11.88%；"
        "归属于上市公司股东的净利润10.01亿元，同比下降47.55%。"
    )
    project_short_title = "甲公司：国电投滨海2×100万千瓦扩建项目6号机组投产"
    project_complete_title = "甲公司：国电投滨海2×100万千瓦扩建项目6号机组投产，项目全面建成"
    project_alternate_title = "甲公司：滨海2×100万千瓦扩建项目全面建成投产"
    project_short_body = project_short_title + "。"
    project_medium_body = (
        "甲公司公告，公司控股子公司投资建设的国电投滨海2×100万千瓦扩建项目6号机组近日通过"
        "168小时满负荷试运行，正式投产。该项目首台5号机组已于2026年7月12日投产，至此项目全面建成。"
    )
    project_long_body = (
        "【甲公司：滨海2×100万千瓦扩建项目全面建成投产】甲公司公告称，公司控股子公司投资建设的"
        "国电投滨海2×100万千瓦扩建项目6号机组顺利通过168小时满负荷试运行，正式投产。"
        "项目位于江苏省盐城港滨海港区，规划建设两台100万千瓦清洁高效燃煤发电机组，至此全面建成投产。"
    )
    financial_time = datetime(2026, 8, 28, 10, 59, 29, tzinfo=timezone.utc)
    candidates = [
        _candidate(
            "financial-bracket",
            published_at=financial_time,
            title=None,
            content=f"【{financial_title}】{financial_body}",
            source="sina",
        ),
        _candidate(
            "financial-complete",
            published_at=financial_time - timedelta(seconds=39),
            title=financial_title,
            content=financial_body,
            source="jinrongjie",
        ),
        _candidate(
            "financial-truncated-body",
            published_at=financial_time - timedelta(seconds=89),
            title=financial_title,
            content=financial_body[:-5] + "...",
            source="10jqka",
        ),
        _candidate(
            "project-short",
            published_at=BASE_TIME,
            title=None,
            content=project_short_body,
            source="wallstreetcn",
        ),
        _candidate(
            "project-long",
            published_at=BASE_TIME - timedelta(seconds=4),
            title=project_alternate_title,
            content=project_long_body[:-30],
            source="jinrongjie",
        ),
        _candidate(
            "project-complete",
            published_at=BASE_TIME - timedelta(seconds=4),
            title=project_complete_title,
            content=project_medium_body,
            source="jinrongjie",
        ),
        _candidate(
            "project-complete-copy",
            published_at=BASE_TIME - timedelta(seconds=26),
            title=project_complete_title,
            content=project_medium_body,
            source="wallstreetcn",
        ),
        _candidate(
            "project-alternate",
            published_at=BASE_TIME - timedelta(seconds=99),
            title=project_alternate_title,
            content=project_long_body[:120],
            source="eastmoney",
        ),
        _candidate(
            "project-longest",
            published_at=BASE_TIME - timedelta(seconds=99),
            title=project_alternate_title,
            content=project_long_body,
            source="cls",
        ),
        _candidate(
            "project-bracket",
            published_at=BASE_TIME - timedelta(seconds=100),
            title=None,
            content=f"【{project_complete_title}】{project_medium_body}",
            source="sina",
        ),
        _candidate(
            "project-truncated",
            published_at=BASE_TIME - timedelta(seconds=139),
            title=project_complete_title[:27] + "...",
            content=project_medium_body,
            source="10jqka",
        ),
    ]

    events = deduplicate_news_events(list(reversed(candidates)))
    events_in_source_order = deduplicate_news_events(candidates)

    assert [event.representative.news_id for event in events] == [
        "financial-complete",
        "project-longest",
    ]
    assert [event.display_title for event in events] == [financial_title, project_alternate_title]
    assert events_in_source_order == events


def test_news_event_deduplicator_keeps_conflicting_numbers_and_distant_events() -> None:
    shared_content = "甲公司公告，项目机组已经完成试运行并正式投产，后续将持续提升稳定运行能力。"
    current = _candidate(
        "unit-6",
        published_at=BASE_TIME,
        title="甲公司：扩建项目6号机组正式投产",
        content=shared_content,
    )
    conflicting = _candidate(
        "unit-5",
        published_at=BASE_TIME - timedelta(minutes=1),
        title="甲公司：扩建项目5号机组正式投产",
        content=shared_content,
    )
    distant = _candidate(
        "unit-6-later",
        published_at=BASE_TIME - timedelta(minutes=11),
        title=current.title,
        content=shared_content,
    )

    events = deduplicate_news_events([conflicting, distant, current])

    assert [event.representative.news_id for event in events] == ["unit-6", "unit-5", "unit-6-later"]


def test_news_event_deduplicator_does_not_merge_short_generic_content() -> None:
    events = deduplicate_news_events(
        [
            _candidate(
                "brief-a",
                published_at=BASE_TIME,
                title="事项A",
                content="公司公告正文",
            ),
            _candidate(
                "brief-b",
                published_at=BASE_TIME - timedelta(seconds=1),
                title="事项B",
                content="公司公告正文",
            ),
        ]
    )

    assert [event.representative.news_id for event in events] == ["brief-a", "brief-b"]


def test_news_event_deduplicator_keeps_conflicting_fact_numbers() -> None:
    events = deduplicate_news_events(
        [
            _candidate(
                "progress-6",
                published_at=BASE_TIME,
                title="甲公司：扩建项目建设进展公告",
                content="甲公司公告，扩建项目6号机组已经正式投产。",
            ),
            _candidate(
                "progress-5",
                published_at=BASE_TIME - timedelta(seconds=30),
                title="甲公司：扩建项目建设进展公告",
                content="甲公司公告，扩建项目5号机组已经正式投产。",
            ),
        ]
    )

    assert [event.representative.news_id for event in events] == ["progress-6", "progress-5"]


def test_news_event_deduplicator_does_not_chain_beyond_event_window() -> None:
    title = "甲公司：同一事项发布最新进展公告"
    content = "甲公司公告，同一事项已经取得最新进展，后续安排保持不变。"
    events = deduplicate_news_events(
        [
            _candidate(
                "chain-latest",
                published_at=BASE_TIME,
                title=title,
                content=content,
            ),
            _candidate(
                "chain-middle",
                published_at=BASE_TIME - timedelta(minutes=9),
                title=title,
                content=content,
            ),
            _candidate(
                "chain-oldest",
                published_at=BASE_TIME - timedelta(minutes=18),
                title=title,
                content=content,
            ),
        ]
    )

    assert [event.representative.news_id for event in events] == ["chain-latest", "chain-oldest"]
