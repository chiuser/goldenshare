from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base, TimestampMixin


class UsSecurity(TimestampMixin, Base):
    __tablename__ = "us_security"
    __table_args__ = (
        Index("idx_us_security_name", "name"),
        Index("idx_us_security_classify", "classify"),
        Index("idx_us_security_list_date", "list_date"),
        {"schema": "core_serving"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(128))
    enname: Mapped[str | None] = mapped_column(String(256))
    classify: Mapped[str | None] = mapped_column(String(16))
    list_date: Mapped[date | None] = mapped_column(Date)
    delist_date: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="tushare", server_default="tushare")
