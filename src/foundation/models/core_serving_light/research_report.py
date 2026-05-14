from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class ResearchReportLight(Base):
    __tablename__ = "research_report"
    __table_args__ = {"schema": "core_serving_light"}

    row_key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    report_code: Mapped[str | None] = mapped_column(String(64))
    trade_date: Mapped[date | None] = mapped_column(Date)
    abstr: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    report_type: Mapped[str | None] = mapped_column(String(32))
    author: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(String(128))
    ts_code: Mapped[str | None] = mapped_column(String(32))
    inst_csname: Mapped[str | None] = mapped_column(String(128))
    ind_name: Mapped[str | None] = mapped_column(String(128))
    url: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
