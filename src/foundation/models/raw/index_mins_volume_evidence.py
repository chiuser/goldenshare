from datetime import date

from sqlalchemy import CheckConstraint, Date, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class IndexMinsVolumeEvidence(Base):
    __tablename__ = "index_mins_volume_evidence"
    __table_args__ = (
        CheckConstraint("source_unit IN ('share', 'lot')", name="ck_index_mins_volume_source_unit"),
        {"schema": "raw_tushare"},
    )

    ts_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    freq: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    source_vol: Mapped[float] = mapped_column(Float(53), nullable=False)
    source_unit: Mapped[str] = mapped_column(String(5), nullable=False)
