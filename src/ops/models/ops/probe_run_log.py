from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


class ProbeRunLog(Base):
    __tablename__ = "probe_run_log"
    __table_args__ = (
        Index("idx_probe_run_log_rule_probed_at", "probe_rule_id", "probed_at"),
        Index("idx_probe_run_log_status_probed_at", "status", "probed_at"),
        {"schema": "ops"},
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    probe_rule_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    condition_matched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    message: Mapped[str | None] = mapped_column(Text)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    probed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    triggered_task_run_id: Mapped[int | None] = mapped_column(BigInteger)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    result_code: Mapped[str] = mapped_column(String(32), nullable=False, default="miss", server_default="miss")
    result_reason: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
