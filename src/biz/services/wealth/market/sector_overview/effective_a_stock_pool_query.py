from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping, Sequence

from sqlalchemy import and_, case, distinct, func, select
from sqlalchemy.orm import Session

from src.foundation.models.core.dc_member import DcMember
from src.foundation.models.core.equity_limit_list import EquityLimitList
from src.foundation.models.core.equity_suspend_d import EquitySuspendD
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.security_serving import Security

from .sector_heat_contract import SectorPoolCounts


@dataclass(frozen=True, slots=True)
class EffectiveAStockPoolSnapshot:
    trade_date: date
    sector_code: str
    counts: SectorPoolCounts
    up_count: int
    limit_up_count: int
    down_count: int = 0


class EffectiveAStockPoolQuery:
    """Build all effective-pool counts from one bounded relational aggregate."""

    def load(
        self,
        session: Session,
        *,
        ordered_trade_dates: Sequence[date],
        sector_codes_by_date: Mapping[date, Sequence[str]],
    ) -> dict[tuple[date, str], EffectiveAStockPoolSnapshot]:
        trade_dates = tuple(ordered_trade_dates)
        all_sector_codes = tuple(sorted({code for codes in sector_codes_by_date.values() for code in codes}))
        if not trade_dates or not all_sector_codes:
            return {}

        source_members = (
            select(
                DcMember.trade_date.label("trade_date"),
                DcMember.ts_code.label("sector_code"),
                DcMember.con_code.label("stock_code"),
            )
            .where(DcMember.trade_date.in_(trade_dates), DcMember.ts_code.in_(all_sector_codes))
            .distinct()
            .cte("sector_source_members")
        )
        member_stock_dates = (
            select(
                source_members.c.trade_date,
                source_members.c.stock_code,
            )
            .distinct()
            .cte("sector_member_stock_dates")
        )
        suspended = (
            select(EquitySuspendD.trade_date.label("trade_date"), EquitySuspendD.ts_code.label("stock_code"))
            .join(
                member_stock_dates,
                and_(
                    member_stock_dates.c.trade_date == EquitySuspendD.trade_date,
                    member_stock_dates.c.stock_code == EquitySuspendD.ts_code,
                ),
            )
            .where(EquitySuspendD.suspend_type == "S")
            .distinct()
            .cte("sector_suspended_members")
        )
        valid_bars = (
            select(
                EquityDailyBar.trade_date.label("trade_date"),
                EquityDailyBar.ts_code.label("stock_code"),
                EquityDailyBar.pct_chg.label("pct_chg"),
            )
            .join(
                member_stock_dates,
                and_(
                    member_stock_dates.c.trade_date == EquityDailyBar.trade_date,
                    member_stock_dates.c.stock_code == EquityDailyBar.ts_code,
                ),
            )
            .where(EquityDailyBar.pct_chg.is_not(None))
            .cte("sector_valid_bars")
        )
        limit_ups = (
            select(EquityLimitList.trade_date.label("trade_date"), EquityLimitList.ts_code.label("stock_code"))
            .join(
                member_stock_dates,
                and_(
                    member_stock_dates.c.trade_date == EquityLimitList.trade_date,
                    member_stock_dates.c.stock_code == EquityLimitList.ts_code,
                ),
            )
            .where(EquityLimitList.limit_type == "U")
            .distinct()
            .cte("sector_limit_ups")
        )
        eligible_join = and_(
            Security.ts_code == source_members.c.stock_code,
            Security.security_type == "EQUITY",
            Security.curr_type == "CNY",
            Security.list_status.in_(("L", "D")),
            Security.list_date.is_not(None),
            Security.list_date <= source_members.c.trade_date,
            (Security.delist_date.is_(None) | (Security.delist_date > source_members.c.trade_date)),
        )
        from_clause = (
            source_members.outerjoin(Security, eligible_join)
            .outerjoin(
                suspended,
                and_(
                    suspended.c.trade_date == source_members.c.trade_date,
                    suspended.c.stock_code == source_members.c.stock_code,
                ),
            )
            .outerjoin(
                valid_bars,
                and_(
                    valid_bars.c.trade_date == source_members.c.trade_date,
                    valid_bars.c.stock_code == source_members.c.stock_code,
                ),
            )
            .outerjoin(
                limit_ups,
                and_(
                    limit_ups.c.trade_date == source_members.c.trade_date,
                    limit_ups.c.stock_code == source_members.c.stock_code,
                ),
            )
        )
        eligible_stock = case((Security.ts_code.is_not(None), source_members.c.stock_code))
        suspended_stock = case(
            (and_(Security.ts_code.is_not(None), suspended.c.stock_code.is_not(None)), source_members.c.stock_code)
        )
        quote_eligible_stock = case(
            (and_(Security.ts_code.is_not(None), suspended.c.stock_code.is_(None)), source_members.c.stock_code)
        )
        valid_quote_stock = case(
            (
                and_(
                    Security.ts_code.is_not(None),
                    suspended.c.stock_code.is_(None),
                    valid_bars.c.stock_code.is_not(None),
                ),
                source_members.c.stock_code,
            )
        )
        up_stock = case(
            (
                and_(
                    Security.ts_code.is_not(None),
                    suspended.c.stock_code.is_(None),
                    valid_bars.c.stock_code.is_not(None),
                    valid_bars.c.pct_chg > 0,
                ),
                source_members.c.stock_code,
            )
        )
        down_stock = case(
            (
                and_(
                    Security.ts_code.is_not(None),
                    suspended.c.stock_code.is_(None),
                    valid_bars.c.stock_code.is_not(None),
                    valid_bars.c.pct_chg < 0,
                ),
                source_members.c.stock_code,
            )
        )
        limit_up_stock = case(
            (
                and_(
                    Security.ts_code.is_not(None),
                    suspended.c.stock_code.is_(None),
                    valid_bars.c.stock_code.is_not(None),
                    limit_ups.c.stock_code.is_not(None),
                ),
                source_members.c.stock_code,
            )
        )
        statement = (
            select(
                source_members.c.trade_date,
                source_members.c.sector_code,
                func.count(distinct(source_members.c.stock_code)).label("source_member_count"),
                func.count(distinct(eligible_stock)).label("member_count"),
                func.count(distinct(suspended_stock)).label("suspended_count"),
                func.count(distinct(quote_eligible_stock)).label("quote_eligible_count"),
                func.count(distinct(valid_quote_stock)).label("valid_quote_count"),
                func.count(distinct(up_stock)).label("up_count"),
                func.count(distinct(down_stock)).label("down_count"),
                func.count(distinct(limit_up_stock)).label("limit_up_count"),
            )
            .select_from(from_clause)
            .group_by(source_members.c.trade_date, source_members.c.sector_code)
        )
        aggregated = {
            (row.trade_date, row.sector_code): row
            for row in session.execute(statement)
        }
        snapshots: dict[tuple[date, str], EffectiveAStockPoolSnapshot] = {}
        for trade_date in trade_dates:
            for sector_code in sorted(set(sector_codes_by_date.get(trade_date, ()))):
                row = aggregated.get((trade_date, sector_code))
                source_member_count = int(row.source_member_count) if row is not None else 0
                member_count = int(row.member_count) if row is not None else 0
                suspended_count = int(row.suspended_count) if row is not None else 0
                quote_eligible_count = int(row.quote_eligible_count) if row is not None else 0
                valid_quote_count = int(row.valid_quote_count) if row is not None else 0
                missing_quote_count = quote_eligible_count - valid_quote_count
                quote_coverage = valid_quote_count / quote_eligible_count if quote_eligible_count else 0.0
                snapshots[(trade_date, sector_code)] = EffectiveAStockPoolSnapshot(
                    trade_date=trade_date,
                    sector_code=sector_code,
                    counts=SectorPoolCounts(
                        source_member_count=source_member_count,
                        member_count=member_count,
                        suspended_count=suspended_count,
                        quote_eligible_count=quote_eligible_count,
                        valid_quote_count=valid_quote_count,
                        missing_quote_count=missing_quote_count,
                        quote_coverage=quote_coverage,
                    ),
                    up_count=int(row.up_count) if row is not None else 0,
                    limit_up_count=int(row.limit_up_count) if row is not None else 0,
                    down_count=int(row.down_count) if row is not None else 0,
                )
        return snapshots
