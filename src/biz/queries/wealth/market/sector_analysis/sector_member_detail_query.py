from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.biz.services.wealth.market.sector_analysis.sector_member_detail_contract import (
    SectorMemberDailyFact,
    SectorMemberSourceFact,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorScopeInvalidError,
)
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.dc_member import DcMember
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar


class SectorMemberDetailQuery:
    """Read the complete source membership and its bounded daily-bar window."""

    @staticmethod
    def load_open_window(
        session: Session,
        *,
        trade_date: date,
        period: int,
    ) -> tuple[date, ...]:
        rows = session.scalars(
            select(TradeCalendar.trade_date)
            .where(
                TradeCalendar.exchange == "SSE",
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date <= trade_date,
            )
            .order_by(TradeCalendar.trade_date.desc())
            .limit(period)
        ).all()
        if not rows or rows[0] != trade_date:
            raise SectorScopeInvalidError("tradeDate 必须是 SSE 开市日")
        return tuple(reversed(rows))

    @staticmethod
    def load_members(
        session: Session,
        *,
        trade_date: date,
        sector_code: str,
    ) -> tuple[SectorMemberSourceFact, ...]:
        rows = session.execute(
            select(DcMember.con_code, DcMember.name)
            .where(
                DcMember.trade_date == trade_date,
                DcMember.ts_code == sector_code,
            )
            .order_by(DcMember.con_code)
        ).all()
        return tuple(
            SectorMemberSourceFact(
                stock_code=row.con_code,
                stock_name=row.name.strip() if row.name and row.name.strip() else None,
            )
            for row in rows
        )

    @staticmethod
    def load_daily_facts(
        session: Session,
        *,
        stock_codes: tuple[str, ...],
        open_dates: tuple[date, ...],
    ) -> tuple[SectorMemberDailyFact, ...]:
        if not stock_codes or not open_dates:
            return ()
        rows = session.execute(
            select(
                EquityDailyBar.ts_code,
                EquityDailyBar.trade_date,
                EquityDailyBar.close,
                EquityDailyBar.pct_chg,
            )
            .where(
                EquityDailyBar.ts_code.in_(stock_codes),
                EquityDailyBar.trade_date.in_(open_dates),
            )
            .order_by(EquityDailyBar.trade_date, EquityDailyBar.ts_code)
        ).all()
        return tuple(
            SectorMemberDailyFact(
                stock_code=row.ts_code,
                trade_date=row.trade_date,
                close=row.close,
                pct_change=row.pct_chg,
            )
            for row in rows
        )
