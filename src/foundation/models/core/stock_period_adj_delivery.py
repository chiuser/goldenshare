"""Immutable plans and per-unit business commits for adjusted week/month bars."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, Identity, Index, Integer, JSON, SmallInteger, String, Text, UniqueConstraint, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class StockPeriodAdjDelivery(Base):
    __tablename__ = 'stock_period_adj_delivery'
    __table_args__ = (
        UniqueConstraint('batch_id', 'record_kind', 'unit_id', name='uq_stock_period_adj_delivery_unit'),
        CheckConstraint("record_kind IN ('plan_unit','plan_frozen','unit','batch_closed')", name='stock_period_adj_kind'),
        CheckConstraint("freq IN ('week','month') AND contract_version = 1", name='stock_period_adj_contract'),
        Index('uq_stock_period_adj_frozen_intent', 'intent_key', unique=True,
              postgresql_where=text("record_kind='plan_frozen'"), sqlite_where=text("record_kind='plan_frozen'")),
        Index('idx_stock_period_adj_business_date', 'purpose', 'freq', 'business_date', 'record_kind'),
        Index('idx_stock_period_adj_period_date', 'freq', 'period_date', 'record_kind'),
        {'schema': 'core'},
    )
    revision: Mapped[int] = mapped_column(BigInteger().with_variant(Integer(), 'sqlite'), Identity(), primary_key=True)
    contract_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    batch_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    intent_key: Mapped[str] = mapped_column(Text, nullable=False)
    record_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    unit_id: Mapped[str] = mapped_column(String(128), nullable=False)
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    freq: Mapped[str] = mapped_column(String(8), nullable=False)
    business_date: Mapped[date | None] = mapped_column(Date)
    period_date: Mapped[date | None] = mapped_column(Date)
    ts_code: Mapped[str | None] = mapped_column(String(16))
    contract_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON().with_variant(JSONB(), 'postgresql'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
