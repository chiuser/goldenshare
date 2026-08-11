from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Index, Integer, String, Text, desc
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class EquityExpress(Base):
    __tablename__ = "equity_express"
    __table_args__ = (
        Index("idx_equity_express_ann_date_ts_code", desc("ann_date"), "ts_code"),
        Index("idx_equity_express_ts_code_end_ann", "ts_code", desc("end_date"), desc("ann_date")),
        Index("idx_equity_express_end_date_ts_code", desc("end_date"), "ts_code"),
        {"schema": "core_serving"},
    )

    source_entity_key: Mapped[str] = mapped_column(Text, primary_key=True)
    source_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    identity_basis: Mapped[str] = mapped_column(Text, nullable=False)
    ts_code: Mapped[str] = mapped_column(Text, nullable=False)
    ann_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    revenue: Mapped[float | None] = mapped_column(Float)
    operate_profit: Mapped[float | None] = mapped_column(Float)
    total_profit: Mapped[float | None] = mapped_column(Float)
    n_income: Mapped[float | None] = mapped_column(Float)
    total_assets: Mapped[float | None] = mapped_column(Float)
    total_hldr_eqy_exc_min_int: Mapped[float | None] = mapped_column(Float)
    diluted_eps: Mapped[float | None] = mapped_column(Float)
    diluted_roe: Mapped[float | None] = mapped_column(Float)
    yoy_net_profit: Mapped[float | None] = mapped_column(Float)
    bps: Mapped[float | None] = mapped_column(Float)
    yoy_sales: Mapped[float | None] = mapped_column(Float)
    yoy_op: Mapped[float | None] = mapped_column(Float)
    yoy_tp: Mapped[float | None] = mapped_column(Float)
    yoy_dedu_np: Mapped[float | None] = mapped_column(Float)
    yoy_eps: Mapped[float | None] = mapped_column(Float)
    yoy_roe: Mapped[float | None] = mapped_column(Float)
    growth_assets: Mapped[float | None] = mapped_column(Float)
    yoy_equity: Mapped[float | None] = mapped_column(Float)
    growth_bps: Mapped[float | None] = mapped_column(Float)
    or_last_year: Mapped[float | None] = mapped_column(Float)
    op_last_year: Mapped[float | None] = mapped_column(Float)
    tp_last_year: Mapped[float | None] = mapped_column(Float)
    np_last_year: Mapped[float | None] = mapped_column(Float)
    eps_last_year: Mapped[float | None] = mapped_column(Float)
    open_net_assets: Mapped[float | None] = mapped_column(Float)
    open_bps: Mapped[float | None] = mapped_column(Float)
    perf_summary: Mapped[str | None] = mapped_column(Text)
    is_audit: Mapped[int | None] = mapped_column(Integer)
    remark: Mapped[str | None] = mapped_column(Text)
    update_flag: Mapped[str | None] = mapped_column(Text)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
