from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import event

from src.biz.queries.wealth.market.news.news_reader_query_service import NewsReaderQueryService
from src.foundation.models.core_serving_light.news import NewsLight


def _ensure_news_table(db_session) -> None:
    NewsLight.__table__.create(db_session.get_bind(), checkfirst=True)


def _add_news(
    db_session,
    *,
    news_id: str,
    title: str | None,
    content: str | None,
    src: str = "eastmoney",
) -> None:
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


@pytest.mark.parametrize(
    ("news_id", "content", "mode", "payload_key"),
    [
        ("reader-url", "https://example.com/news", "URL", "url"),
        ("reader-html", "<article><h1>标题</h1><p>正文</p></article>", "HTML", "html"),
        ("reader-text", "普通新闻正文", "TEXT", "content"),
    ],
)
def test_news_reader_endpoint_returns_one_exclusive_payload(
    app_client,
    db_session,
    news_id: str,
    content: str,
    mode: str,
    payload_key: str,
) -> None:
    _ensure_news_table(db_session)
    _add_news(db_session, news_id=news_id, title="新闻标题", content=content)
    db_session.commit()

    response = app_client.get(f"/api/v1/wealth/market/news/items/{news_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["readerMode"] == mode
    assert payload["source"] == "eastmoney"
    assert payload[payload_key] is not None
    assert sum(payload[key] is not None for key in ("url", "html", "content")) == 1


def test_news_reader_endpoint_builds_title_from_content(app_client, db_session) -> None:
    _ensure_news_table(db_session)
    _add_news(
        db_session,
        news_id="reader-title",
        title="  ",
        content="<article><p>这是正文生成的标题</p></article>",
    )
    db_session.commit()

    response = app_client.get("/api/v1/wealth/market/news/items/reader-title")

    assert response.status_code == 200
    assert response.json()["title"] == "这是正文生成的标题"


def test_news_reader_endpoint_maps_controlled_errors(app_client, db_session) -> None:
    _ensure_news_table(db_session)
    _add_news(db_session, news_id="reader-empty", title="空正文", content=" ")
    _add_news(db_session, news_id="reader-large", title="超大正文", content="中" * 90_000)
    _add_news(db_session, news_id="reader-invalid", title="非法地址", content="http:///missing-host")
    db_session.commit()

    missing = app_client.get("/api/v1/wealth/market/news/items/not-found")
    empty = app_client.get("/api/v1/wealth/market/news/items/reader-empty")
    too_large = app_client.get("/api/v1/wealth/market/news/items/reader-large")
    invalid_content = app_client.get("/api/v1/wealth/market/news/items/reader-invalid")
    invalid_id = app_client.get("/api/v1/wealth/market/news/items/bad%24id")

    assert (missing.status_code, missing.json()["code"]) == (404, "NEWS_READER_NOT_FOUND")
    assert (empty.status_code, empty.json()["code"]) == (404, "NEWS_READER_NOT_FOUND")
    assert (too_large.status_code, too_large.json()["code"]) == (413, "NEWS_READER_CONTENT_TOO_LARGE")
    assert (invalid_content.status_code, invalid_content.json()["code"]) == (422, "NEWS_READER_CONTENT_INVALID")
    assert (invalid_id.status_code, invalid_id.json()["code"]) == (400, "NEWS_READER_REQUEST_INVALID")


def test_news_reader_endpoint_hides_unexpected_query_details(app_client, monkeypatch) -> None:
    def fail_query(*_args, **_kwargs):
        raise RuntimeError("sensitive table and SQL detail")

    monkeypatch.setattr(NewsReaderQueryService, "build_news_reader_item", fail_query)

    response = app_client.get("/api/v1/wealth/market/news/items/reader-query-failure")

    assert response.status_code == 500
    payload = response.json()
    assert payload["code"] == "NEWS_READER_QUERY_FAILED"
    assert payload["message"] == "新闻内容加载失败"
    assert "sensitive" not in response.text


def test_news_reader_query_service_uses_one_primary_key_statement(db_session) -> None:
    _ensure_news_table(db_session)
    _add_news(db_session, news_id="reader-one-query", title="单次查询", content="正文")
    db_session.commit()
    statements: list[str] = []
    bind = db_session.get_bind()

    def capture_statement(_connection, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(statement)

    event.listen(bind, "before_cursor_execute", capture_statement)
    try:
        item = NewsReaderQueryService().build_news_reader_item(db_session, news_id="reader-one-query")
    finally:
        event.remove(bind, "before_cursor_execute", capture_statement)

    assert item.newsId == "reader-one-query"
    assert len(statements) == 1
    normalized_sql = " ".join(statements[0].lower().split())
    assert "where core_serving_light.news.row_key_hash =" in normalized_sql
    assert "limit" in normalized_sql


def test_news_reader_backend_does_not_add_remote_fetch_or_lake_dependencies() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    files = [
        root / "src/biz/api/wealth/market/news_item.py",
        root / "src/biz/queries/wealth/market/news/news_reader_query.py",
        root / "src/biz/queries/wealth/market/news/news_reader_query_service.py",
        root / "src/biz/services/wealth/market/news/news_reader_content_resolver.py",
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in files)
    for forbidden in ("httpx", "requests", "urlopen", "duckdb", "dagster", "lake_root"):
        assert forbidden not in source.lower()
