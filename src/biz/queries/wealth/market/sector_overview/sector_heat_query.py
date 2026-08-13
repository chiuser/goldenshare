from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.models.core_serving.wealth_sector_heat_daily import WealthSectorHeatDaily


@dataclass(frozen=True, slots=True)
class SectorHeatRow:
    trade_date: date
    sector_code: str
    sector_name: str
    heat_status: str
    invalid_reason: str | None
    heat_score: Decimal | None
    heat_rank: int | None
    heat_level: str
    heat_delta_1d: Decimal | None
    heat_trend: str
    source_member_count: int
    member_count: int
    suspended_count: int
    quote_eligible_count: int
    valid_quote_count: int
    missing_quote_count: int
    quote_coverage: Decimal
    score_version: str
    source_dates_json: dict[str, object]
    calculated_at: datetime

    def source_matches_trade_date(self) -> bool:
        return self.source_dates_json.get("target") == self.trade_date.isoformat()


class SectorHeatQuery:
    """Read already-materialized concept Heat; never calculate Heat in a Web request."""

    _COLUMNS = (
        WealthSectorHeatDaily.trade_date,
        WealthSectorHeatDaily.sector_code,
        WealthSectorHeatDaily.sector_name,
        WealthSectorHeatDaily.heat_status,
        WealthSectorHeatDaily.invalid_reason,
        WealthSectorHeatDaily.heat_score,
        WealthSectorHeatDaily.heat_rank,
        WealthSectorHeatDaily.heat_level,
        WealthSectorHeatDaily.heat_delta_1d,
        WealthSectorHeatDaily.heat_trend,
        WealthSectorHeatDaily.source_member_count,
        WealthSectorHeatDaily.member_count,
        WealthSectorHeatDaily.suspended_count,
        WealthSectorHeatDaily.quote_eligible_count,
        WealthSectorHeatDaily.valid_quote_count,
        WealthSectorHeatDaily.missing_quote_count,
        WealthSectorHeatDaily.quote_coverage,
        WealthSectorHeatDaily.score_version,
        WealthSectorHeatDaily.source_dates_json,
        WealthSectorHeatDaily.calculated_at,
    )

    def load_for_date(
        self,
        session: Session,
        *,
        trade_date: date,
        sector_codes: tuple[str, ...] | None = None,
    ) -> dict[str, SectorHeatRow]:
        if sector_codes == ():
            return {}
        statement = select(*self._COLUMNS).where(WealthSectorHeatDaily.trade_date == trade_date)
        if sector_codes is not None:
            statement = statement.where(WealthSectorHeatDaily.sector_code.in_(sector_codes))
        rows = session.execute(statement.order_by(WealthSectorHeatDaily.sector_code))
        return {row.sector_code: self._map(row) for row in rows}

    def load_history(
        self,
        session: Session,
        *,
        trade_date: date,
        sector_code: str,
        limit: int = 20,
    ) -> list[SectorHeatRow]:
        rows = list(
            session.execute(
                select(*self._COLUMNS)
                .where(
                    WealthSectorHeatDaily.sector_code == sector_code,
                    WealthSectorHeatDaily.trade_date <= trade_date,
                )
                .order_by(WealthSectorHeatDaily.trade_date.desc())
                .limit(limit)
            )
        )
        return [self._map(row) for row in reversed(rows)]

    @staticmethod
    def _map(row: object) -> SectorHeatRow:
        return SectorHeatRow(
            trade_date=row.trade_date,
            sector_code=row.sector_code,
            sector_name=row.sector_name,
            heat_status=row.heat_status,
            invalid_reason=row.invalid_reason,
            heat_score=row.heat_score,
            heat_rank=row.heat_rank,
            heat_level=row.heat_level,
            heat_delta_1d=row.heat_delta_1d,
            heat_trend=row.heat_trend,
            source_member_count=int(row.source_member_count),
            member_count=int(row.member_count),
            suspended_count=int(row.suspended_count),
            quote_eligible_count=int(row.quote_eligible_count),
            valid_quote_count=int(row.valid_quote_count),
            missing_quote_count=int(row.missing_quote_count),
            quote_coverage=row.quote_coverage,
            score_version=row.score_version,
            source_dates_json=dict(row.source_dates_json),
            calculated_at=row.calculated_at,
        )
