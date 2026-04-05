from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class ThsMember(TimestampMixin, Base):
    __tablename__ = "ths_member"
    __table_args__ = (
        Index("idx_ths_member_con_code", "con_code"),
        Index("idx_ths_member_is_new", "is_new"),
        {"schema": "core"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    con_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    con_name: Mapped[str | None] = mapped_column(String(128))
    weight: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    in_date: Mapped[date | None] = mapped_column(Date)
    out_date: Mapped[date | None] = mapped_column(Date)
    is_new: Mapped[str | None] = mapped_column(String(8))
