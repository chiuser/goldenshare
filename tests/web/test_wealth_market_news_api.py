from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from src.foundation.models.core_serving_light.news import NewsLight


def _ensure_news_tables(db_session) -> None:
    bind = db_session.get_bind()
    for table in [
        NewsLight.__table__,
    ]:
        table.create(bind, checkfirst=True)


def _news_window_sample_times() -> tuple[datetime, datetime, datetime]:
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    window_start = datetime.combine(now.date() - timedelta(days=1), time.min, tzinfo=ZoneInfo("Asia/Shanghai"))
    return now, window_start + timedelta(hours=9), window_start - timedelta(minutes=1)


def _add_news(
    db_session,
    *,
    row_key_hash: str,
    news_time: datetime,
    title: str | None,
    channels: str | None,
    content: str | None = None,
    src: str = "sina",
) -> None:
    db_session.add(
        NewsLight(
            row_key_hash=row_key_hash,
            src=src,
            news_time=news_time,
            title=title,
            content=content,
            channels=channels,
            score=None,
            source="tushare",
            fetched_at=datetime(2026, 5, 8, 16, 0, tzinfo=timezone.utc),
        )
    )


def test_market_news_endpoints_return_split_panels(app_client, db_session) -> None:
    _ensure_news_tables(db_session)
    now, in_window_time, before_window_time = _news_window_sample_times()
    _add_news(
        db_session,
        row_key_hash="market-news-001",
        news_time=in_window_time + timedelta(minutes=5),
        title="央行公开市场开展逆回购操作",
        channels="宏观",
        content="央行公开市场开展逆回购操作正文",
    )
    _add_news(
        db_session,
        row_key_hash="market-news-002",
        news_time=in_window_time + timedelta(minutes=4),
        title=None,
        content="市场流动性保持合理充裕",
        channels=None,
    )
    _add_news(
        db_session,
        row_key_hash="market-news-duplicate-old",
        news_time=in_window_time + timedelta(minutes=3),
        title="重复旧新闻",
        content="市场流动性保持合理充裕",
        channels="宏观",
    )
    _add_news(
        db_session,
        row_key_hash="market-news-empty-content",
        news_time=in_window_time + timedelta(minutes=2),
        title="只有标题没有正文",
        content=" ",
        channels="宏观",
    )
    _add_news(
        db_session,
        row_key_hash="market-news-before-window",
        news_time=before_window_time,
        title="窗口外旧新闻",
        content="窗口外旧新闻正文",
        channels="宏观",
    )
    _add_news(
        db_session,
        row_key_hash="stock-news-001",
        news_time=in_window_time + timedelta(minutes=1),
        title="某上市公司发布一季度经营进展",
        channels="公司",
        content="某上市公司发布一季度经营进展正文",
    )
    db_session.commit()

    briefs_response = app_client.get(
        "/api/v1/wealth/market/news/briefs",
        params={"debug": 1},
    )
    assert briefs_response.status_code == 200
    briefs_payload = briefs_response.json()
    assert briefs_payload["newsWindow"]["market"] == "CN_A"
    assert briefs_payload["newsWindow"]["startAt"][:10] == (now.date() - timedelta(days=1)).isoformat()
    assert briefs_payload["newsWindow"]["endAt"][:10] == now.date().isoformat()
    assert briefs_payload["pageStatus"]["status"] == "READY"
    assert briefs_payload["newsBriefs"]["panelKey"] == "newsBriefs"
    assert briefs_payload["newsBriefs"]["visibleItemCount"] == 10
    assert [item["newsId"] for item in briefs_payload["newsBriefs"]["items"]] == [
        "market-news-001",
        "market-news-002",
    ]
    assert briefs_payload["newsBriefs"]["items"][0]["title"] == "央行公开市场开展逆回购操作"
    assert briefs_payload["newsBriefs"]["items"][0]["category"] == "market"
    assert briefs_payload["newsBriefs"]["items"][0]["clickable"] is False
    assert briefs_payload["newsBriefs"]["items"][1]["title"] == "市场流动性保持合理充裕"
    assert briefs_payload["debugInfo"]["modules"][0]["moduleKey"] == "newsBriefs"

    stocks_response = app_client.get(
        "/api/v1/wealth/market/news/stocks",
        params={"debug": 1},
    )
    assert stocks_response.status_code == 200
    stocks_payload = stocks_response.json()
    assert stocks_payload["pageStatus"]["status"] == "READY"
    assert stocks_payload["stockNews"]["panelKey"] == "stockNews"
    assert [item["newsId"] for item in stocks_payload["stockNews"]["items"]] == ["stock-news-001"]
    assert stocks_payload["stockNews"]["items"][0]["category"] == "stock"
    assert stocks_payload["stockNews"]["items"][0]["subject"] is None
    assert stocks_payload["stockNews"]["items"][0]["clickable"] is False
    assert stocks_payload["debugInfo"]["modules"][0]["moduleKey"] == "stockNews"

    no_debug_response = app_client.get("/api/v1/wealth/market/news/briefs")
    assert no_debug_response.status_code == 200
    no_debug_payload = no_debug_response.json()
    assert "debugInfo" not in no_debug_payload or no_debug_payload["debugInfo"] is None


def test_market_news_endpoint_marks_delayed_without_old_day_fallback(app_client, db_session) -> None:
    _ensure_news_tables(db_session)
    _, _, before_window_time = _news_window_sample_times()
    _add_news(
        db_session,
        row_key_hash="market-news-old",
        news_time=before_window_time,
        title="旧日市场新闻",
        channels="宏观",
        content="旧日市场新闻正文",
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/news/briefs",
        params={"debug": 1},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["pageStatus"]["status"] == "DELAYED"
    assert payload["newsBriefs"]["items"] == []
    assert payload["debugInfo"]["modules"][0]["observedTradeDate"] == before_window_time.date().isoformat()
    assert payload["debugInfo"]["exceptions"][0]["code"] == "NEWS_SOURCE_DELAYED"


def test_market_news_endpoint_returns_300_item_candidate_pool(app_client, db_session) -> None:
    _ensure_news_tables(db_session)
    _, in_window_time, _ = _news_window_sample_times()
    for index in range(305):
        _add_news(
            db_session,
            row_key_hash=f"market-news-bulk-{index:03d}",
            news_time=in_window_time + timedelta(seconds=index),
            title=f"市场新闻 {index:03d}",
            channels="宏观",
            content=f"市场新闻正文 {index:03d}",
        )
    db_session.commit()

    response = app_client.get("/api/v1/wealth/market/news/briefs")
    assert response.status_code == 200
    payload = response.json()
    items = payload["newsBriefs"]["items"]
    assert payload["newsBriefs"]["visibleItemCount"] == 10
    assert len(items) == 300
    assert items[0]["newsId"] == "market-news-bulk-304"
    assert items[-1]["newsId"] == "market-news-bulk-005"


def test_market_news_rejects_unsupported_market(app_client) -> None:
    response = app_client.get("/api/v1/wealth/market/news/briefs", params={"market": "US"})
    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == "400001"
