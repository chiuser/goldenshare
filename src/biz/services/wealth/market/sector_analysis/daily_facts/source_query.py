from __future__ import annotations

from collections.abc import Iterable
from datetime import date
import hashlib
import json

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.common.sector_hierarchy_query import (
    SectorHierarchyQuery,
    SectorHierarchySnapshot,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.contract import (
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


class SectorAnalysisDailyFactsSourceQuery:
    WINDOW_SIZE = 60

    def __init__(self, *, hierarchy_query: SectorHierarchyQuery | None = None) -> None:
        self._hierarchy_query = hierarchy_query or SectorHierarchyQuery()

    def load_bundle(self, session: Session, *, trade_date: date) -> SectorAnalysisSourceBundle:
        if session.get_bind().dialect.name == "postgresql":
            session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))

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

        hierarchy = self._hierarchy_query.load(session)
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
