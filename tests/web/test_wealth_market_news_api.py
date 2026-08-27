from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import literal, select
from sqlalchemy.dialects import postgresql

from src.biz.queries.wealth.market.news.news_display_title import (
    build_news_display_title,
    build_news_display_title_expr,
    extract_leading_bracket_title,
)
from src.foundation.models.core_serving_light.major_news import MajorNewsLight
from src.foundation.models.core_serving_light.news import NewsLight


def _ensure_news_tables(db_session) -> None:
    bind = db_session.get_bind()
    for table in (NewsLight.__table__, MajorNewsLight.__table__):
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


def _add_major_news(
    db_session,
    *,
    row_key_hash: str,
    pub_time: datetime,
    title: str | None,
    content: str | None,
    src: str = "cls",
    url: str | None = "https://example.com/original",
) -> None:
    db_session.add(
        MajorNewsLight(
            row_key_hash=row_key_hash,
            src=src,
            pub_time=pub_time,
            title=title,
            content=content,
            url=url,
            source="tushare-source-must-not-leak",
            fetched_at=datetime(2026, 5, 8, 16, 0, tzinfo=timezone.utc),
        )
    )


@pytest.mark.parametrize(
    ("raw_title", "content", "expected_title", "expected_extracted_title"),
    [
        ("【标题】摘要", "正文", "标题", "标题"),
        ("  【 标题 】摘要  ", "正文", "标题", "标题"),
        ("【第一标题】【第二标题】摘要", "正文", "第一标题", "第一标题"),
        ("【缺少右括号", "正文", "【缺少右括号", None),
        ("【】摘要", "正文", "【】摘要", None),
        ("【   】摘要", "正文", "【   】摘要", None),
        ("前缀【标题】摘要", "正文", "前缀【标题】摘要", None),
        ("[半角标题]摘要", "正文", "[半角标题]摘要", None),
        (None, "【正文中的括号】正文 fallback", "【正文中的括号】正文 fallback", None),
        ("  ", "正文 fallback", "正文 fallback", None),
    ],
)
def test_news_display_title_python_and_sql_rules_are_consistent(
    db_session,
    raw_title: str | None,
    content: str,
    expected_title: str,
    expected_extracted_title: str | None,
) -> None:
    fallback_title = content.strip()[:80]

    python_title = build_news_display_title(raw_title, fallback_title)
    sql_title = db_session.scalar(
        select(
            build_news_display_title_expr(
                literal(raw_title),
                literal(content),
            )
        )
    )

    assert python_title == expected_title
    assert sql_title == expected_title
    assert extract_leading_bracket_title(raw_title) == expected_extracted_title


def test_news_display_title_expression_uses_postgresql_substring_position() -> None:
    statement = select(
        build_news_display_title_expr(
            literal("【标题】摘要"),
            literal("正文"),
        )
    )

    compiled = str(statement.compile(dialect=postgresql.dialect()))

    assert "strpos(" in compiled
    assert "instr(" not in compiled


def test_market_news_endpoints_use_independent_sources(app_client, db_session) -> None:
    _ensure_news_tables(db_session)
    now, in_window_time, before_window_time = _news_window_sample_times()
    _add_news(
        db_session,
        row_key_hash="brief-company",
        news_time=in_window_time + timedelta(minutes=5),
        title="两列共有标题",
        channels="公司",
        content="公司频道也属于完整快讯流",
    )
    _add_news(
        db_session,
        row_key_hash="brief-macro",
        news_time=in_window_time + timedelta(minutes=4),
        title="宏观快讯",
        channels="宏观",
        content="宏观快讯正文",
    )
    _add_news(
        db_session,
        row_key_hash="brief-null-channel",
        news_time=in_window_time + timedelta(minutes=3),
        title=None,
        channels=None,
        content="无频道快讯正文",
    )
    _add_news(
        db_session,
        row_key_hash="brief-outside-window",
        news_time=before_window_time,
        title="窗口外快讯",
        channels="宏观",
        content="窗口外快讯正文",
    )
    _add_major_news(
        db_session,
        row_key_hash="communication-shared-title",
        pub_time=in_window_time + timedelta(minutes=7),
        title="两列共有标题",
        content="<article><p>通讯正文</p></article>",
    )
    _add_major_news(
        db_session,
        row_key_hash="communication-duplicate-old",
        pub_time=in_window_time + timedelta(minutes=2),
        title="重复通讯标题",
        content="较旧通讯正文",
    )
    _add_major_news(
        db_session,
        row_key_hash="communication-duplicate-new",
        pub_time=in_window_time + timedelta(minutes=6),
        title="重复通讯标题",
        content="较新通讯正文",
    )
    _add_major_news(
        db_session,
        row_key_hash="communication-empty-title",
        pub_time=in_window_time + timedelta(minutes=8),
        title=" ",
        content="不能进入列表",
    )
    _add_major_news(
        db_session,
        row_key_hash="communication-empty-content",
        pub_time=in_window_time + timedelta(minutes=9),
        title="空正文通讯",
        content=" ",
    )
    db_session.commit()

    briefs_response = app_client.get("/api/v1/wealth/market/news/briefs", params={"debug": 1})
    communications_response = app_client.get(
        "/api/v1/wealth/market/news/communications",
        params={"debug": 1},
    )

    assert briefs_response.status_code == 200
    briefs_payload = briefs_response.json()
    assert briefs_payload["newsWindow"]["market"] == "CN_A"
    assert briefs_payload["newsWindow"]["startAt"][:10] == (now.date() - timedelta(days=1)).isoformat()
    assert briefs_payload["pageStatus"]["status"] == "READY"
    assert briefs_payload["newsBriefs"]["panelKey"] == "newsBriefs"
    assert briefs_payload["newsBriefs"]["sortRule"] == "publishTime_desc"
    assert [item["newsId"] for item in briefs_payload["newsBriefs"]["items"]] == [
        "brief-company",
        "brief-macro",
        "brief-null-channel",
    ]
    assert {item["contentSource"] for item in briefs_payload["newsBriefs"]["items"]} == {"news"}
    assert {item["category"] for item in briefs_payload["newsBriefs"]["items"]} == {"brief"}
    assert briefs_payload["newsBriefs"]["items"][2]["title"] == "无频道快讯正文"
    assert not {"subject", "priority", "url", "html", "content"}.intersection(
        briefs_payload["newsBriefs"]["items"][0]
    )

    assert communications_response.status_code == 200
    communications_payload = communications_response.json()
    assert communications_payload["pageStatus"]["status"] == "READY"
    assert communications_payload["newsCommunications"]["panelKey"] == "newsCommunications"
    assert [item["newsId"] for item in communications_payload["newsCommunications"]["items"]] == [
        "communication-shared-title",
        "communication-duplicate-new",
    ]
    assert {item["contentSource"] for item in communications_payload["newsCommunications"]["items"]} == {
        "major_news"
    }
    assert {item["category"] for item in communications_payload["newsCommunications"]["items"]} == {
        "communication"
    }
    assert communications_payload["newsCommunications"]["items"][0]["source"] == "cls"
    assert communications_payload["newsCommunications"]["items"][0]["readerMode"] == "HTML"
    assert briefs_payload["newsBriefs"]["items"][0]["title"] == "两列共有标题"
    assert communications_payload["newsCommunications"]["items"][0]["title"] == "两列共有标题"
    assert communications_payload["debugInfo"]["modules"][0]["moduleKey"] == "newsCommunications"
    assert app_client.get("/api/v1/wealth/market/news/stocks").status_code == 404


def test_market_news_extracts_leading_bracket_title_before_deduplication(
    app_client,
    db_session,
) -> None:
    _ensure_news_tables(db_session)
    _, in_window_time, _ = _news_window_sample_times()
    sample_title = "商务部等9部门：支持航空保税维修绿色化发展"
    _add_news(
        db_session,
        row_key_hash="brief-bracket-sample",
        news_time=in_window_time + timedelta(minutes=5),
        title=f"【{sample_title}】商务部等9部门发布关于促进航空保税维修高质量发展的意见",
        channels="宏观",
        content="新闻正文",
    )
    _add_news(
        db_session,
        row_key_hash="brief-dedup-old",
        news_time=in_window_time + timedelta(minutes=3),
        title="【同一展示标题】较旧摘要",
        channels="公司",
        content="较旧正文",
    )
    _add_news(
        db_session,
        row_key_hash="brief-dedup-new",
        news_time=in_window_time + timedelta(minutes=4),
        title="【同一展示标题】较新摘要",
        channels="公司",
        content="较新正文",
    )
    _add_news(
        db_session,
        row_key_hash="brief-body-brackets",
        news_time=in_window_time + timedelta(minutes=2),
        title=None,
        channels=None,
        content="【正文中的括号】不能反向提取",
    )
    _add_major_news(
        db_session,
        row_key_hash="communication-brackets",
        pub_time=in_window_time + timedelta(minutes=6),
        title="【新闻通讯标题】尾部保持原样",
        content="新闻通讯正文",
    )
    db_session.commit()

    briefs_response = app_client.get("/api/v1/wealth/market/news/briefs")
    communications_response = app_client.get("/api/v1/wealth/market/news/communications")

    assert briefs_response.status_code == 200
    briefs = briefs_response.json()["newsBriefs"]["items"]
    assert [item["newsId"] for item in briefs] == [
        "brief-bracket-sample",
        "brief-dedup-new",
        "brief-body-brackets",
    ]
    assert [item["title"] for item in briefs] == [
        sample_title,
        "同一展示标题",
        "【正文中的括号】不能反向提取",
    ]
    assert "促进航空保税维修高质量发展的意见" not in briefs[0]["title"]

    assert communications_response.status_code == 200
    communications = communications_response.json()["newsCommunications"]["items"]
    assert communications[0]["title"] == "【新闻通讯标题】尾部保持原样"


def test_market_news_endpoint_marks_delayed_without_old_day_fallback(app_client, db_session) -> None:
    _ensure_news_tables(db_session)
    _, _, before_window_time = _news_window_sample_times()
    _add_news(
        db_session,
        row_key_hash="brief-old",
        news_time=before_window_time,
        title="旧日市场新闻",
        channels="宏观",
        content="旧日市场新闻正文",
    )
    db_session.commit()

    response = app_client.get("/api/v1/wealth/market/news/briefs", params={"debug": 1})

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
            row_key_hash=f"brief-bulk-{index:03d}",
            news_time=in_window_time + timedelta(seconds=index),
            title=f"市场新闻 {index:03d}",
            channels="公司" if index % 2 else "宏观",
            content=f"市场新闻正文 {index:03d}",
        )
    db_session.commit()

    response = app_client.get("/api/v1/wealth/market/news/briefs")

    assert response.status_code == 200
    items = response.json()["newsBriefs"]["items"]
    assert len(items) == 300
    assert items[0]["newsId"] == "brief-bulk-304"
    assert items[-1]["newsId"] == "brief-bulk-005"


def test_market_news_rejects_unsupported_market(app_client) -> None:
    response = app_client.get("/api/v1/wealth/market/news/briefs", params={"market": "US"})
    assert response.status_code == 400
    assert response.json()["code"] == "400001"


def test_market_news_source_contract_has_no_stock_compatibility() -> None:
    root = Path(__file__).resolve().parents[2]
    market_query = (root / "src/biz/queries/wealth/market/news/market_news_query.py").read_text(encoding="utf-8")
    scoped_files = [
        root / "src/biz/queries/wealth/market/news/news_query_service.py",
        root / "src/app/api/v1/router.py",
        root / "wealth/src/features/market-overview/news/api/marketNewsApi.ts",
        root / "wealth/src/features/market-overview/news/api/marketNewsAdapter.ts",
        root / "wealth/src/features/market-overview/news/MarketNewsPanelGroup.tsx",
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in scoped_files)

    assert "channels" not in market_query
    assert "StockNewsQuery" not in source
    assert "build_stock_news" not in source
    assert "stockNews" not in source
    assert "/news/stocks" not in source
    assert not (root / "src/biz/api/wealth/market/stock_news.py").exists()
    assert not (root / "src/biz/schemas/wealth/market/stock_news.py").exists()
    assert not (root / "src/biz/queries/wealth/market/news/stock_news_query.py").exists()
