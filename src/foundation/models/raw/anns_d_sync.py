"""Announcement business completion receipts and persistent request budgets."""
from datetime import date, datetime
from uuid import UUID
from sqlalchemy import BigInteger, Date, DateTime, String, Uuid, JSON, text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB
from src.foundation.models.base import Base


class AnnsDSyncUnit(Base):
    __tablename__ = 'anns_d_sync_unit'
    __table_args__ = {'schema': 'raw_tushare'}
    execution_token: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    contract_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    ann_date: Mapped[date] = mapped_column(Date, primary_key=True)
    attempt_token: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    terminal_page_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    terminal_offset: Mapped[int] = mapped_column(BigInteger, nullable=False)
    terminal_rows: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rows_observed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rows_committed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason_counts: Mapped[dict] = mapped_column(JSONB, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text('now()'))


class AnnsDSyncRequestBudget(Base):
    __tablename__ = 'anns_d_sync_request_budget'
    __table_args__ = {'schema': 'raw_tushare'}
    execution_token: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    contract_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    issued_requests: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text('0'))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text('now()'))
