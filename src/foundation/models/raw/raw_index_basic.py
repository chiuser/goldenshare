from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawIndexBasic(Base):
    __tablename__ = "index_basic"
    __table_args__ = {"schema": "raw_tushare"}

    ts_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(128))
    fullname: Mapped[str | None] = mapped_column(String(256))
    market: Mapped[str | None] = mapped_column(String(32))
    publisher: Mapped[str | None] = mapped_column(String(128))
    index_type: Mapped[str | None] = mapped_column(String(32))
    category: Mapped[str | None] = mapped_column(String(64))
    base_date: Mapped[str | None] = mapped_column(String(16))
    base_point: Mapped[float | None] = mapped_column(Numeric(20, 4))
    list_date: Mapped[str | None] = mapped_column(String(16))
    weight_rule: Mapped[str | None] = mapped_column(String(128))
    desc: Mapped[str | None] = mapped_column(Text)
    exp_date: Mapped[str | None] = mapped_column(String(16))
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'index_basic'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
