from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class EquityMoneyflow(TimestampMixin, Base):
    __tablename__ = "equity_moneyflow"
    __table_args__ = (
        Index("idx_equity_moneyflow_trade_date", "trade_date"),
        Index("idx_equity_moneyflow_net_mf_amount_trade_date", "trade_date", "net_mf_amount"),
        {"schema": "core"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    buy_sm_vol: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    buy_sm_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    sell_sm_vol: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    sell_sm_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    buy_md_vol: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    buy_md_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    sell_md_vol: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    sell_md_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    buy_lg_vol: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    buy_lg_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    sell_lg_vol: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    sell_lg_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    buy_elg_vol: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    buy_elg_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    sell_elg_vol: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    sell_elg_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    net_mf_vol: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    net_mf_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
