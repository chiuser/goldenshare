from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawBiyingStockBasic(Base):
    __tablename__ = "stock_basic"
    __table_args__ = {"schema": "raw_biying"}

    dm: Mapped[str] = mapped_column(String(16), primary_key=True)
    mc: Mapped[str | None] = mapped_column(String(64))
    jys: Mapped[str | None] = mapped_column(String(16))
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'stock_basic'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
