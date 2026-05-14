from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class RawResearchReport(Base):
    __tablename__ = "research_report"
    __table_args__ = (
        Index("uq_raw_tushare_research_report_row_key_hash", "row_key_hash", unique=True),
        Index(
            "uq_raw_tushare_research_report_report_code",
            "report_code",
            unique=True,
            postgresql_where=text("report_code IS NOT NULL"),
        ),
        Index("idx_raw_tushare_research_report_trade_date", "trade_date"),
        Index("idx_raw_tushare_research_report_ts_code_date", "ts_code", "trade_date"),
        Index("idx_raw_tushare_research_report_inst_date", "inst_csname", "trade_date"),
        Index("idx_raw_tushare_research_report_type_date", "report_type", "trade_date"),
        {"schema": "raw_tushare"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    row_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    report_code: Mapped[str | None] = mapped_column(String(64))
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    abstr: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    report_type: Mapped[str] = mapped_column(String(32), nullable=False)
    author: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(String(128))
    ts_code: Mapped[str | None] = mapped_column(String(32))
    inst_csname: Mapped[str] = mapped_column(String(128), nullable=False)
    ind_name: Mapped[str | None] = mapped_column(String(128))
    url: Mapped[str] = mapped_column(Text, nullable=False)
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'research_report'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
