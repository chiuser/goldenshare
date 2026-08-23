from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class NewsReaderItemDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    newsId: str
    title: str
    source: str | None
    publishTime: datetime
    readerMode: Literal["URL", "HTML", "TEXT"]
    url: str | None
    html: str | None
    content: str | None

    @model_validator(mode="after")
    def validate_exclusive_payload(self) -> "NewsReaderItemDto":
        payloads = {"URL": self.url, "HTML": self.html, "TEXT": self.content}
        if payloads[self.readerMode] is None:
            raise ValueError("reader payload is missing")
        if any(value is not None for mode, value in payloads.items() if mode != self.readerMode):
            raise ValueError("reader payloads must be mutually exclusive")
        return self
