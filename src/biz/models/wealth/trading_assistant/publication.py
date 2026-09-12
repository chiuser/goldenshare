"""Sealed daily summaries and direct publication manifests, design §4.24."""
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKeyConstraint, LargeBinary, Numeric, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base
from .accounts import finite_numeric


class AccountSnapshot(Base):
    __tablename__ = "wealth_ta_account_snapshot"
    __table_args__ = (
        ForeignKeyConstraint(["account_id", "trade_date", "day_result_id"],
            ["app.wealth_ta_day_result.account_id", "app.wealth_ta_day_result.trade_date",
             "app.wealth_ta_day_result.day_result_id"], ondelete="RESTRICT"),
        CheckConstraint("(cash_amount IS NULL AND total_assets IS NULL) OR "
            "(cash_amount IS NOT NULL AND total_assets IS NOT NULL AND cash_amount >= 0 AND "
            "total_assets = cash_amount + stock_market_value)", name="cash_history"),
        CheckConstraint("closed_trade_count >= 0 AND current_buy_input >= 0 AND stock_market_value >= 0 "
            "AND cash_in_amount >= 0 AND cash_out_amount >= 0 AND estimated_sell_commission >= 0 "
            "AND estimated_stamp_tax >= 0", name="nonnegative"),
        CheckConstraint("dynamic_cost_amount = current_buy_input - current_sell_net AND "
            "estimated_net_proceeds = stock_market_value - estimated_sell_commission - estimated_stamp_tax "
            "AND holding_profit_amount = current_sell_net + estimated_net_proceeds - current_buy_input", name="valuation"),
        CheckConstraint("(current_buy_input > 0 AND holding_return_pct IS NOT NULL) OR "
            "(current_buy_input = 0 AND holding_return_pct IS NULL AND holding_profit_amount = 0)", name="holding_return"),
        CheckConstraint("(day_profit_amount IS NULL AND day_capital_amount IS NULL AND day_return_pct IS NULL) OR "
            "(day_profit_amount IS NOT NULL AND day_capital_amount IS NOT NULL AND day_capital_amount > 0 "
            "AND day_return_pct IS NOT NULL)", name="day_return"),
        *(CheckConstraint(finite_numeric(column), name=column) for column in (
            "cash_amount", "stock_market_value", "total_assets", "cash_in_amount", "cash_out_amount",
            "current_buy_input", "current_sell_net", "dynamic_cost_amount", "estimated_sell_commission",
            "estimated_stamp_tax", "estimated_net_proceeds", "holding_profit_amount", "holding_return_pct",
            "day_profit_amount", "day_capital_amount", "day_return_pct", "closed_profit_amount")),
        {"schema": "app"},
    )
    account_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    day_result_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date)
    valuation_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cash_amount: Mapped[Decimal | None] = mapped_column(Numeric)
    stock_market_value: Mapped[Decimal] = mapped_column(Numeric)
    total_assets: Mapped[Decimal | None] = mapped_column(Numeric)
    cash_in_amount: Mapped[Decimal] = mapped_column(Numeric)
    cash_out_amount: Mapped[Decimal] = mapped_column(Numeric)
    current_buy_input: Mapped[Decimal] = mapped_column(Numeric)
    current_sell_net: Mapped[Decimal] = mapped_column(Numeric)
    dynamic_cost_amount: Mapped[Decimal] = mapped_column(Numeric)
    estimated_sell_commission: Mapped[Decimal] = mapped_column(Numeric)
    estimated_stamp_tax: Mapped[Decimal] = mapped_column(Numeric)
    estimated_net_proceeds: Mapped[Decimal] = mapped_column(Numeric)
    holding_profit_amount: Mapped[Decimal] = mapped_column(Numeric)
    holding_return_pct: Mapped[Decimal | None] = mapped_column(Numeric)
    day_profit_amount: Mapped[Decimal | None] = mapped_column(Numeric)
    day_capital_amount: Mapped[Decimal | None] = mapped_column(Numeric)
    day_return_pct: Mapped[Decimal | None] = mapped_column(Numeric)
    closed_trade_count: Mapped[int] = mapped_column(BigInteger)
    closed_profit_amount: Mapped[Decimal] = mapped_column(Numeric)


class PublicationDay(Base):
    __tablename__ = "wealth_ta_publication_day"
    __table_args__ = (
        ForeignKeyConstraint(["account_id", "generation_id"],
            ["app.wealth_ta_calculation_generation.account_id", "app.wealth_ta_calculation_generation.generation_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["account_id", "trade_date", "day_result_id"],
            ["app.wealth_ta_day_result.account_id", "app.wealth_ta_day_result.trade_date",
             "app.wealth_ta_day_result.day_result_id"], ondelete="RESTRICT"),
        {"schema": "app"},
    )
    account_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    generation_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    day_result_id: Mapped[UUID] = mapped_column(Uuid)


class PublicationReceipt(Base):
    __tablename__ = "wealth_ta_publication_receipt"
    __table_args__ = (
        ForeignKeyConstraint(["account_id", "generation_id"],
            ["app.wealth_ta_calculation_generation.account_id", "app.wealth_ta_calculation_generation.generation_id"], ondelete="RESTRICT"),
        CheckConstraint("target_version >= 1 AND day_count >= 0 AND octet_length(manifest_digest) = 32", name="receipt"),
        {"schema": "app"},
    )
    account_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    generation_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    target_version: Mapped[int] = mapped_column(BigInteger)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    manifest_digest: Mapped[bytes] = mapped_column(LargeBinary)
    day_count: Mapped[int] = mapped_column(BigInteger)
