from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, Index, Integer, JSON, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.base import Base


_JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")
_INVALID_REASONS = (
    "MEMBER_COUNT_LOW",
    "QUOTE_ELIGIBLE_COUNT_ZERO",
    "QUOTE_COVERAGE_LOW",
    "HISTORY_INSUFFICIENT",
    "FEATURE_MISSING",
)
_INVALID_REASON_SQL = ", ".join(f"'{reason}'" for reason in _INVALID_REASONS)


class WealthSectorHeatDaily(Base):
    __tablename__ = "wealth_sector_heat_daily"
    __table_args__ = (
        CheckConstraint(
            "heat_status IN ('VALID', 'INVALID')",
            name="heat_status_allowed",
        ),
        CheckConstraint(
            f"(heat_status = 'VALID' AND invalid_reason IS NULL) OR "
            f"(heat_status = 'INVALID' AND invalid_reason IN ({_INVALID_REASON_SQL}))",
            name="status_reason_consistent",
        ),
        CheckConstraint(
            "heat_level IN ('BOILING', 'HOT', 'ACTIVE', 'NONE')",
            name="heat_level_allowed",
        ),
        CheckConstraint(
            "heat_trend IN ('HEATING', 'STABLE', 'COOLING', 'UNKNOWN')",
            name="heat_trend_allowed",
        ),
        CheckConstraint(
            "raw_heat_trend IN ('HEATING', 'STABLE', 'COOLING', 'UNKNOWN')",
            name="raw_heat_trend_allowed",
        ),
        CheckConstraint(
            "heat_status <> 'VALID' OR ("
            "base_heat_score IS NOT NULL AND base_heat_rank IS NOT NULL "
            "AND heat_score IS NOT NULL AND heat_rank IS NOT NULL "
            "AND price_strength_score IS NOT NULL AND breadth_score IS NOT NULL "
            "AND capital_flow_score IS NOT NULL AND activity_score IS NOT NULL "
            "AND persistence_score IS NOT NULL)",
            name="valid_metrics_present",
        ),
        CheckConstraint(
            "heat_status <> 'INVALID' OR ("
            "heat_score IS NULL AND heat_rank IS NULL AND heat_level = 'NONE' "
            "AND heat_delta_1d IS NULL AND heat_trend = 'UNKNOWN' "
            "AND raw_heat_trend = 'UNKNOWN')",
            name="invalid_outputs_empty",
        ),
        CheckConstraint(
            "(base_heat_score IS NULL OR base_heat_score BETWEEN 0 AND 100) "
            "AND (heat_score IS NULL OR heat_score BETWEEN 0 AND 100)",
            name="heat_scores_range",
        ),
        CheckConstraint(
            "(price_strength_score IS NULL OR price_strength_score BETWEEN 0 AND 1) "
            "AND (breadth_score IS NULL OR breadth_score BETWEEN 0 AND 1) "
            "AND (capital_flow_score IS NULL OR capital_flow_score BETWEEN 0 AND 1) "
            "AND (activity_score IS NULL OR activity_score BETWEEN 0 AND 1) "
            "AND (persistence_score IS NULL OR persistence_score BETWEEN 0 AND 1) "
            "AND quote_coverage BETWEEN 0 AND 1",
            name="component_scores_range",
        ),
        CheckConstraint(
            "(base_heat_rank IS NULL OR base_heat_rank > 0) "
            "AND (heat_rank IS NULL OR heat_rank > 0)",
            name="heat_ranks_positive",
        ),
        CheckConstraint(
            "source_member_count >= 0 AND member_count >= 0 AND suspended_count >= 0 "
            "AND quote_eligible_count >= 0 AND valid_quote_count >= 0 "
            "AND missing_quote_count >= 0",
            name="member_counts_non_negative",
        ),
        CheckConstraint(
            "suspended_count <= member_count",
            name="suspended_count_within_members",
        ),
        CheckConstraint(
            "quote_eligible_count = member_count - suspended_count",
            name="quote_eligible_count_consistent",
        ),
        CheckConstraint(
            "valid_quote_count <= quote_eligible_count",
            name="valid_quote_count_within_eligible",
        ),
        CheckConstraint(
            "missing_quote_count = quote_eligible_count - valid_quote_count",
            name="missing_quote_count_consistent",
        ),
        CheckConstraint(
            "config_hash ~ '^[0-9a-f]{64}$'",
            name="config_hash_sha256",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "source_hash ~ '^[0-9a-f]{64}$'",
            name="source_hash_sha256",
        ).ddl_if(dialect="postgresql"),
        {"schema": "core_serving"},
    )

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    sector_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    sector_name: Mapped[str] = mapped_column(String(128), nullable=False)
    heat_status: Mapped[str] = mapped_column(String(16), nullable=False)
    invalid_reason: Mapped[str | None] = mapped_column(String(64))
    base_heat_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    base_heat_rank: Mapped[int | None] = mapped_column(Integer)
    heat_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    heat_rank: Mapped[int | None] = mapped_column(Integer)
    heat_level: Mapped[str] = mapped_column(String(16), nullable=False)
    heat_delta_1d: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    heat_trend: Mapped[str] = mapped_column(String(16), nullable=False)
    raw_heat_trend: Mapped[str] = mapped_column(String(16), nullable=False)
    price_strength_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    breadth_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    capital_flow_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    activity_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    persistence_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    source_member_count: Mapped[int] = mapped_column(Integer, nullable=False)
    member_count: Mapped[int] = mapped_column(Integer, nullable=False)
    suspended_count: Mapped[int] = mapped_column(Integer, nullable=False)
    quote_eligible_count: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_quote_count: Mapped[int] = mapped_column(Integer, nullable=False)
    missing_quote_count: Mapped[int] = mapped_column(Integer, nullable=False)
    quote_coverage: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    score_version: Mapped[str] = mapped_column(String(64), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_dates_json: Mapped[dict[str, object]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    source_row_counts_json: Mapped[dict[str, object]] = mapped_column(_JSON_DOCUMENT, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


Index(
    "idx_wealth_sector_heat_daily_trade_score_code",
    WealthSectorHeatDaily.trade_date,
    WealthSectorHeatDaily.heat_score.desc(),
    WealthSectorHeatDaily.sector_code,
)
Index(
    "idx_wealth_sector_heat_daily_trade_delta_code",
    WealthSectorHeatDaily.trade_date,
    WealthSectorHeatDaily.heat_delta_1d.desc(),
    WealthSectorHeatDaily.sector_code,
)
Index(
    "idx_wealth_sector_heat_daily_sector_trade",
    WealthSectorHeatDaily.sector_code,
    WealthSectorHeatDaily.trade_date.desc(),
)
