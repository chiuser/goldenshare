from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import and_, case, func, or_, select, true
from sqlalchemy.orm import Session

from src.biz.services.wealth.market.sector_analysis.sector_member_breadth_contract import (
    DuplicateMemberBreadthFactError,
    MemberBreadthMemberProjectionFact,
    SectorMemberBreadthQueryError,
    SectorMemberBreadthReason,
    ordered_member_breadth_reasons,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import (
    SectorSelectionInvalidError,
)
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.dc_member import DcMember
from src.foundation.models.core_serving.equity_adj_factor import EquityAdjFactor
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar

_POSITIVE_INFINITY = Decimal("Infinity")
_NEGATIVE_INFINITY = Decimal("-Infinity")


class SectorMemberBreadthQuery:
    """Read only the selected day's complete members and bounded stock MA inputs."""

    @staticmethod
    def load_member_projection(
        session: Session,
        *,
        sector_code: str,
        target_date: date,
        ma_period: int,
    ) -> tuple[MemberBreadthMemberProjectionFact, ...]:
        if not sector_code:
            raise SectorMemberBreadthQueryError("member breadth selection is empty")
        if ma_period not in (5, 10, 15, 20, 30, 60):
            raise SectorSelectionInvalidError("成员广度均线周期不合法")
        open_date_rows = (
            select(TradeCalendar.trade_date.label("trade_date"))
            .where(
                TradeCalendar.exchange == "SSE",
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date <= target_date,
            )
            .order_by(TradeCalendar.trade_date.desc())
            .limit(ma_period)
            .cte("member_breadth_projection_open_dates")
        )
        relation_members = (
            select(
                DcMember.trade_date.label("trade_date"),
                DcMember.con_code.label("stock_code"),
                DcMember.name.label("stock_name"),
            )
            .where(DcMember.ts_code == sector_code, DcMember.trade_date == target_date)
            .cte("member_breadth_projection_relations")
        )
        stock_pool = (
            select(relation_members.c.stock_code)
            .distinct()
            .cte("member_breadth_projection_stock_pool")
        )
        market_present = EquityDailyBar.ts_code.is_not(None)
        pct_finite = and_(
            EquityDailyBar.pct_chg.is_not(None),
            EquityDailyBar.pct_chg > _NEGATIVE_INFINITY,
            EquityDailyBar.pct_chg < _POSITIVE_INFINITY,
        )
        amount_finite = and_(
            EquityDailyBar.amount.is_not(None),
            EquityDailyBar.amount > _NEGATIVE_INFINITY,
            EquityDailyBar.amount < _POSITIVE_INFINITY,
        )
        amount_valid = and_(amount_finite, EquityDailyBar.amount >= 0)
        close_valid = and_(
            market_present,
            EquityDailyBar.close.is_not(None),
            EquityDailyBar.close > 0,
            EquityDailyBar.close < _POSITIVE_INFINITY,
        )
        factor_finite = and_(
            EquityAdjFactor.adj_factor.is_not(None),
            EquityAdjFactor.adj_factor > _NEGATIVE_INFINITY,
            EquityAdjFactor.adj_factor < _POSITIVE_INFINITY,
        )
        factor_valid = and_(factor_finite, EquityAdjFactor.adj_factor > 0)
        adjusted_valid = and_(close_valid, factor_valid)
        grid = (
            select(
                stock_pool.c.stock_code,
                open_date_rows.c.trade_date,
                case((market_present, 1), else_=0).label("market_present"),
                case((and_(market_present, pct_finite), 1), else_=0).label("pct_valid"),
                case((and_(market_present, amount_finite), 1), else_=0).label(
                    "amount_finite"
                ),
                case((and_(market_present, amount_valid), 1), else_=0).label(
                    "amount_valid"
                ),
                EquityDailyBar.pct_chg.label("pct_change"),
                EquityDailyBar.amount.label("amount_thousand_yuan"),
                case(
                    (
                        adjusted_valid,
                        EquityDailyBar.close * EquityAdjFactor.adj_factor,
                    ),
                    else_=None,
                ).label("adjusted_basis"),
                case((~close_valid, 1), else_=0).label("ma_market_invalid"),
                case((and_(close_valid, ~factor_finite), 1), else_=0).label(
                    "ma_factor_missing"
                ),
                case(
                    (
                        and_(
                            close_valid,
                            factor_finite,
                            EquityAdjFactor.adj_factor <= 0,
                        ),
                        1,
                    ),
                    else_=0,
                ).label("ma_factor_non_positive"),
            )
            .select_from(stock_pool.join(open_date_rows, true()))
            .outerjoin(
                EquityDailyBar,
                and_(
                    EquityDailyBar.ts_code == stock_pool.c.stock_code,
                    EquityDailyBar.trade_date == open_date_rows.c.trade_date,
                ),
            )
            .outerjoin(
                EquityAdjFactor,
                and_(
                    EquityAdjFactor.ts_code == stock_pool.c.stock_code,
                    EquityAdjFactor.trade_date == open_date_rows.c.trade_date,
                ),
            )
            .cte("member_breadth_projection_market_grid")
        )
        window_args = {
            "partition_by": grid.c.stock_code,
            "order_by": grid.c.trade_date,
            "rows": (1 - ma_period, 0),
        }
        rolling_market = select(
            grid,
            func.count().over(**window_args).label("rolling_slot_count"),
            func.sum(case((grid.c.adjusted_basis.is_not(None), 1), else_=0))
            .over(**window_args)
            .label("rolling_valid_count"),
            func.sum(grid.c.adjusted_basis)
            .over(**window_args)
            .label("rolling_adjusted_sum"),
            func.sum(grid.c.ma_market_invalid)
            .over(**window_args)
            .label("rolling_market_invalid_count"),
            func.sum(grid.c.ma_factor_missing)
            .over(**window_args)
            .label("rolling_factor_missing_count"),
            func.sum(grid.c.ma_factor_non_positive)
            .over(**window_args)
            .label("rolling_factor_non_positive_count"),
        ).cte("member_breadth_projection_rolling_market")
        member_day = (
            select(
                relation_members.c.trade_date,
                relation_members.c.stock_code,
                relation_members.c.stock_name,
                rolling_market.c.market_present,
                rolling_market.c.pct_valid,
                rolling_market.c.amount_finite,
                rolling_market.c.amount_valid,
                rolling_market.c.pct_change,
                rolling_market.c.amount_thousand_yuan,
                rolling_market.c.adjusted_basis,
                rolling_market.c.rolling_slot_count,
                rolling_market.c.rolling_valid_count,
                rolling_market.c.rolling_adjusted_sum,
                rolling_market.c.rolling_market_invalid_count,
                rolling_market.c.rolling_factor_missing_count,
                rolling_market.c.rolling_factor_non_positive_count,
            )
            .select_from(relation_members)
            .join(
                rolling_market,
                and_(
                    rolling_market.c.stock_code == relation_members.c.stock_code,
                    rolling_market.c.trade_date == relation_members.c.trade_date,
                ),
            )
            .cte("member_breadth_projection_member_day")
        )

        target_member = member_day.alias("member_breadth_target_member_projection")
        member_rows = select(
            target_member.c.trade_date,
            target_member.c.stock_code,
            target_member.c.stock_name,
            case((target_member.c.market_present == 0, 1), else_=0).label(
                "daily_market_missing_count"
            ),
            case(
                (
                    and_(
                        target_member.c.market_present == 1,
                        target_member.c.pct_valid == 0,
                    ),
                    1,
                ),
                else_=0,
            ).label("pct_missing_count"),
            case(
                (
                    and_(
                        target_member.c.market_present == 1,
                        target_member.c.amount_finite == 0,
                    ),
                    1,
                ),
                else_=0,
            ).label("amount_missing_count"),
            case(
                (
                    and_(
                        target_member.c.market_present == 1,
                        target_member.c.amount_finite == 1,
                        target_member.c.amount_valid == 0,
                    ),
                    1,
                ),
                else_=0,
            ).label("amount_non_positive_count"),
            case((target_member.c.rolling_market_invalid_count > 0, 1), else_=0).label(
                "ma_market_missing_count"
            ),
            case((target_member.c.rolling_factor_missing_count > 0, 1), else_=0).label(
                "ma_factor_missing_count"
            ),
            case(
                (
                    target_member.c.rolling_factor_non_positive_count > 0,
                    1,
                ),
                else_=0,
            ).label("ma_factor_non_positive_count"),
            case(
                (
                    or_(
                        target_member.c.rolling_slot_count != ma_period,
                        target_member.c.rolling_valid_count != ma_period,
                    ),
                    1,
                ),
                else_=0,
            ).label("ma_history_insufficient_count"),
            case(
                (target_member.c.pct_valid == 1, target_member.c.pct_change),
                else_=None,
            ).label("daily_pct_change"),
            case(
                (
                    target_member.c.amount_valid == 1,
                    target_member.c.amount_thousand_yuan,
                ),
                else_=None,
            ).label("amount_thousand_yuan"),
            target_member.c.adjusted_basis.label("current_adjusted_basis"),
            target_member.c.rolling_adjusted_sum,
            target_member.c.rolling_slot_count,
            target_member.c.rolling_valid_count,
        ).where(target_member.c.trade_date == target_date)

        rows = session.execute(member_rows.order_by(target_member.c.stock_code)).all()
        members: list[MemberBreadthMemberProjectionFact] = []
        seen_member_keys: set[tuple[date, str]] = set()
        for row in rows:
            key = (row.trade_date, row.stock_code)
            if key in seen_member_keys:
                raise DuplicateMemberBreadthFactError(
                    "duplicate member breadth target projection"
                )
            seen_member_keys.add(key)
            reasons: set[SectorMemberBreadthReason] = set()
            if row.daily_market_missing_count or row.ma_market_missing_count:
                reasons.add("MARKET_ROW_MISSING")
            if row.pct_missing_count:
                reasons.add("PCT_CHANGE_MISSING")
            if row.amount_missing_count:
                reasons.add("AMOUNT_MISSING")
            if row.amount_non_positive_count:
                reasons.add("AMOUNT_NON_POSITIVE")
            if row.ma_factor_missing_count:
                reasons.add("ADJ_FACTOR_MISSING")
            if row.ma_factor_non_positive_count:
                reasons.add("ADJ_FACTOR_NON_POSITIVE")
            if row.ma_history_insufficient_count:
                reasons.add("MA_HISTORY_INSUFFICIENT")
            members.append(
                MemberBreadthMemberProjectionFact(
                    trade_date=row.trade_date,
                    stock_code=row.stock_code,
                    stock_name=(
                        row.stock_name.strip()
                        if row.stock_name and row.stock_name.strip()
                        else None
                    ),
                    daily_pct_change=row.daily_pct_change,
                    amount_thousand_yuan=row.amount_thousand_yuan,
                    current_adjusted_basis=row.current_adjusted_basis,
                    rolling_adjusted_sum=row.rolling_adjusted_sum,
                    rolling_slot_count=int(row.rolling_slot_count),
                    rolling_valid_count=int(row.rolling_valid_count),
                    source_reasons=ordered_member_breadth_reasons(reasons),
                )
            )

        return tuple(members)
