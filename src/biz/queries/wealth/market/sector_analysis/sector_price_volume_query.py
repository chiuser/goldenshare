from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorDataQueryError,
)
from src.biz.services.wealth.market.sector_analysis.sector_price_volume_contract import (
    SectorPriceVolumeDailyFact,
)
from src.foundation.models.core.dc_daily import DcDaily
from src.foundation.models.core.trade_calendar import TradeCalendar


class SectorPriceVolumeQuery:
    """Bounded raw inputs for price-volume calculation; no date admission audit."""

    @staticmethod
    def load_open_dates(
        session: Session,
        *,
        end_date: date,
        count: int,
    ) -> tuple[date, ...]:
        if count <= 0 or count > 119:
            raise SectorDataQueryError("open-date window must be between 1 and 119")
        rows = session.scalars(
            select(TradeCalendar.trade_date)
            .where(
                TradeCalendar.exchange == "SSE",
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date <= end_date,
            )
            .order_by(TradeCalendar.trade_date.desc())
            .limit(count)
        ).all()
        return tuple(reversed(rows))

    @staticmethod
    def load_facts(
        session: Session,
        *,
        sector_codes: tuple[str, ...],
        start_date: date,
        end_date: date,
    ) -> tuple[SectorPriceVolumeDailyFact, ...]:
        if not sector_codes:
            return ()
        rows = session.execute(
            select(
                DcDaily.ts_code,
                DcDaily.trade_date,
                DcDaily.close,
                DcDaily.pct_change,
                DcDaily.amount,
            )
            .where(
                DcDaily.category == "行业板块",
                DcDaily.ts_code.in_(sector_codes),
                DcDaily.trade_date.between(start_date, end_date),
            )
            .order_by(DcDaily.trade_date, DcDaily.ts_code)
        ).all()
        facts = tuple(
            SectorPriceVolumeDailyFact(
                sector_code=row.ts_code,
                trade_date=row.trade_date,
                close=row.close,
                pct_change=row.pct_change,
                amount=row.amount,
            )
            for row in rows
        )
        keys = tuple((item.sector_code, item.trade_date) for item in facts)
        if len(keys) != len(set(keys)):
            raise SectorDataQueryError("price-volume facts contain duplicate business keys")
        return facts
