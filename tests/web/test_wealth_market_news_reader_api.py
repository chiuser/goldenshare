from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import event

from src.biz.queries.wealth.market.news.news_reader_query_service import NewsReaderQueryService
from src.biz.schemas.wealth.market.news_common import NewsContentSourceValue
from src.foundation.models.core_serving_light.major_news import MajorNewsLight
from src.foundation.models.core_serving_light.news import NewsLight


def _ensure_news_tables(db_session) -> None:
    bind = db_session.get_bind()
    for table in (NewsLight.__table__, MajorNewsLight.__table__):
        table.create(bind, checkfirst=True)


def _add_news(db_session, *, news_id: str, title: str | None, content: str | None, src: str = "eastmoney") -> None:
    db_session.add(
        NewsLight(
            row_key_hash=news_id,
            src=src,
            news_time=datetime(2026, 8, 23, 9, 45, tzinfo=timezone.utc),
            title=title,
            content=content,
            channels="宏观",
            score=None,
            source="tushare-source-must-not-leak",
            fetched_at=datetime(2026, 8, 23, 10, 0, tzinfo=timezone.utc),
        )
    )


def _add_major_news(
    db_session,
    *,
    news_id: str,
    title: str | None,
    content: str | None,
    original_url: str | None = "https://example.com/original",
    src: str = "cls",
) -> None:
    db_session.add(
        MajorNewsLight(
            row_key_hash=news_id,
            src=src,
            pub_time=datetime(2026, 8, 23, 9, 45, tzinfo=timezone.utc),
            title=title,
            content=content,
            url=original_url,
            source="tushare-source-must-not-leak",
            fetched_at=datetime(2026, 8, 23, 10, 0, tzinfo=timezone.utc),
        )
    )


@pytest.mark.parametrize(
    ("news_id", "content", "mode", "payload_key"),
    [
        ("reader-url", "https://example.com/news", "URL", "url"),
        ("reader-html", "<article><h1>标题</h1><p>正文</p></article>", "HTML", "html"),
        ("reader-text", "普通新闻正文", "TEXT", "content"),
    ],
)
def test_news_reader_endpoint_preserves_news_classification(
    app_client,
    db_session,
    news_id: str,
    content: str,
    mode: str,
    payload_key: str,
) -> None:
    _ensure_news_tables(db_session)
    _add_news(db_session, news_id=news_id, title="新闻标题", content=content)
    db_session.commit()

    response = app_client.get(f"/api/v1/wealth/market/news/items/news/{news_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["contentSource"] == "news"
    assert payload["readerMode"] == mode
    assert payload["source"] == "eastmoney"
    assert payload["originalUrl"] is None
    assert payload[payload_key] is not None
    assert sum(payload[key] is not None for key in ("url", "html", "content")) == 1


@pytest.mark.parametrize(
    ("news_id", "content", "expected_mode", "payload_key"),
    [
        ("major-html", "<article><p>通讯 HTML 正文</p></article>", "HTML", "html"),
        ("major-text", "通讯纯文本正文", "TEXT", "content"),
        ("major-url-text", "https://example.com/content-is-not-a-frame", "TEXT", "content"),
    ],
)
def test_major_news_reader_uses_database_content_not_original_url(
    app_client,
    db_session,
    news_id: str,
    content: str,
    expected_mode: str,
    payload_key: str,
) -> None:
    _ensure_news_tables(db_session)
    _add_major_news(db_session, news_id=news_id, title="新闻通讯标题", content=content)
    db_session.commit()

    response = app_client.get(f"/api/v1/wealth/market/news/items/major_news/{news_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["contentSource"] == "major_news"
    assert payload["readerMode"] == expected_mode
    assert payload[payload_key] == content
    assert payload["url"] is None
    assert payload["originalUrl"] == "https://example.com/original"


def test_news_reader_builds_fallback_title_only_for_news(app_client, db_session) -> None:
    _ensure_news_tables(db_session)
    _add_news(db_session, news_id="news-title", title="  ", content="<p>这是正文生成的标题</p>")
    _add_major_news(db_session, news_id="major-title", title="  ", content="<p>不能生成通讯标题</p>")
    db_session.commit()

    news_response = app_client.get("/api/v1/wealth/market/news/items/news/news-title")
    major_response = app_client.get("/api/v1/wealth/market/news/items/major_news/major-title")

    assert news_response.status_code == 200
    assert news_response.json()["title"] == "这是正文生成的标题"
    assert (major_response.status_code, major_response.json()["code"]) == (404, "NEWS_READER_NOT_FOUND")


@pytest.mark.parametrize(
    ("news_id", "raw_title", "content", "expected_title"),
    [
        (
            "reader-bracket-sample",
            "【商务部等9部门：支持航空保税维修绿色化发展】商务部等9部门发布关于促进航空保税维修高质量发展的意见",
            "新闻正文",
            "商务部等9部门：支持航空保税维修绿色化发展",
        ),
        ("reader-bracket-spaces", "  【 标题 】尾部摘要  ", "新闻正文", "标题"),
        ("reader-missing-close", "【缺少右括号", "新闻正文", "【缺少右括号"),
        ("reader-empty-bracket", "【】尾部摘要", "新闻正文", "【】尾部摘要"),
        ("reader-middle-bracket", "前缀【标题】尾部摘要", "新闻正文", "前缀【标题】尾部摘要"),
        ("reader-body-bracket", None, "【正文中的括号】不能反向提取", "【正文中的括号】不能反向提取"),
    ],
)
def test_news_reader_applies_news_display_title_contract(
    app_client,
    db_session,
    news_id: str,
    raw_title: str | None,
    content: str,
    expected_title: str,
) -> None:
    _ensure_news_tables(db_session)
    _add_news(db_session, news_id=news_id, title=raw_title, content=content)
    db_session.commit()

    response = app_client.get(f"/api/v1/wealth/market/news/items/news/{news_id}")

    assert response.status_code == 200
    assert response.json()["title"] == expected_title


def test_major_news_reader_does_not_extract_leading_bracket_title(app_client, db_session) -> None:
    _ensure_news_tables(db_session)
    _add_major_news(
        db_session,
        news_id="major-bracket-title",
        title="【新闻通讯标题】尾部保持原样",
        content="新闻通讯正文",
    )
    db_session.commit()

    response = app_client.get("/api/v1/wealth/market/news/items/major_news/major-bracket-title")

    assert response.status_code == 200
    assert response.json()["title"] == "【新闻通讯标题】尾部保持原样"


def test_major_news_reader_hides_sina_finance_source(app_client, db_session) -> None:
    _ensure_news_tables(db_session)
    _add_major_news(
        db_session,
        news_id="major-sina-filtered",
        title="新浪财经通讯不得展示",
        content="新浪财经正文",
        src=" 新浪财经 ",
    )
    db_session.commit()

    response = app_client.get("/api/v1/wealth/market/news/items/major_news/major-sina-filtered")

    assert (response.status_code, response.json()["code"]) == (404, "NEWS_READER_NOT_FOUND")


@pytest.mark.parametrize(
    ("news_id", "content", "expected_mode", "payload_key", "expected_body"),
    [
        (
            "major-ths-html-footer",
            '<article><p>正文主体</p><p class="bottomSign politics-hide"><a><strong>'
            "关注同花顺财经（ths518），获取更多机会"
            "</strong></a></p><span id=\"arctTailMark\"></span></article>",
            "HTML",
            "html",
            '<article><p>正文主体</p><p class="bottomSign politics-hide"><a><strong>'
            "</strong></a></p><span id=\"arctTailMark\"></span></article>",
        ),
        (
            "major-ths-text-footer",
            "正文主体\n关注同花顺财经（ths518），获取更多机会。",
            "TEXT",
            "content",
            "正文主体",
        ),
    ],
)
def test_major_news_reader_removes_ths_promotional_text(
    app_client,
    db_session,
    news_id: str,
    content: str,
    expected_mode: str,
    payload_key: str,
    expected_body: str,
) -> None:
    _ensure_news_tables(db_session)
    _add_major_news(
        db_session,
        news_id=news_id,
        title="同花顺通讯标题",
        content=content,
        src=" 同花顺 ",
    )
    db_session.commit()

    response = app_client.get(f"/api/v1/wealth/market/news/items/major_news/{news_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["readerMode"] == expected_mode
    assert payload[payload_key] == expected_body
    assert "关注同花顺财经" not in payload[payload_key]


def test_major_news_reader_keeps_same_text_for_other_sources(app_client, db_session) -> None:
    _ensure_news_tables(db_session)
    content = "正文主体\n关注同花顺财经（ths518），获取更多机会。"
    _add_major_news(
        db_session,
        news_id="major-cls-same-text",
        title="财联社通讯标题",
        content=content,
        src="财联社",
    )
    db_session.commit()

    response = app_client.get("/api/v1/wealth/market/news/items/major_news/major-cls-same-text")

    assert response.status_code == 200
    assert response.json()["content"] == content


def test_news_reader_does_not_fallback_across_sources(app_client, db_session) -> None:
    _ensure_news_tables(db_session)
    _add_news(db_session, news_id="news-only", title="快讯", content="快讯正文")
    _add_major_news(db_session, news_id="major-only", title="通讯", content="通讯正文")
    db_session.commit()

    missing_major = app_client.get("/api/v1/wealth/market/news/items/major_news/news-only")
    missing_news = app_client.get("/api/v1/wealth/market/news/items/news/major-only")

    assert (missing_major.status_code, missing_major.json()["code"]) == (404, "NEWS_READER_NOT_FOUND")
    assert (missing_news.status_code, missing_news.json()["code"]) == (404, "NEWS_READER_NOT_FOUND")


def test_news_reader_endpoint_maps_controlled_errors(app_client, db_session) -> None:
    _ensure_news_tables(db_session)
    ths_promotion = "关注同花顺财经（ths518），获取更多机会。"
    _add_news(db_session, news_id="reader-empty", title="空正文", content=" ")
    _add_news(db_session, news_id="reader-large", title="超大正文", content="中" * 90_000)
    _add_news(db_session, news_id="reader-invalid", title="非法地址", content="http:///missing-host")
    _add_major_news(
        db_session,
        news_id="major-empty-after-promotion",
        title="清理后空正文",
        content=ths_promotion,
        src="同花顺",
    )
    _add_major_news(
        db_session,
        news_id="major-large-before-promotion",
        title="清理前超大正文",
        content=ths_promotion * 5_000,
        src="同花顺",
    )
    db_session.commit()

    missing = app_client.get("/api/v1/wealth/market/news/items/news/not-found")
    empty = app_client.get("/api/v1/wealth/market/news/items/news/reader-empty")
    too_large = app_client.get("/api/v1/wealth/market/news/items/news/reader-large")
    invalid_content = app_client.get("/api/v1/wealth/market/news/items/news/reader-invalid")
    invalid_source = app_client.get("/api/v1/wealth/market/news/items/unknown/reader-empty")
    invalid_id = app_client.get("/api/v1/wealth/market/news/items/news/bad%24id")
    legacy_route = app_client.get("/api/v1/wealth/market/news/items/reader-empty")
    major_empty_after_promotion = app_client.get(
        "/api/v1/wealth/market/news/items/major_news/major-empty-after-promotion"
    )
    major_large_before_promotion = app_client.get(
        "/api/v1/wealth/market/news/items/major_news/major-large-before-promotion"
    )

    assert (missing.status_code, missing.json()["code"]) == (404, "NEWS_READER_NOT_FOUND")
    assert (empty.status_code, empty.json()["code"]) == (404, "NEWS_READER_NOT_FOUND")
    assert (too_large.status_code, too_large.json()["code"]) == (413, "NEWS_READER_CONTENT_TOO_LARGE")
    assert (invalid_content.status_code, invalid_content.json()["code"]) == (422, "NEWS_READER_CONTENT_INVALID")
    assert (invalid_source.status_code, invalid_source.json()["code"]) == (400, "NEWS_READER_REQUEST_INVALID")
    assert (invalid_id.status_code, invalid_id.json()["code"]) == (400, "NEWS_READER_REQUEST_INVALID")
    assert legacy_route.status_code == 404
    assert (major_empty_after_promotion.status_code, major_empty_after_promotion.json()["code"]) == (
        404,
        "NEWS_READER_NOT_FOUND",
    )
    assert (major_large_before_promotion.status_code, major_large_before_promotion.json()["code"]) == (
        413,
        "NEWS_READER_CONTENT_TOO_LARGE",
    )


def test_news_reader_endpoint_hides_unexpected_query_details(app_client, monkeypatch) -> None:
    def fail_query(*_args, **_kwargs):
        raise RuntimeError("sensitive table and SQL detail")

    monkeypatch.setattr(NewsReaderQueryService, "build_news_reader_item", fail_query)

    response = app_client.get("/api/v1/wealth/market/news/items/news/reader-query-failure")

    assert response.status_code == 500
    assert response.json()["code"] == "NEWS_READER_QUERY_FAILED"
    assert response.json()["message"] == "新闻内容加载失败"
    assert "sensitive" not in response.text


@pytest.mark.parametrize("content_source", ["news", "major_news"])
def test_news_reader_query_service_uses_one_source_specific_primary_key_statement(
    db_session,
    content_source: str,
) -> None:
    _ensure_news_tables(db_session)
    if content_source == "news":
        _add_news(db_session, news_id="one-query", title="单次查询", content="正文")
    else:
        _add_major_news(db_session, news_id="one-query", title="单次查询", content="正文")
    db_session.commit()
    statements: list[str] = []
    bind = db_session.get_bind()

    def capture_statement(_connection, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(statement)

    event.listen(bind, "before_cursor_execute", capture_statement)
    try:
        item = NewsReaderQueryService().build_news_reader_item(
            db_session,
            content_source=cast(NewsContentSourceValue, content_source),
            news_id="one-query",
        )
    finally:
        event.remove(bind, "before_cursor_execute", capture_statement)

    assert item.newsId == "one-query"
    assert len(statements) == 1
    normalized_sql = " ".join(statements[0].lower().split())
    assert f"core_serving_light.{content_source}" in normalized_sql
    assert "limit" in normalized_sql
    other_table = "major_news" if content_source == "news" else "news"
    assert f"core_serving_light.{other_table}." not in normalized_sql


def test_news_reader_backend_keeps_major_original_url_inactive() -> None:
    root = Path(__file__).resolve().parents[2]
    files = [
        root / "src/biz/api/wealth/market/news_item.py",
        root / "src/biz/queries/wealth/market/news/news_reader_query.py",
        root / "src/biz/queries/wealth/market/news/major_news_reader_query.py",
        root / "src/biz/queries/wealth/market/news/news_reader_query_service.py",
        root / "src/biz/services/wealth/market/news/news_reader_content_resolver.py",
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in files)
    resolver_source = files[-1].read_text(encoding="utf-8")
    major_resolver = resolver_source.split("def resolve_major_news_reader_content", maxsplit=1)[1].split(
        "def _validate_nonempty_and_size",
        maxsplit=1,
    )[0]

    for forbidden in ("httpx", "requests", "urlopen", "duckdb", "dagster", "lake_root"):
        assert forbidden not in source.lower()
    assert "classify_news_reader_mode" not in major_resolver
