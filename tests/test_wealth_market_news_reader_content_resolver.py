from __future__ import annotations

import pytest

from src.biz.services.wealth.market.news.news_reader_content_resolver import (
    NEWS_READER_MAX_CONTENT_BYTES,
    NewsReaderContentEmptyError,
    NewsReaderContentInvalidError,
    NewsReaderContentTooLargeError,
    classify_news_reader_mode,
    resolve_news_reader_content,
)


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("https://example.com/news?id=1", "URL"),
        ("  HTTP://EXAMPLE.COM/news  ", "URL"),
        ("<article><p>正文</p></article>", "HTML"),
        ("<!doctype html><html><body>正文</body></html>", "HTML"),
        ("市场说明 https://example.com/news", "TEXT"),
        ("1 < 2 且 3 > 2", "TEXT"),
        ("javascript:alert(1)", "TEXT"),
        ("普通新闻正文", "TEXT"),
    ],
)
def test_classify_news_reader_mode(content: str, expected: str) -> None:
    assert classify_news_reader_mode(content) == expected


def test_resolved_payloads_are_mutually_exclusive() -> None:
    url = resolve_news_reader_content("https://example.com/news")
    html = resolve_news_reader_content("<p>新闻正文</p>")
    text = resolve_news_reader_content("新闻正文")

    assert (url.url, url.html, url.content) == ("https://example.com/news", None, None)
    assert (html.url, html.html, html.content) == (None, "<p>新闻正文</p>", None)
    assert (text.url, text.html, text.content) == (None, None, "新闻正文")


def test_empty_and_too_large_content_fail_closed() -> None:
    with pytest.raises(NewsReaderContentEmptyError):
        resolve_news_reader_content(" \n ")
    with pytest.raises(NewsReaderContentTooLargeError):
        resolve_news_reader_content("中" * (NEWS_READER_MAX_CONTENT_BYTES // 3 + 1))


def test_http_shape_without_host_is_invalid() -> None:
    with pytest.raises(NewsReaderContentInvalidError):
        resolve_news_reader_content("http:///missing-host")
