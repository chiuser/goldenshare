from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from .news_common import NewsContentSourceValue


class NewsReaderItemDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    newsId: str
    contentSource: NewsContentSourceValue
    title: str
    source: str | None
    publishTime: datetime
    readerMode: Literal["URL", "HTML", "TEXT"]
    url: str | None
    html: str | None
    content: str | None
    originalUrl: str | None = None

    @model_validator(mode="after")
    def validate_exclusive_payload(self) -> "NewsReaderItemDto":
        payloads = {"URL": self.url, "HTML": self.html, "TEXT": self.content}
        if payloads[self.readerMode] is None:
            raise ValueError("reader payload is missing")
        if any(value is not None for mode, value in payloads.items() if mode != self.readerMode):
            raise ValueError("reader payloads must be mutually exclusive")
        if self.contentSource == "news" and self.originalUrl is not None:
            raise ValueError("news items cannot expose an original URL")
        if self.contentSource == "major_news":
            if self.readerMode == "URL" or self.url is not None:
                raise ValueError("major news items cannot use URL reader mode")
        return self
