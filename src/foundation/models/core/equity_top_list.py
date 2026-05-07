from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class EquityTopList(TimestampMixin, Base):
    __tablename__ = "equity_top_list"
    __table_args__ = (
        Index("idx_equity_top_list_trade_date", "trade_date"),
        Index(
            "uq_equity_top_list_ts_code_trade_date_reason_hash",
            "ts_code",
            "trade_date",
            "reason_hash",
            unique=True,
        ),
        {"schema": "core_serving"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    reason: Mapped[str] = mapped_column(Text, primary_key=True)
    reason_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    selected_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    variant_count: Mapped[int] = mapped_column(nullable=False)
    resolution_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str | None] = mapped_column(String(64))
    close: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    pct_chg: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    turnover_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    l_sell: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    l_buy: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    l_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    net_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    net_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    amount_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    float_values: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
