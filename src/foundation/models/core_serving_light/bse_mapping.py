from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class BseMappingLight(Base):
    __tablename__ = "bse_mapping"
    __table_args__ = {"schema": "core_serving_light"}

    o_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    n_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(128))
    list_date: Mapped[date | None] = mapped_column(Date)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
