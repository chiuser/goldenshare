from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class BakBasicLight(Base):
    __tablename__ = "bak_basic"
    __table_args__ = {"schema": "core_serving_light"}

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(64))
    industry: Mapped[str | None] = mapped_column(String(64))
    area: Mapped[str | None] = mapped_column(String(64))
    pe: Mapped[float | None] = mapped_column(Float)
    float_share: Mapped[float | None] = mapped_column(Float)
    total_share: Mapped[float | None] = mapped_column(Float)
    total_assets: Mapped[float | None] = mapped_column(Float)
    liquid_assets: Mapped[float | None] = mapped_column(Float)
    fixed_assets: Mapped[float | None] = mapped_column(Float)
    reserved: Mapped[float | None] = mapped_column(Float)
    reserved_pershare: Mapped[float | None] = mapped_column(Float)
    eps: Mapped[float | None] = mapped_column(Float)
    bvps: Mapped[float | None] = mapped_column(Float)
    pb: Mapped[float | None] = mapped_column(Float)
    list_date: Mapped[date | None] = mapped_column(Date)
    undp: Mapped[float | None] = mapped_column(Float)
    per_undp: Mapped[float | None] = mapped_column(Float)
    rev_yoy: Mapped[float | None] = mapped_column(Float)
    profit_yoy: Mapped[float | None] = mapped_column(Float)
    gpr: Mapped[float | None] = mapped_column(Float)
    npr: Mapped[float | None] = mapped_column(Float)
    holder_num: Mapped[int | None] = mapped_column(Integer)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
