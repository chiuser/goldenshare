from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class BoardMoneyflowDc(TimestampMixin, Base):
    __tablename__ = "board_moneyflow_dc"
    __table_args__ = (
        Index("idx_board_moneyflow_dc_trade_date", "trade_date"),
        Index("idx_board_moneyflow_dc_content_type_trade_date", "content_type", "trade_date"),
        {"schema": "core_serving"},
    )

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    content_type: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    ts_code: Mapped[str | None] = mapped_column(String(16))
    pct_change: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    close: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    net_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    net_amount_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    buy_elg_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    buy_elg_amount_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    buy_lg_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    buy_lg_amount_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    buy_md_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    buy_md_amount_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    buy_sm_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    buy_sm_amount_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    buy_sm_amount_stock: Mapped[str | None] = mapped_column(String(128))
    rank: Mapped[int | None] = mapped_column(Integer)
