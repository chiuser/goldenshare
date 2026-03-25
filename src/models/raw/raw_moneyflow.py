from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class RawMoneyflow(Base):
    __tablename__ = "moneyflow"
    __table_args__ = {"schema": "raw"}

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    buy_sm_vol: Mapped[float | None] = mapped_column(Numeric(20, 4))
    buy_sm_amount: Mapped[float | None] = mapped_column(Numeric(20, 4))
    sell_sm_vol: Mapped[float | None] = mapped_column(Numeric(20, 4))
    sell_sm_amount: Mapped[float | None] = mapped_column(Numeric(20, 4))
    buy_md_vol: Mapped[float | None] = mapped_column(Numeric(20, 4))
    buy_md_amount: Mapped[float | None] = mapped_column(Numeric(20, 4))
    sell_md_vol: Mapped[float | None] = mapped_column(Numeric(20, 4))
    sell_md_amount: Mapped[float | None] = mapped_column(Numeric(20, 4))
    buy_lg_vol: Mapped[float | None] = mapped_column(Numeric(20, 4))
    buy_lg_amount: Mapped[float | None] = mapped_column(Numeric(20, 4))
    sell_lg_vol: Mapped[float | None] = mapped_column(Numeric(20, 4))
    sell_lg_amount: Mapped[float | None] = mapped_column(Numeric(20, 4))
    buy_elg_vol: Mapped[float | None] = mapped_column(Numeric(20, 4))
    buy_elg_amount: Mapped[float | None] = mapped_column(Numeric(20, 4))
    sell_elg_vol: Mapped[float | None] = mapped_column(Numeric(20, 4))
    sell_elg_amount: Mapped[float | None] = mapped_column(Numeric(20, 4))
    net_mf_vol: Mapped[float | None] = mapped_column(Numeric(20, 4))
    net_mf_amount: Mapped[float | None] = mapped_column(Numeric(20, 4))
    api_name: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'moneyflow'"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    raw_payload: Mapped[str | None] = mapped_column(Text)
