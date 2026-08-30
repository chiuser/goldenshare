from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Integer,
    Numeric,
    String,
    and_,
    case,
    cast,
    func,
    literal,
    or_,
    select,
    true,
    union_all,
)
from sqlalchemy.orm import Session

from src.biz.services.wealth.market.sector_analysis.sector_member_breadth_contract import (
    DuplicateMemberBreadthFactError,
    MemberBreadthDailyProjectionFact,
    MemberBreadthDetailsProjectionFact,
    MemberBreadthDetailsWindowFact,
    MemberBreadthMemberProjectionFact,
    MemberBreadthWindowRelationsFact,
    MemberMarketFact,
    MemberRelationFact,
    SectorMemberBreadthQueryError,
    SectorMemberBreadthReason,
    ordered_member_breadth_reasons,
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

    @staticmethod
    def load_details_window(
        session: Session,
        *,
        target_date: date,
        coverage_end_date: date,
        hierarchy_sector_codes: tuple[str, ...],
        sector_code: str,
        open_date_count: int,
        relation_date_count: int,
    ) -> MemberBreadthDetailsWindowFact:
        if not hierarchy_sector_codes or not sector_code:
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
        target_source_count = (
            select(func.count())
            .select_from(DcMember)
            .where(
                DcMember.trade_date == target_date,
                DcMember.ts_code == sector_code,
            )
            .scalar_subquery()
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
            .cte("member_breadth_details_open_dates")
        )
        rows = session.execute(
            select(
                open_dates.c.trade_date,
                coverage_start.label("coverage_start_date"),
                target_source_count.label("target_source_count"),
            ).order_by(open_dates.c.trade_date)
        ).all()
        if not rows:
            raise SectorSelectionInvalidError("tradeDate 之前没有 SSE 开市日")
        coverage_start_date = rows[0].coverage_start_date
        if coverage_start_date is None:
            raise SectorMemberBreadthQueryError("industry daily coverage is empty")
        returned_open_dates = tuple(row.trade_date for row in rows)
        if returned_open_dates[-1] != target_date:
            raise SectorSelectionInvalidError("tradeDate 必须是 SSE 开市日")
        if target_date < coverage_start_date:
            raise SectorSelectionInvalidError("tradeDate 早于公共行业行情覆盖起点")
        return MemberBreadthDetailsWindowFact(
            coverage_start_date=coverage_start_date,
            coverage_end_date=coverage_end_date,
            open_dates=returned_open_dates,
            relation_dates=returned_open_dates[-relation_date_count:],
            target_source_count=int(rows[0].target_source_count or 0),
        )

    @staticmethod
    def load_details_projection(
        session: Session,
        *,
        sector_code: str,
        target_date: date,
        open_dates: tuple[date, ...],
        relation_dates: tuple[date, ...],
        ma_period: int,
    ) -> MemberBreadthDetailsProjectionFact:
        if not sector_code or not open_dates or not relation_dates:
            raise SectorMemberBreadthQueryError("member breadth details window is empty")
        if target_date != open_dates[-1] or target_date != relation_dates[-1]:
            raise SectorMemberBreadthQueryError("member breadth target date mismatch")
        if not 1 <= len(open_dates) <= _MAX_OPEN_DATE_COUNT:
            raise SectorSelectionInvalidError(
                "成员广度交易日窗口必须在 1 到 119 日之间"
            )
        if ma_period not in (5, 10, 15, 20, 30, 60):
            raise SectorSelectionInvalidError("成员广度均线周期不合法")

        open_date_rows = (
            select(TradeCalendar.trade_date.label("trade_date"))
            .where(
                TradeCalendar.exchange == "SSE",
                TradeCalendar.is_open.is_(True),
                TradeCalendar.trade_date.in_(open_dates),
            )
            .cte("member_breadth_projection_open_dates")
        )
        relation_date_rows = (
            select(open_date_rows.c.trade_date)
            .where(open_date_rows.c.trade_date.in_(relation_dates))
            .cte("member_breadth_projection_relation_dates")
        )
        relation_members = (
            select(
                DcMember.trade_date.label("trade_date"),
                DcMember.con_code.label("stock_code"),
                DcMember.name.label("stock_name"),
            )
            .where(
                DcMember.ts_code == sector_code,
                DcMember.trade_date.in_(select(relation_date_rows.c.trade_date)),
            )
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
                case((and_(market_present, pct_finite), 1), else_=0).label(
                    "pct_valid"
                ),
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
                case(
                    (and_(close_valid, ~factor_finite), 1), else_=0
                ).label("ma_factor_missing"),
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
        rolling_market = (
            select(
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
            )
            .cte("member_breadth_projection_rolling_market")
        )
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

        has_member = member_day.c.stock_code.is_not(None)
        pct_valid_member = and_(has_member, member_day.c.pct_valid == 1)
        turnover_valid_member = and_(
            pct_valid_member,
            member_day.c.amount_valid == 1,
        )
        ma_valid_member = and_(
            has_member,
            member_day.c.rolling_slot_count == ma_period,
            member_day.c.rolling_valid_count == ma_period,
        )
        daily_projection = (
            select(
                relation_date_rows.c.trade_date.label("trade_date"),
                func.count(member_day.c.stock_code).label("source_count"),
                func.sum(case((pct_valid_member, 1), else_=0)).label(
                    "member_calculable_count"
                ),
                func.sum(
                    case(
                        (
                            and_(pct_valid_member, member_day.c.pct_change > 0),
                            1,
                        ),
                        else_=0,
                    )
                ).label("member_up_count"),
                func.sum(
                    case(
                        (
                            and_(pct_valid_member, member_day.c.pct_change == 0),
                            1,
                        ),
                        else_=0,
                    )
                ).label("member_flat_count"),
                func.sum(
                    case(
                        (
                            and_(pct_valid_member, member_day.c.pct_change < 0),
                            1,
                        ),
                        else_=0,
                    )
                ).label("member_down_count"),
                func.sum(case((turnover_valid_member, 1), else_=0)).label(
                    "turnover_calculable_count"
                ),
                func.sum(
                    case(
                        (
                            and_(
                                turnover_valid_member,
                                member_day.c.pct_change > 0,
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ).label("turnover_up_count"),
                func.sum(
                    case(
                        (
                            and_(
                                turnover_valid_member,
                                member_day.c.pct_change == 0,
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ).label("turnover_flat_count"),
                func.sum(
                    case(
                        (
                            and_(
                                turnover_valid_member,
                                member_day.c.pct_change < 0,
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ).label("turnover_down_count"),
                func.sum(
                    case(
                        (
                            and_(
                                turnover_valid_member,
                                member_day.c.pct_change > 0,
                            ),
                            member_day.c.amount_thousand_yuan,
                        ),
                        else_=0,
                    )
                ).label("turnover_up_amount"),
                func.sum(
                    case(
                        (
                            and_(
                                turnover_valid_member,
                                member_day.c.pct_change == 0,
                            ),
                            member_day.c.amount_thousand_yuan,
                        ),
                        else_=0,
                    )
                ).label("turnover_flat_amount"),
                func.sum(
                    case(
                        (
                            and_(
                                turnover_valid_member,
                                member_day.c.pct_change < 0,
                            ),
                            member_day.c.amount_thousand_yuan,
                        ),
                        else_=0,
                    )
                ).label("turnover_down_amount"),
                func.sum(case((ma_valid_member, 1), else_=0)).label(
                    "ma_calculable_count"
                ),
                func.sum(
                    case(
                        (
                            and_(
                                ma_valid_member,
                                member_day.c.adjusted_basis * ma_period
                                > member_day.c.rolling_adjusted_sum,
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ).label("ma_above_count"),
                func.sum(
                    case(
                        (
                            and_(
                                ma_valid_member,
                                member_day.c.adjusted_basis * ma_period
                                == member_day.c.rolling_adjusted_sum,
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ).label("ma_equal_count"),
                func.sum(
                    case(
                        (
                            and_(
                                ma_valid_member,
                                member_day.c.adjusted_basis * ma_period
                                < member_day.c.rolling_adjusted_sum,
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ).label("ma_below_count"),
                func.sum(
                    case(
                        (
                            and_(has_member, member_day.c.market_present == 0),
                            1,
                        ),
                        else_=0,
                    )
                ).label("daily_market_missing_count"),
                func.sum(
                    case(
                        (
                            and_(
                                has_member,
                                member_day.c.market_present == 1,
                                member_day.c.pct_valid == 0,
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ).label("pct_missing_count"),
                func.sum(
                    case(
                        (
                            and_(
                                pct_valid_member,
                                member_day.c.amount_finite == 0,
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ).label("amount_missing_count"),
                func.sum(
                    case(
                        (
                            and_(
                                pct_valid_member,
                                member_day.c.amount_finite == 1,
                                member_day.c.amount_valid == 0,
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ).label("amount_non_positive_count"),
                func.sum(
                    case(
                        (
                            and_(
                                has_member,
                                member_day.c.rolling_market_invalid_count > 0,
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ).label("ma_market_missing_count"),
                func.sum(
                    case(
                        (
                            and_(
                                has_member,
                                member_day.c.rolling_factor_missing_count > 0,
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ).label("ma_factor_missing_count"),
                func.sum(
                    case(
                        (
                            and_(
                                has_member,
                                member_day.c.rolling_factor_non_positive_count > 0,
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ).label("ma_factor_non_positive_count"),
                func.sum(
                    case(
                        (
                            and_(has_member, ~ma_valid_member),
                            1,
                        ),
                        else_=0,
                    )
                ).label("ma_history_insufficient_count"),
            )
            .select_from(relation_date_rows)
            .outerjoin(
                member_day,
                member_day.c.trade_date == relation_date_rows.c.trade_date,
            )
            .group_by(relation_date_rows.c.trade_date)
            .cte("member_breadth_daily_projection")
        )

        integer_null = cast(literal(None), Integer)
        numeric_null = cast(literal(None), Numeric())
        string_null = cast(literal(None), String(128))
        daily_rows = select(
            literal("DAY").label("row_kind"),
            daily_projection.c.trade_date,
            string_null.label("stock_code"),
            string_null.label("stock_name"),
            daily_projection.c.source_count,
            daily_projection.c.member_calculable_count,
            daily_projection.c.member_up_count,
            daily_projection.c.member_flat_count,
            daily_projection.c.member_down_count,
            daily_projection.c.turnover_calculable_count,
            daily_projection.c.turnover_up_count,
            daily_projection.c.turnover_flat_count,
            daily_projection.c.turnover_down_count,
            daily_projection.c.turnover_up_amount,
            daily_projection.c.turnover_flat_amount,
            daily_projection.c.turnover_down_amount,
            daily_projection.c.ma_calculable_count,
            daily_projection.c.ma_above_count,
            daily_projection.c.ma_equal_count,
            daily_projection.c.ma_below_count,
            daily_projection.c.daily_market_missing_count,
            daily_projection.c.pct_missing_count,
            daily_projection.c.amount_missing_count,
            daily_projection.c.amount_non_positive_count,
            daily_projection.c.ma_market_missing_count,
            daily_projection.c.ma_factor_missing_count,
            daily_projection.c.ma_factor_non_positive_count,
            daily_projection.c.ma_history_insufficient_count,
            numeric_null.label("daily_pct_change"),
            numeric_null.label("amount_thousand_yuan"),
            numeric_null.label("current_adjusted_basis"),
            numeric_null.label("rolling_adjusted_sum"),
            integer_null.label("rolling_slot_count"),
            integer_null.label("rolling_valid_count"),
        )
        target_member = member_day.alias("member_breadth_target_member_projection")
        member_rows = select(
            literal("MEMBER").label("row_kind"),
            target_member.c.trade_date,
            target_member.c.stock_code,
            target_member.c.stock_name,
            integer_null.label("source_count"),
            integer_null.label("member_calculable_count"),
            integer_null.label("member_up_count"),
            integer_null.label("member_flat_count"),
            integer_null.label("member_down_count"),
            integer_null.label("turnover_calculable_count"),
            integer_null.label("turnover_up_count"),
            integer_null.label("turnover_flat_count"),
            integer_null.label("turnover_down_count"),
            numeric_null.label("turnover_up_amount"),
            numeric_null.label("turnover_flat_amount"),
            numeric_null.label("turnover_down_amount"),
            integer_null.label("ma_calculable_count"),
            integer_null.label("ma_above_count"),
            integer_null.label("ma_equal_count"),
            integer_null.label("ma_below_count"),
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
            case(
                (target_member.c.rolling_market_invalid_count > 0, 1), else_=0
            ).label("ma_market_missing_count"),
            case(
                (target_member.c.rolling_factor_missing_count > 0, 1), else_=0
            ).label("ma_factor_missing_count"),
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
        statement = union_all(daily_rows, member_rows).order_by(
            "trade_date", "row_kind", "stock_code"
        )
        rows = session.execute(statement).all()

        daily: list[MemberBreadthDailyProjectionFact] = []
        members: list[MemberBreadthMemberProjectionFact] = []
        seen_dates: set[date] = set()
        seen_member_keys: set[tuple[date, str]] = set()
        for row in rows:
            if row.row_kind == "DAY":
                if row.trade_date in seen_dates:
                    raise DuplicateMemberBreadthFactError(
                        "duplicate member breadth daily projection"
                    )
                seen_dates.add(row.trade_date)
                member_reasons: set[SectorMemberBreadthReason] = set()
                turnover_reasons: set[SectorMemberBreadthReason] = set()
                ma_reasons: set[SectorMemberBreadthReason] = set()
                if row.daily_market_missing_count:
                    member_reasons.add("MARKET_ROW_MISSING")
                    turnover_reasons.add("MARKET_ROW_MISSING")
                if row.pct_missing_count:
                    member_reasons.add("PCT_CHANGE_MISSING")
                    turnover_reasons.add("PCT_CHANGE_MISSING")
                if row.amount_missing_count:
                    turnover_reasons.add("AMOUNT_MISSING")
                if row.amount_non_positive_count:
                    turnover_reasons.add("AMOUNT_NON_POSITIVE")
                if row.ma_market_missing_count:
                    ma_reasons.add("MARKET_ROW_MISSING")
                if row.ma_factor_missing_count:
                    ma_reasons.add("ADJ_FACTOR_MISSING")
                if row.ma_factor_non_positive_count:
                    ma_reasons.add("ADJ_FACTOR_NON_POSITIVE")
                if row.ma_history_insufficient_count:
                    ma_reasons.add("MA_HISTORY_INSUFFICIENT")
                daily.append(
                    MemberBreadthDailyProjectionFact(
                        trade_date=row.trade_date,
                        source_count=int(row.source_count),
                        member_calculable_count=int(row.member_calculable_count),
                        member_up_count=int(row.member_up_count),
                        member_flat_count=int(row.member_flat_count),
                        member_down_count=int(row.member_down_count),
                        turnover_calculable_count=int(
                            row.turnover_calculable_count
                        ),
                        turnover_up_count=int(row.turnover_up_count),
                        turnover_flat_count=int(row.turnover_flat_count),
                        turnover_down_count=int(row.turnover_down_count),
                        turnover_up_amount=_decimal_or_zero(row.turnover_up_amount),
                        turnover_flat_amount=_decimal_or_zero(
                            row.turnover_flat_amount
                        ),
                        turnover_down_amount=_decimal_or_zero(
                            row.turnover_down_amount
                        ),
                        ma_calculable_count=int(row.ma_calculable_count),
                        ma_above_count=int(row.ma_above_count),
                        ma_equal_count=int(row.ma_equal_count),
                        ma_below_count=int(row.ma_below_count),
                        member_source_reasons=ordered_member_breadth_reasons(
                            member_reasons
                        ),
                        turnover_source_reasons=ordered_member_breadth_reasons(
                            turnover_reasons
                        ),
                        ma_source_reasons=ordered_member_breadth_reasons(ma_reasons),
                    )
                )
                continue
            if row.row_kind != "MEMBER" or row.stock_code is None:
                raise SectorMemberBreadthQueryError(
                    "unknown member breadth projection row"
                )
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
        returned_dates = tuple(item.trade_date for item in daily)
        if returned_dates != relation_dates:
            raise SectorMemberBreadthQueryError(
                "member breadth daily projection dates mismatch"
            )
        if any(item.trade_date != target_date for item in members):
            raise SectorMemberBreadthQueryError(
                "member breadth target projection date mismatch"
            )
        return MemberBreadthDetailsProjectionFact(
            daily=tuple(daily),
            members=tuple(members),
        )


def _decimal_or_zero(value: Decimal | int | None) -> Decimal:
    if value is None:
        return Decimal(0)
    if isinstance(value, Decimal):
        return value
    return Decimal(value)
