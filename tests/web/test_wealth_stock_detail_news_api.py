from __future__ import annotations

from datetime import datetime, timedelta, timezone

import src.biz.queries.wealth.market.stock_detail.news_query as news_query_module

from src.foundation.models.core_serving.news_stock_link import NewsStockLink
from src.foundation.models.core_serving.security_serving import Security
from src.foundation.models.core_serving_light.news import NewsLight


def _ensure_news_detail_tables(db_session) -> None:
    bind = db_session.get_bind()
    for table in (Security.__table__, NewsLight.__table__, NewsStockLink.__table__):
        table.create(bind, checkfirst=True)


def _seed_news(db_session) -> None:
    _ensure_news_detail_tables(db_session)
    db_session.add(
        Security(
            ts_code="603806.SH",
            symbol="603806",
            name="福斯特",
            fullname="杭州福斯特应用材料股份有限公司",
            security_type="EQUITY",
            source="tushare",
        )
    )
    news_rows = [
        ("news-z", datetime(2026, 5, 29, 10, 0, 5, tzinfo=timezone.utc), "同秒新闻 Z", "公司"),
        ("news-a", datetime(2026, 5, 29, 10, 0, 5, tzinfo=timezone.utc), "同秒新闻 A", "宏观"),
        ("news-new", datetime(2026, 5, 29, 10, 0, 6, tzinfo=timezone.utc), "更新新闻", "公司"),
        ("news-empty-title", datetime(2026, 5, 29, 9, 0, 0, tzinfo=timezone.utc), " ", "其他"),
    ]
    for news_id, news_time, title, channel in news_rows:
        db_session.add(
            NewsLight(
                row_key_hash=news_id,
                src="sina",
                news_time=news_time,
                title=title,
                content="正文回退标题内容" if news_id == "news-empty-title" else "正文",
                channels=channel,
                source="tushare",
                fetched_at=datetime(2026, 5, 29, 12, 0, tzinfo=timezone.utc),
            )
        )
        db_session.add(
            NewsStockLink(
                news_id=news_id,
                ts_code="603806.SH",
                match_method="SHORT_NAME_EXACT",
                source_field="title",
                rule_version="news-stock-rule-v1",
            )
        )
    db_session.commit()


def test_stock_detail_news_orders_by_full_time_and_row_key_without_channel_filter(app_client, db_session) -> None:
    _seed_news(db_session)

    response = app_client.get(
        "/api/v1/wealth/market/stock-detail/news",
        params={
            "tsCode": "603806.SH",
            "startAt": "2026-05-29T00:00:00+08:00",
            "endAt": "2026-05-30T00:00:00+08:00",
            "debug": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item["newsId"] for item in payload["items"]] == ["news-new", "news-a", "news-z", "news-empty-title"]
    assert payload["items"][0]["publishTime"].endswith("+08:00")
    assert payload["items"][0]["debugInfo"]["matchMethod"] == "SHORT_NAME_EXACT"
    assert payload["items"][-1]["title"] == "正文回退标题内容"


def test_stock_detail_news_normal_response_hides_match_method_and_clamps_limit(app_client, db_session) -> None:
    _seed_news(db_session)

    response = app_client.get(
        "/api/v1/wealth/market/stock-detail/news",
        params={
            "tsCode": "603806.SH",
            "startAt": "2026-05-29T00:00:00+08:00",
            "endAt": "2026-05-30T00:00:00+08:00",
            "limit": 2001,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["limit"] == 2000
    assert all("debugInfo" not in item for item in payload["items"])


def test_stock_detail_news_applies_limit_after_cross_batch_event_deduplication(
    app_client,
    db_session,
    monkeypatch,
) -> None:
    _ensure_news_detail_tables(db_session)
    monkeypatch.setattr(news_query_module, "NEWS_EVENT_CANDIDATE_BATCH_SIZE", 2)
    db_session.add(
        Security(
            ts_code="603806.SH",
            symbol="603806",
            name="福斯特",
            fullname="杭州福斯特应用材料股份有限公司",
            security_type="EQUITY",
            source="tushare",
        )
    )
    latest_time = datetime(2026, 8, 28, 2, 0, tzinfo=timezone.utc)
    news_rows = [
        (
            "event-copy-a",
            latest_time,
            "福斯特：2026年半年度净利润增长20%",
            "福斯特公告，2026年半年度净利润同比增长20%，经营情况保持稳定。",
            "SHORT_NAME_EXACT",
        ),
        (
            "event-copy-b",
            latest_time - timedelta(seconds=30),
            "福斯特：2026年半年度净利润增长20%",
            "福斯特公告，2026年半年度净利润同比增长20%，经营情况保持稳定，核心业务持续发展。",
            "FULL_NAME_EXACT",
        ),
        (
            "event-copy-c",
            latest_time - timedelta(seconds=60),
            "福斯特：2026年半年度净利润增长20%",
            "福斯特公告，2026年半年度净利润同比增长20%，经营情况保持稳定。",
            "SHORT_NAME_EXACT",
        ),
        (
            "independent-event",
            latest_time - timedelta(minutes=20),
            "福斯特：新建光伏胶膜产线正式投产",
            "福斯特公告，新建光伏胶膜产线已经完成验收并正式投入生产。",
            "SHORT_NAME_EXACT",
        ),
    ]
    for news_id, news_time, title, content, match_method in news_rows:
        db_session.add(
            NewsLight(
                row_key_hash=news_id,
                src="sina",
                news_time=news_time,
                title=title,
                content=content,
                channels="公司",
                source="tushare",
                fetched_at=latest_time,
            )
        )
        db_session.add(
            NewsStockLink(
                news_id=news_id,
                ts_code="603806.SH",
                match_method=match_method,
                source_field="title",
                rule_version="news-stock-rule-v1",
            )
        )
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/stock-detail/news",
        params={
            "tsCode": "603806.SH",
            "startAt": "2026-08-28T00:00:00+08:00",
            "endAt": "2026-08-29T00:00:00+08:00",
            "limit": 2,
            "debug": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item["newsId"] for item in payload["items"]] == [
        "event-copy-b",
        "independent-event",
    ]
    assert payload["items"][0]["debugInfo"]["matchMethod"] == "FULL_NAME_EXACT"
    assert payload["meta"]["count"] == 2
    assert payload["meta"]["limit"] == 2


def test_stock_detail_news_rejects_unknown_stock_and_naive_datetime(app_client, db_session) -> None:
    _ensure_news_detail_tables(db_session)

    not_found = app_client.get(
        "/api/v1/wealth/market/stock-detail/news",
        params={"tsCode": "000000.SH"},
    )
    assert not_found.status_code == 404
    assert not_found.json()["code"] == "404001"

    naive = app_client.get(
        "/api/v1/wealth/market/stock-detail/news",
        params={"tsCode": "603806.SH", "startAt": "2026-05-29T00:00:00"},
    )
    assert naive.status_code == 400
    assert naive.json()["code"] == "400001"
