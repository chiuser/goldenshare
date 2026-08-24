from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit


NewsReaderMode = Literal["URL", "HTML", "TEXT"]
NEWS_READER_MAX_CONTENT_BYTES = 256 * 1024
NEWS_READER_URL_PATTERN = r"(?is)^https?://[^\s]+$"
NEWS_READER_HTML_PATTERN = (
    r"(?is)<(?:!doctype\s+html|html\b|head\b|body\b|article\b|section\b|"
    r"div\b|p\b|h[1-6]\b|ul\b|ol\b|li\b|table\b|blockquote\b|br\b)[^>]*>"
)


class NewsReaderContentError(ValueError):
    pass


class NewsReaderContentEmptyError(NewsReaderContentError):
    pass


class NewsReaderContentInvalidError(NewsReaderContentError):
    pass


class NewsReaderContentTooLargeError(NewsReaderContentError):
    pass


@dataclass(frozen=True, slots=True)
class ResolvedNewsReaderContent:
    mode: NewsReaderMode
    url: str | None
    html: str | None
    content: str | None


def classify_news_reader_mode(content: str) -> NewsReaderMode:
    text = content.strip()
    if re.fullmatch(NEWS_READER_URL_PATTERN, text):
        parsed = urlsplit(text)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            raise NewsReaderContentInvalidError("news URL is invalid")
        return "URL"
    if re.search(NEWS_READER_HTML_PATTERN, text):
        return "HTML"
    return "TEXT"


def resolve_news_reader_content(content: str | None) -> ResolvedNewsReaderContent:
    text = _validate_nonempty_and_size(content)
    mode = classify_news_reader_mode(text)
    if mode == "URL":
        return ResolvedNewsReaderContent(mode=mode, url=text, html=None, content=None)
    if mode == "HTML":
        return ResolvedNewsReaderContent(mode=mode, url=None, html=text, content=None)
    return ResolvedNewsReaderContent(mode=mode, url=None, html=None, content=text)


def resolve_major_news_reader_content(content: str | None) -> ResolvedNewsReaderContent:
    text = _validate_nonempty_and_size(content)
    if re.search(NEWS_READER_HTML_PATTERN, text):
        return ResolvedNewsReaderContent(mode="HTML", url=None, html=text, content=None)
    return ResolvedNewsReaderContent(mode="TEXT", url=None, html=None, content=text)


def _validate_nonempty_and_size(content: str | None) -> str:
    if content is None or not content.strip():
        raise NewsReaderContentEmptyError("news content is empty")
    text = content.strip()
    if len(text.encode("utf-8")) > NEWS_READER_MAX_CONTENT_BYTES:
        raise NewsReaderContentTooLargeError("news content exceeds the size limit")
    return text
