from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import and_, func, literal, select
from sqlalchemy.orm import Session

from src.biz.services.wealth.market.sector_analysis.sector_member_breadth_contract import (
    DuplicateMemberBreadthFactError,
    MemberBreadthWindowRelationsFact,
    MemberMarketFact,
    MemberRelationFact,
    SectorMemberBreadthQueryError,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorSelectionInvalidError,
)
from src.foundation.models.core.dc_daily import DcDaily
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.dc_member import DcMember
from src.foundation.models.core_serving.equity_adj_factor import EquityAdjFactor
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar


_POSITIVE_INFINITY = Decimal("Infinity")
_NEGATIVE_INFINITY = Decimal("-Infinity")
_MAX_OPEN_DATE_COUNT = 119


class SectorMemberBreadthQuery:
    """Bounded set reads for membership, daily bars and adjustment factors."""

    @staticmethod
    def load_window_relations(
        session: Session,
        *,
        target_date: date,
        coverage_end_date: date,
        hierarchy_sector_codes: tuple[str, ...],
        relation_sector_codes: tuple[str, ...],
        open_date_count: int,
        relation_date_count: int,
    ) -> MemberBreadthWindowRelationsFact:
        if not hierarchy_sector_codes or not relation_sector_codes:
            raise SectorMemberBreadthQueryError("member breadth code pool is empty")
        if not 1 <= open_date_count <= _MAX_OPEN_DATE_COUNT:
            raise SectorSelectionInvalidError(
                "成员广度交易日窗口必须在 1 到 119 日之间"
            )
        if not 1 <= relation_date_count <= open_date_count:
            raise SectorSelectionInvalidError("成员关系日期窗口不合法")
        if target_date > coverage_end_date:
            raise SectorSelectionInvalidError("tradeDate 晚于公共业务日期")

        valid_daily = and_(
            DcDaily.category == "行业板块",
            DcDaily.ts_code.in_(hierarchy_sector_codes),
            DcDaily.trade_date <= coverage_end_date,
            DcDaily.close.is_not(None),
            DcDaily.close > 0,
            DcDaily.close < _POSITIVE_INFINITY,
            DcDaily.pct_change.is_not(None),
            DcDaily.pct_change > _NEGATIVE_INFINITY,
            DcDaily.pct_change < _POSITIVE_INFINITY,
        )
        coverage_start = (
            select(func.min(DcDaily.trade_date)).where(valid_daily).scalar_subquery()
        )
        open_dates = (
            select(TradeCalendar.trade_date.label("trade_date"))
            .where(
                TradeCalendar.exchange == "SSE",
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date <= target_date,
            )
            .order_by(TradeCalendar.trade_date.desc())
            .limit(open_date_count)
            .cte("member_breadth_open_dates")
        )
        relation_dates = (
            select(open_dates.c.trade_date)
            .order_by(open_dates.c.trade_date.desc())
            .limit(relation_date_count)
            .cte("member_breadth_relation_dates")
        )
        rows = session.execute(
            select(
                open_dates.c.trade_date,
                coverage_start.label("coverage_start_date"),
                DcMember.ts_code.label("sector_code"),
                DcMember.con_code.label("stock_code"),
                DcMember.name.label("stock_name"),
            )
            .select_from(open_dates)
            .outerjoin(
                DcMember,
                and_(
                    DcMember.trade_date == open_dates.c.trade_date,
                    DcMember.trade_date.in_(select(relation_dates.c.trade_date)),
                    DcMember.ts_code.in_(relation_sector_codes),
                ),
            )
            .order_by(
                open_dates.c.trade_date,
                DcMember.ts_code,
                DcMember.con_code,
            )
        ).all()
        if not rows:
            raise SectorSelectionInvalidError("tradeDate 之前没有 SSE 开市日")
        coverage_start_date = rows[0].coverage_start_date
        if coverage_start_date is None:
            raise SectorMemberBreadthQueryError("industry daily coverage is empty")

        returned_open_dates = tuple(dict.fromkeys(row.trade_date for row in rows))
        if returned_open_dates[-1] != target_date:
            raise SectorSelectionInvalidError("tradeDate 必须是 SSE 开市日")
        if target_date < coverage_start_date:
            raise SectorSelectionInvalidError("tradeDate 早于公共行业行情覆盖起点")
        returned_relation_dates = returned_open_dates[-relation_date_count:]

        relations: list[MemberRelationFact] = []
        seen_relation_keys: set[tuple[date, str, str]] = set()
        for row in rows:
            if row.sector_code is None or row.stock_code is None:
                continue
            key = (row.trade_date, row.sector_code, row.stock_code)
            if key in seen_relation_keys:
                raise DuplicateMemberBreadthFactError(
                    "duplicate member breadth relation fact"
                )
            seen_relation_keys.add(key)
            relations.append(
                MemberRelationFact(
                    sector_code=row.sector_code,
                    trade_date=row.trade_date,
                    stock_code=row.stock_code,
                    stock_name=(
                        row.stock_name.strip()
                        if row.stock_name and row.stock_name.strip()
                        else None
                    ),
                )
            )
        return MemberBreadthWindowRelationsFact(
            coverage_start_date=coverage_start_date,
            coverage_end_date=coverage_end_date,
            open_dates=returned_open_dates,
            relation_dates=returned_relation_dates,
            relations=tuple(relations),
        )

    @staticmethod
    def load_market_facts(
        session: Session,
        *,
        stock_codes: tuple[str, ...],
        start_date: date,
        end_date: date,
        include_adj_factor: bool,
    ) -> tuple[MemberMarketFact, ...]:
        if not stock_codes:
            return ()
        adj_factor_column = (
            EquityAdjFactor.adj_factor
            if include_adj_factor
            else literal(None).label("adj_factor")
        )
        statement = select(
            EquityDailyBar.ts_code,
            EquityDailyBar.trade_date,
            EquityDailyBar.close,
            EquityDailyBar.pct_chg,
            EquityDailyBar.amount,
            adj_factor_column,
        ).where(
            EquityDailyBar.ts_code.in_(stock_codes),
            EquityDailyBar.trade_date >= start_date,
            EquityDailyBar.trade_date <= end_date,
        )
        if include_adj_factor:
            statement = statement.outerjoin(
                EquityAdjFactor,
                and_(
                    EquityAdjFactor.ts_code == EquityDailyBar.ts_code,
                    EquityAdjFactor.trade_date == EquityDailyBar.trade_date,
                ),
            )
        rows = session.execute(
            statement.order_by(EquityDailyBar.trade_date, EquityDailyBar.ts_code)
        ).all()
        facts: list[MemberMarketFact] = []
        seen_keys: set[tuple[str, date]] = set()
        for row in rows:
            key = (row.ts_code, row.trade_date)
            if key in seen_keys:
                raise DuplicateMemberBreadthFactError(
                    "duplicate member breadth market fact"
                )
            seen_keys.add(key)
            facts.append(
                MemberMarketFact(
                    stock_code=row.ts_code,
                    trade_date=row.trade_date,
                    close=row.close,
                    pct_change=row.pct_chg,
                    amount_thousand_yuan=row.amount,
                    adj_factor=row.adj_factor,
                )
            )
        return tuple(facts)
