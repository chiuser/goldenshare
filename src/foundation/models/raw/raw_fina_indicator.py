from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, Numeric, PrimaryKeyConstraint, String, desc, text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.datasets.fina_indicator_contracts import FINA_INDICATOR_DECIMAL_FIELDS
from src.foundation.models.base import Base


class RawFinaIndicator(Base):
    __tablename__ = "fina_indicator"
    __table_args__ = (
        PrimaryKeyConstraint(
            "ts_code",
            "ann_date",
            "end_date",
            "update_flag",
            name="pk_raw_tushare_fina_indicator",
        ),
        Index("idx_raw_tushare_fina_indicator_ann_date_ts_code", "ann_date", "ts_code"),
        Index(
            "idx_raw_tushare_fina_indicator_ts_code_end_ann_update",
            "ts_code",
            desc("end_date"),
            desc("ann_date"),
            "update_flag",
        ),
        {"schema": "raw_tushare"},
    )

    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
    ann_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    # The source contract contains 163 nullable numeric indicators. Building
    # the mapped columns from that contract prevents the ORM from drifting from
    # the fields explicitly requested from Tushare.
    locals().update(
        {
            field_name: mapped_column(Numeric(), nullable=True)
            for field_name in FINA_INDICATOR_DECIMAL_FIELDS
        }
    )

    update_flag: Mapped[str] = mapped_column(String(8), nullable=False)
    source_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    api_name: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'fina_indicator_vip'"),
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


__all__ = ["RawFinaIndicator"]
