from __future__ import annotations

from collections.abc import Iterable
from datetime import date
import hashlib
import json
from typing import Callable

from sqlalchemy import case, func, literal, or_, select, text
from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.common.sector_hierarchy_query import (
    SectorHierarchyQuery,
    SectorHierarchySnapshot,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.contract import (
    HistorySourceCoverage,
    SectorAnalysisDailyFactsSourceNotReadyError,
    SectorAnalysisSourceBundle,
    SectorComparisonPool,
)
from src.biz.services.wealth.market.sector_analysis.sector_member_breadth_contract import (
    MemberMarketFact,
    MemberRelationFact,
)
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import SectorDailyFact
from src.biz.services.wealth.market.sector_analysis.sector_price_volume_contract import SectorPriceVolumeDailyFact
from src.foundation.models.core.dc_daily import DcDaily
from src.foundation.models.core_serving.dc_member import DcMember
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core_serving.equity_adj_factor import EquityAdjFactor
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar


_READ_ONLY_TRANSACTION_INFO_KEY = "sector_analysis_daily_facts_read_only_transaction"


def ensure_repeatable_read_only_transaction(session: Session) -> None:
    """Start the PostgreSQL snapshot before the first query and only once per transaction."""
    if session.get_bind().dialect.name != "postgresql":
        return
    current_transaction = session.get_transaction()
    if (
        current_transaction is not None
        and session.info.get(_READ_ONLY_TRANSACTION_INFO_KEY) is current_transaction
    ):
        return
    session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
    session.info[_READ_ONLY_TRANSACTION_INFO_KEY] = session.get_transaction()


class SectorAnalysisDailyFactsSourceQuery:
    WINDOW_SIZE = 60

    def __init__(self, *, hierarchy_query: SectorHierarchyQuery | None = None) -> None:
        self._hierarchy_query = hierarchy_query or SectorHierarchyQuery()

    def load_bundle(
        self,
        session: Session,
        *,
        trade_date: date,
        cancel_check: Callable[[], None] | None = None,
    ) -> SectorAnalysisSourceBundle:
        self._check_cancel(cancel_check)
        ensure_repeatable_read_only_transaction(session)

        open_dates = tuple(
            reversed(
                tuple(
                    session.scalars(
                        select(TradeCalendar.trade_date)
                        .where(
                            TradeCalendar.exchange == "SSE",
                            TradeCalendar.is_open.is_(True),
                            TradeCalendar.trade_date <= trade_date,
                        )
                        .order_by(TradeCalendar.trade_date.desc())
                        .limit(self.WINDOW_SIZE)
                    )
                )
            )
        )
        if len(open_dates) != self.WINDOW_SIZE or open_dates[-1] != trade_date:
            raise SectorAnalysisDailyFactsSourceNotReadyError(
                f"{trade_date.isoformat()} 缺少完整60交易日窗口或不是SSE开市日"
            )
        self._check_cancel(cancel_check)

        hierarchy = self._hierarchy_query.load(session)
        self._check_cancel(cancel_check)
        pools = self._comparison_pools(hierarchy)
        sector_codes = tuple(node.sector_code for node in hierarchy.nodes)

        sector_rows = tuple(
            session.execute(
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
                    DcDaily.trade_date.in_(open_dates),
                )
                .order_by(DcDaily.trade_date, DcDaily.ts_code)
            ).all()
        )
        if not sector_rows or not any(row.trade_date == trade_date for row in sector_rows):
            raise SectorAnalysisDailyFactsSourceNotReadyError("目标日行业行情整体未发布")
        self._assert_unique(((row.ts_code, row.trade_date) for row in sector_rows), "dc_daily")
        self._assert_all_source_dates(
            expected_dates=open_dates,
            actual_dates=(row.trade_date for row in sector_rows),
            source="dc_daily",
        )
        self._check_cancel(cancel_check)

        member_rows = tuple(
            session.execute(
                select(DcMember.trade_date, DcMember.ts_code, DcMember.con_code, DcMember.name)
                .where(
                    DcMember.ts_code.in_(sector_codes),
                    DcMember.trade_date.in_(open_dates),
                )
                .order_by(DcMember.trade_date, DcMember.ts_code, DcMember.con_code)
            ).all()
        )
        if not member_rows or not any(row.trade_date == trade_date for row in member_rows):
            raise SectorAnalysisDailyFactsSourceNotReadyError("目标日行业成员整体未发布")
        self._assert_unique(
            ((row.trade_date, row.ts_code, row.con_code) for row in member_rows),
            "dc_member",
        )
        self._assert_all_source_dates(
            expected_dates=open_dates,
            actual_dates=(row.trade_date for row in member_rows),
            source="dc_member",
        )
        self._check_cancel(cancel_check)
        stock_codes = tuple(sorted({row.con_code for row in member_rows}))

        market_rows = tuple(
            session.execute(
                select(
                    EquityDailyBar.ts_code,
                    EquityDailyBar.trade_date,
                    EquityDailyBar.close,
                    EquityDailyBar.pct_chg,
                    EquityDailyBar.amount,
                    EquityAdjFactor.adj_factor,
                )
                .outerjoin(
                    EquityAdjFactor,
                    (EquityAdjFactor.ts_code == EquityDailyBar.ts_code)
                    & (EquityAdjFactor.trade_date == EquityDailyBar.trade_date),
                )
                .where(
                    EquityDailyBar.ts_code.in_(stock_codes),
                    EquityDailyBar.trade_date.in_(open_dates),
                )
                .order_by(EquityDailyBar.trade_date, EquityDailyBar.ts_code)
            ).all()
        )
        self._assert_unique(((row.ts_code, row.trade_date) for row in market_rows), "equity_daily_bar")
        self._assert_all_source_dates(
            expected_dates=open_dates,
            actual_dates=(row.trade_date for row in market_rows),
            source="equity_daily_bar",
        )
        self._assert_all_source_dates(
            expected_dates=open_dates,
            actual_dates=(row.trade_date for row in market_rows if row.adj_factor is not None),
            source="equity_adj_factor",
        )
        self._check_cancel(cancel_check)

        sector_facts = tuple(
            SectorDailyFact(row.ts_code, row.trade_date, row.close, row.pct_change)
            for row in sector_rows
        )
        price_volume_facts = tuple(
            SectorPriceVolumeDailyFact(row.ts_code, row.trade_date, row.close, row.pct_change, row.amount)
            for row in sector_rows
        )
        member_relations = tuple(
            MemberRelationFact(row.ts_code, row.trade_date, row.con_code, row.name)
            for row in member_rows
        )
        member_market_facts = tuple(
            MemberMarketFact(
                row.ts_code,
                row.trade_date,
                row.close,
                row.pct_chg,
                row.amount,
                row.adj_factor,
            )
            for row in market_rows
        )
        self._assert_finite_source(sector_facts, price_volume_facts, member_market_facts)

        source_row_counts = {
            "trade_calendar": len(open_dates),
            "wealth_sector_hierarchy": len(hierarchy.nodes),
            "dc_daily": len(sector_rows),
            "dc_member": len(member_rows),
            "equity_daily_bar": len(market_rows),
            "equity_adj_factor": sum(row.adj_factor is not None for row in market_rows),
        }
        source_dates = {
            "trade_calendar": f"{open_dates[0].isoformat()}..{open_dates[-1].isoformat()}",
            "wealth_sector_hierarchy": hierarchy.published_at.isoformat(),
            "dc_daily": self._date_range(row.trade_date for row in sector_rows),
            "dc_member": self._date_range(row.trade_date for row in member_rows),
            "equity_daily_bar": self._date_range(row.trade_date for row in market_rows),
            "equity_adj_factor": self._date_range(row.trade_date for row in market_rows if row.adj_factor is not None),
        }
        source_hash = self._source_hash(
            open_dates=open_dates,
            hierarchy=hierarchy,
            sector_rows=sector_rows,
            member_rows=member_rows,
            market_rows=market_rows,
        )
        self._check_cancel(cancel_check)
        return SectorAnalysisSourceBundle(
            trade_date=trade_date,
            previous_trade_date=open_dates[-2],
            open_dates=open_dates,
            hierarchy=hierarchy,
            comparison_pools=pools,
            sector_facts=sector_facts,
            price_volume_facts=price_volume_facts,
            member_relations=member_relations,
            member_market_facts=member_market_facts,
            source_dates=source_dates,
            source_row_counts=source_row_counts,
            source_hash=source_hash,
        )

    def audit_dc_daily(
        self,
        session: Session,
        *,
        open_dates: tuple[date, ...],
        sector_codes: tuple[str, ...],
        cancel_check: Callable[[], None] | None = None,
    ) -> HistorySourceCoverage:
        return self._audit_source(
            session,
            source="dc_daily",
            date_column=DcDaily.trade_date,
            key_columns=(DcDaily.ts_code, DcDaily.trade_date, DcDaily.category),
            open_dates=open_dates,
            scope_conditions=(
                DcDaily.category == "行业板块",
                DcDaily.ts_code.in_(sector_codes),
            ),
            invalid_condition=or_(
                DcDaily.close.is_not(None) & (DcDaily.close <= 0),
                DcDaily.amount.is_not(None) & (DcDaily.amount < 0),
            ),
            missing_condition=or_(
                DcDaily.close.is_(None),
                DcDaily.pct_change.is_(None),
                DcDaily.amount.is_(None),
            ),
            cancel_check=cancel_check,
        )

    def audit_dc_member(
        self,
        session: Session,
        *,
        open_dates: tuple[date, ...],
        sector_codes: tuple[str, ...],
        cancel_check: Callable[[], None] | None = None,
    ) -> HistorySourceCoverage:
        return self._audit_source(
            session,
            source="dc_member",
            date_column=DcMember.trade_date,
            key_columns=(DcMember.trade_date, DcMember.ts_code, DcMember.con_code),
            open_dates=open_dates,
            scope_conditions=(DcMember.ts_code.in_(sector_codes),),
            invalid_condition=or_(
                func.length(func.trim(DcMember.ts_code)) == 0,
                func.length(func.trim(DcMember.con_code)) == 0,
            ),
            missing_condition=None,
            cancel_check=cancel_check,
        )

    def audit_equity_daily_bar(
        self,
        session: Session,
        *,
        open_dates: tuple[date, ...],
        sector_codes: tuple[str, ...],
        cancel_check: Callable[[], None] | None = None,
    ) -> HistorySourceCoverage:
        stock_codes = self._member_stock_codes_subquery(
            open_dates=open_dates,
            sector_codes=sector_codes,
        )
        return self._audit_source(
            session,
            source="equity_daily_bar",
            date_column=EquityDailyBar.trade_date,
            key_columns=(EquityDailyBar.ts_code, EquityDailyBar.trade_date),
            open_dates=open_dates,
            scope_conditions=(EquityDailyBar.ts_code.in_(stock_codes),),
            invalid_condition=or_(
                EquityDailyBar.close.is_not(None) & (EquityDailyBar.close <= 0),
                EquityDailyBar.amount.is_not(None) & (EquityDailyBar.amount < 0),
            ),
            missing_condition=or_(
                EquityDailyBar.close.is_(None),
                EquityDailyBar.pct_chg.is_(None),
                EquityDailyBar.amount.is_(None),
            ),
            cancel_check=cancel_check,
        )

    def audit_equity_adj_factor(
        self,
        session: Session,
        *,
        open_dates: tuple[date, ...],
        sector_codes: tuple[str, ...],
        cancel_check: Callable[[], None] | None = None,
    ) -> HistorySourceCoverage:
        stock_codes = self._member_stock_codes_subquery(
            open_dates=open_dates,
            sector_codes=sector_codes,
        )
        return self._audit_source(
            session,
            source="equity_adj_factor",
            date_column=EquityAdjFactor.trade_date,
            key_columns=(EquityAdjFactor.ts_code, EquityAdjFactor.trade_date),
            open_dates=open_dates,
            scope_conditions=(EquityAdjFactor.ts_code.in_(stock_codes),),
            invalid_condition=EquityAdjFactor.adj_factor <= 0,
            missing_condition=None,
            cancel_check=cancel_check,
        )

    @staticmethod
    def _member_stock_codes_subquery(
        *,
        open_dates: tuple[date, ...],
        sector_codes: tuple[str, ...],
    ):
        return (
            select(DcMember.con_code)
            .where(
                DcMember.trade_date.in_(open_dates),
                DcMember.ts_code.in_(sector_codes),
            )
            .distinct()
        )

    def _audit_source(
        self,
        session: Session,
        *,
        source: str,
        date_column,
        key_columns: tuple,
        open_dates: tuple[date, ...],
        scope_conditions: tuple,
        invalid_condition,
        missing_condition,
        cancel_check: Callable[[], None] | None,
    ) -> HistorySourceCoverage:
        if not open_dates:
            raise ValueError("history source audit requires open_dates")
        date_range_condition = date_column.between(open_dates[0], open_dates[-1])
        in_window_condition = date_column.in_(open_dates)
        missing_value_count = literal(0)
        if missing_condition is not None:
            missing_value_count = func.coalesce(
                func.sum(
                    case(
                        (in_window_condition & missing_condition, 1),
                        else_=0,
                    )
                ),
                0,
            )
        summary = self._execute_one(
            session,
            select(
                func.count().label("row_count"),
                func.coalesce(
                    func.sum(case((~in_window_condition, 1), else_=0)),
                    0,
                ).label("illegal_date_count"),
                func.coalesce(
                    func.sum(
                        case(
                            (in_window_condition & invalid_condition, 1),
                            else_=0,
                        )
                    ),
                    0,
                ).label("invalid_value_count"),
                missing_value_count.label("missing_value_count"),
            ).where(date_range_condition, *scope_conditions),
            cancel_check=cancel_check,
        )
        daily_row_counts = tuple(
            (row[0], int(row[1]))
            for row in self._execute_all(
                session,
                select(date_column, func.count())
                .where(in_window_condition, *scope_conditions)
                .group_by(date_column)
                .order_by(date_column),
                cancel_check=cancel_check,
            )
        )
        covered_dates = tuple(item[0] for item in daily_row_counts)
        duplicate_groups = (
            select(*key_columns, func.count().label("row_count"))
            .where(in_window_condition, *scope_conditions)
            .group_by(*key_columns)
            .having(func.count() > 1)
            .subquery()
        )
        duplicate_key_count = int(
            self._execute_scalar(
                session,
                select(func.coalesce(func.sum(duplicate_groups.c.row_count - 1), 0)),
                cancel_check=cancel_check,
            )
            or 0
        )
        return HistorySourceCoverage(
            source=source,
            row_count=int(summary.row_count or 0),
            covered_dates=covered_dates,
            daily_row_counts=daily_row_counts,
            missing_dates=tuple(sorted(set(open_dates) - set(covered_dates))),
            duplicate_key_count=duplicate_key_count,
            illegal_date_count=int(summary.illegal_date_count or 0),
            invalid_value_count=int(summary.invalid_value_count or 0),
            missing_value_count=int(summary.missing_value_count or 0),
        )

    def _execute_one(
        self,
        session: Session,
        statement,
        *,
        cancel_check: Callable[[], None] | None,
    ):
        self._check_cancel(cancel_check)
        result = session.execute(statement).one()
        self._check_cancel(cancel_check)
        return result

    def _execute_all(
        self,
        session: Session,
        statement,
        *,
        cancel_check: Callable[[], None] | None,
    ):
        self._check_cancel(cancel_check)
        result = tuple(session.execute(statement).all())
        self._check_cancel(cancel_check)
        return result

    def _execute_scalar(
        self,
        session: Session,
        statement,
        *,
        cancel_check: Callable[[], None] | None,
    ):
        self._check_cancel(cancel_check)
        result = session.scalar(statement)
        self._check_cancel(cancel_check)
        return result

    @staticmethod
    def _check_cancel(cancel_check: Callable[[], None] | None) -> None:
        if cancel_check is not None:
            cancel_check()

    @staticmethod
    def _comparison_pools(snapshot: SectorHierarchySnapshot) -> tuple[SectorComparisonPool, ...]:
        pools: list[SectorComparisonPool] = []
        for level in (1, 2, 3):
            nodes = tuple(node for node in snapshot.nodes if node.industry_level == level)
            pools.append(
                SectorComparisonPool(
                    scope=f"LEVEL_{level}",
                    comparison_key=f"GLOBAL:L{level}",
                    parent_sector_code=None,
                    sector_codes=tuple(node.sector_code for node in nodes),
                )
            )
        for parent in (node for node in snapshot.nodes if node.industry_level in (1, 2)):
            children = tuple(
                node
                for node in snapshot.children_by_parent.get(parent.sector_code, ())
                if node.industry_level == parent.industry_level + 1
            )
            if not children:
                continue
            pools.append(
                SectorComparisonPool(
                    scope=f"LEVEL_{parent.industry_level}_CHILDREN",
                    comparison_key=f"PARENT:L{parent.industry_level}:{parent.sector_code}",
                    parent_sector_code=parent.sector_code,
                    sector_codes=tuple(node.sector_code for node in children),
                )
            )
        if any(not pool.sector_codes for pool in pools):
            raise SectorAnalysisDailyFactsSourceNotReadyError("行业比较池存在空集合")
        return tuple(pools)

    @staticmethod
    def _assert_unique(keys: Iterable[object], source: str) -> None:
        values = tuple(keys)
        if len(values) != len(set(values)):
            raise SectorAnalysisDailyFactsSourceNotReadyError(f"{source} 业务键重复")

    @staticmethod
    def _assert_all_source_dates(
        *,
        expected_dates: tuple[date, ...],
        actual_dates: Iterable[date],
        source: str,
    ) -> None:
        missing = tuple(sorted(set(expected_dates) - set(actual_dates)))
        if missing:
            raise SectorAnalysisDailyFactsSourceNotReadyError(
                f"{source} 来源日期整体未发布: {','.join(item.isoformat() for item in missing)}"
            )

    @staticmethod
    def _assert_finite_source(
        sector_facts: tuple[SectorDailyFact, ...],
        price_volume_facts: tuple[SectorPriceVolumeDailyFact, ...],
        market_facts: tuple[MemberMarketFact, ...],
    ) -> None:
        values = [
            *(value for row in sector_facts for value in (row.close, row.pct_change)),
            *(row.amount for row in price_volume_facts),
            *(value for row in market_facts for value in (row.close, row.pct_change, row.amount_thousand_yuan, row.adj_factor)),
        ]
        if any(value is not None and not value.is_finite() for value in values):
            raise SectorAnalysisDailyFactsSourceNotReadyError("来源包含非有限数值")

    @staticmethod
    def _date_range(values: Iterable[date]) -> str:
        dates = tuple(values)
        return "" if not dates else f"{min(dates).isoformat()}..{max(dates).isoformat()}"

    @staticmethod
    def _source_hash(*, open_dates, hierarchy, sector_rows, member_rows, market_rows) -> str:  # type: ignore[no-untyped-def]
        digest = hashlib.sha256()
        def feed(source: str, values: Iterable[object]) -> None:
            for value in values:
                payload = json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=lambda item: item.isoformat() if hasattr(item, "isoformat") else str(item),
                )
                digest.update(source.encode("utf-8"))
                digest.update(b"\0")
                digest.update(payload.encode("utf-8"))
                digest.update(b"\n")
        feed("trade_calendar", open_dates)
        feed(
            "wealth_sector_hierarchy",
            (
                (node.sector_code, node.sector_name, node.industry_level, node.parent_sector_code, node.root_sector_code, node.hierarchy_path, node.display_order, hierarchy.baseline_version)
                for node in hierarchy.nodes
            ),
        )
        feed("dc_daily", (tuple(row) for row in sector_rows))
        feed("dc_member", (tuple(row) for row in member_rows))
        feed("equity_daily_bar+adj_factor", (tuple(row) for row in market_rows))
        return digest.hexdigest()
