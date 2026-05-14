from __future__ import annotations

from datetime import date, datetime, timezone

from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving_light.news import NewsLight


def _ensure_news_tables(db_session) -> None:
    bind = db_session.get_bind()
    for table in [
        TradeCalendar.__table__,
        NewsLight.__table__,
    ]:
        table.create(bind, checkfirst=True)


def _seed_trade_calendar(db_session, *, target_date: date, prev_date: date) -> None:
    db_session.add(
        TradeCalendar(
            exchange="SSE",
            trade_date=prev_date,
            is_open=True,
            pretrade_date=None,
        )
    )
    db_session.add(
        TradeCalendar(
            exchange="SSE",
            trade_date=target_date,
            is_open=True,
            pretrade_date=prev_date,
        )
    )


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
    target_date = date(2026, 5, 8)
    _seed_trade_calendar(db_session, target_date=target_date, prev_date=date(2026, 5, 7))
    _add_news(
        db_session,
        row_key_hash="market-news-001",
        news_time=datetime(2026, 5, 8, 15, 5, 1),
        title="央行公开市场开展逆回购操作",
        channels="宏观",
    )
    _add_news(
        db_session,
        row_key_hash="market-news-002",
        news_time=datetime(2026, 5, 8, 15, 4, 1),
        title=None,
        content="市场流动性保持合理充裕",
        channels=None,
    )
    _add_news(
        db_session,
        row_key_hash="stock-news-001",
        news_time=datetime(2026, 5, 8, 15, 3, 1),
        title="某上市公司发布一季度经营进展",
        channels="公司",
    )
    db_session.commit()

    briefs_response = app_client.get(
        "/api/v1/wealth/market/news/briefs",
        params={"tradeDate": "2026-05-08", "debug": 1},
    )
    assert briefs_response.status_code == 200
    briefs_payload = briefs_response.json()
    assert briefs_payload["tradingDay"]["tradeDate"] == "2026-05-08"
    assert briefs_payload["pageStatus"]["status"] == "READY"
    assert briefs_payload["newsBriefs"]["panelKey"] == "newsBriefs"
    assert briefs_payload["newsBriefs"]["visibleItemCount"] == 10
    assert [item["newsId"] for item in briefs_payload["newsBriefs"]["items"]] == [
        "market-news-001",
        "market-news-002",
    ]
    assert briefs_payload["newsBriefs"]["items"][0]["displayTime"] == "05-08 15:05:01"
    assert briefs_payload["newsBriefs"]["items"][0]["title"] == "央行公开市场开展逆回购操作"
    assert briefs_payload["newsBriefs"]["items"][0]["category"] == "market"
    assert briefs_payload["newsBriefs"]["items"][0]["clickable"] is False
    assert briefs_payload["newsBriefs"]["items"][1]["title"] == "市场流动性保持合理充裕"
    assert briefs_payload["debugInfo"]["modules"][0]["moduleKey"] == "newsBriefs"

    stocks_response = app_client.get(
        "/api/v1/wealth/market/news/stocks",
        params={"tradeDate": "2026-05-08", "debug": 1},
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

    no_debug_response = app_client.get("/api/v1/wealth/market/news/briefs", params={"tradeDate": "2026-05-08"})
    assert no_debug_response.status_code == 200
    no_debug_payload = no_debug_response.json()
    assert "debugInfo" not in no_debug_payload or no_debug_payload["debugInfo"] is None


def test_market_news_endpoint_marks_delayed_without_old_day_fallback(app_client, db_session) -> None:
    _ensure_news_tables(db_session)
    _seed_trade_calendar(db_session, target_date=date(2026, 5, 8), prev_date=date(2026, 5, 7))
    _add_news(
        db_session,
        row_key_hash="market-news-old",
        news_time=datetime(2026, 5, 7, 15, 5, 1),
        title="旧日市场新闻",
        channels="宏观",
    )
    db_session.commit()

    response = app_client.get(
        "/api/v1/wealth/market/news/briefs",
        params={"tradeDate": "2026-05-08", "debug": 1},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["pageStatus"]["status"] == "DELAYED"
    assert payload["newsBriefs"]["items"] == []
    assert payload["debugInfo"]["modules"][0]["observedTradeDate"] == "2026-05-07"
    assert payload["debugInfo"]["exceptions"][0]["code"] == "NEWS_SOURCE_DELAYED"


def test_market_news_rejects_unsupported_market(app_client) -> None:
    response = app_client.get("/api/v1/wealth/market/news/briefs", params={"market": "US"})
    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == "400001"
