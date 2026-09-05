from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.biz.queries.wealth.market.common.sector_hierarchy_query import (
    SectorHierarchyNode,
    SectorHierarchySnapshot,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.contract import (
    HISTORY_INPUT_AUDIT_CONTRACT_VERSION,
    HistorySourceCoverage,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.history_input_auditor import (
    SectorAnalysisHistoryInputAuditor,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.replay_planner import (
    MIN_PUBLISH_DATE,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.source_query import (
    SectorAnalysisDailyFactsSourceQuery,
)
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core.dc_daily import DcDaily
from src.foundation.models.core_serving.dc_member import DcMember
from src.foundation.models.core_serving.equity_adj_factor import EquityAdjFactor
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.wealth_sector_hierarchy import (
    WealthSectorHierarchy,
)


FIRST = MIN_PUBLISH_DATE
SECOND = date(2025, 8, 25)


def _node(
    code: str,
    level: int,
    parent: str | None,
    root: str,
) -> SectorHierarchyNode:
    return SectorHierarchyNode(
        sector_code=code,
        sector_name=code,
        industry_level=level,
        parent_sector_code=parent,
        parent_sector_name=parent,
        root_sector_code=root,
        root_sector_name=root,
        hierarchy_path=code,
        display_order=level,
        is_leaf=level == 3,
        baseline_version="hierarchy-v1",
    )


def _hierarchy() -> SectorHierarchySnapshot:
    nodes = (
        _node("L1.DC", 1, None, "L1.DC"),
        _node("L2.DC", 2, "L1.DC", "L1.DC"),
        _node("L3.DC", 3, "L2.DC", "L1.DC"),
    )
    return SectorHierarchySnapshot(
        baseline_version="hierarchy-v1",
        published_at=datetime(2026, 8, 31, tzinfo=timezone.utc),
        nodes=nodes,
        nodes_by_code={node.sector_code: node for node in nodes},
        children_by_parent={
            None: (nodes[0],),
            "L1.DC": (nodes[1],),
            "L2.DC": (nodes[2],),
        },
    )


class _HierarchyQueryStub:
    def __init__(self) -> None:
        self.calls = 0

    def load(self, session):  # type: ignore[no-untyped-def]
        del session
        self.calls += 1
        return _hierarchy()


class _CoverageQueryStub:
    _comparison_pools = staticmethod(SectorAnalysisDailyFactsSourceQuery._comparison_pools)

    def __init__(self, *, overrides=None) -> None:  # type: ignore[no-untyped-def]
        self.calls: list[str] = []
        self.overrides = dict(overrides or {})

    def _coverage(self, source, open_dates):  # type: ignore[no-untyped-def]
        self.calls.append(source)
        base = HistorySourceCoverage(
            source=source,
            row_count=len(open_dates),
            covered_dates=open_dates,
            daily_row_counts=tuple((item, 1) for item in open_dates),
            missing_dates=(),
            duplicate_key_count=0,
            illegal_date_count=0,
            invalid_value_count=0,
            missing_value_count=0,
        )
        return replace(base, **self.overrides.get(source, {}))

    def audit_dc_daily(self, session, *, open_dates, sector_codes, cancel_check=None):  # type: ignore[no-untyped-def]
        del session, sector_codes
        if cancel_check:
            cancel_check()
        return self._coverage("dc_daily", open_dates)

    def audit_dc_member(self, session, *, open_dates, sector_codes, cancel_check=None):  # type: ignore[no-untyped-def]
        del session, sector_codes
        if cancel_check:
            cancel_check()
        return self._coverage("dc_member", open_dates)

    def audit_equity_daily_bar(self, session, *, open_dates, sector_codes, cancel_check=None):  # type: ignore[no-untyped-def]
        del session, sector_codes
        if cancel_check:
            cancel_check()
        return self._coverage("equity_daily_bar", open_dates)

    def audit_equity_adj_factor(self, session, *, open_dates, sector_codes, cancel_check=None):  # type: ignore[no-untyped-def]
        del session, sector_codes
        if cancel_check:
            cancel_check()
        return self._coverage("equity_adj_factor", open_dates)


def _engine():  # type: ignore[no-untyped-def]
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core_serving")
        TradeCalendar.__table__.create(connection)
        warmup = tuple(FIRST - timedelta(days=offset) for offset in range(59, -1, -1))
        connection.execute(
            TradeCalendar.__table__.insert(),
            [
                {"exchange": "SSE", "trade_date": item, "is_open": True}
                for item in warmup + (SECOND,)
            ],
        )
    return engine


def test_history_input_audit_scans_each_source_once_without_formula_preview_or_writes() -> None:
    source_query = _CoverageQueryStub()
    hierarchy_query = _HierarchyQueryStub()
    auditor = SectorAnalysisHistoryInputAuditor(
        source_query=source_query,  # type: ignore[arg-type]
        hierarchy_query=hierarchy_query,  # type: ignore[arg-type]
    )
    progress: list[tuple[int, int, str]] = []

    with Session(_engine()) as session:
        result = auditor.audit(
            session,
            start_date=date(2024, 1, 1),
            end_date=SECOND,
            progress_update=lambda done, total, item: progress.append((done, total, item)),
        )

    assert result.apply_ready is True
    assert result.ordered_trade_dates == (FIRST, SECOND)
    assert result.warmup_start_date == FIRST - timedelta(days=59)
    assert result.hierarchy_version == "hierarchy-v1"
    assert source_query.calls == [
        "dc_daily",
        "dc_member",
        "equity_daily_bar",
        "equity_adj_factor",
    ]
    assert hierarchy_query.calls == 1
    assert progress[-1] == (6, 6, "equity_adj_factor")
    assert result.metadata()["audit_contract_version"] == HISTORY_INPUT_AUDIT_CONTRACT_VERSION
    assert len(result.audit_hash) == 64


def test_history_input_audit_blocks_duplicate_business_keys_but_keeps_local_missing_typed() -> None:
    blocked_query = _CoverageQueryStub(
        overrides={"dc_daily": {"duplicate_key_count": 2}}
    )
    auditor = SectorAnalysisHistoryInputAuditor(
        source_query=blocked_query,  # type: ignore[arg-type]
        hierarchy_query=_HierarchyQueryStub(),  # type: ignore[arg-type]
    )
    with Session(_engine()) as session:
        blocked = auditor.audit(session, start_date=FIRST, end_date=SECOND)
    assert blocked.state == "BLOCKED"
    assert any(issue.blocking and issue.count == 2 for issue in blocked.issues)

    partial_query = _CoverageQueryStub(
        overrides={"equity_daily_bar": {"missing_value_count": 3}}
    )
    auditor = SectorAnalysisHistoryInputAuditor(
        source_query=partial_query,  # type: ignore[arg-type]
        hierarchy_query=_HierarchyQueryStub(),  # type: ignore[arg-type]
    )
    with Session(_engine()) as session:
        partial = auditor.audit(session, start_date=FIRST, end_date=SECOND)
    assert partial.state == "AUDIT_PASSED"
    assert any(not issue.blocking and issue.count == 3 for issue in partial.issues)


def test_history_input_audit_aggregate_queries_accept_valid_six_source_window() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    warmup = tuple(FIRST - timedelta(days=offset) for offset in range(59, -1, -1))
    all_dates = warmup + (SECOND,)
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core_serving")
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core")
        for model in (
            TradeCalendar,
            WealthSectorHierarchy,
            DcDaily,
            DcMember,
            EquityDailyBar,
            EquityAdjFactor,
        ):
            model.__table__.create(connection)
        connection.execute(
            TradeCalendar.__table__.insert(),
            [
                {"exchange": "SSE", "trade_date": item, "is_open": True}
                for item in all_dates
            ],
        )
        nodes = _hierarchy().nodes
        connection.execute(
            WealthSectorHierarchy.__table__.insert(),
            [
                {
                    "sector_code": node.sector_code,
                    "sector_name": node.sector_name,
                    "industry_level": node.industry_level,
                    "industry_level_name": f"{node.industry_level}级行业",
                    "parent_sector_code": node.parent_sector_code,
                    "parent_sector_name": node.parent_sector_name,
                    "root_sector_code": node.root_sector_code,
                    "root_sector_name": node.root_sector_name,
                    "hierarchy_path": node.hierarchy_path,
                    "is_leaf": node.is_leaf,
                    "display_order": node.display_order,
                    "baseline_version": node.baseline_version,
                    "source_received_date": SECOND,
                    "code_reference_trade_date": SECOND,
                    "published_at": datetime(2026, 8, 31, tzinfo=timezone.utc),
                }
                for node in nodes
            ],
        )
        connection.execute(
            DcDaily.__table__.insert(),
            [
                {
                    "ts_code": node.sector_code,
                    "trade_date": item,
                    "category": "行业板块",
                    "close": Decimal("100"),
                    "pct_change": Decimal("1"),
                    "amount": Decimal("1000"),
                }
                for item in all_dates
                for node in nodes
            ],
        )
        connection.execute(
            DcMember.__table__.insert(),
            [
                {
                    "trade_date": item,
                    "ts_code": node.sector_code,
                    "con_code": "000001.SZ",
                    "name": "样本股",
                }
                for item in all_dates
                for node in nodes
            ],
        )
        connection.execute(
            EquityDailyBar.__table__.insert(),
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": item,
                    "close": Decimal("10"),
                    "pct_chg": Decimal("1"),
                    "amount": Decimal("100"),
                    "source": "test",
                }
                for item in all_dates
            ],
        )
        connection.execute(
            EquityAdjFactor.__table__.insert(),
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": item,
                    "adj_factor": Decimal("1"),
                }
                for item in all_dates
            ],
        )

    with Session(engine) as session:
        result = SectorAnalysisHistoryInputAuditor().audit(
            session,
            start_date=FIRST,
            end_date=SECOND,
        )

    assert result.state == "AUDIT_PASSED"
    assert {item.source for item in result.source_coverage} == {
        "trade_calendar",
        "wealth_sector_hierarchy",
        "dc_daily",
        "dc_member",
        "equity_daily_bar",
        "equity_adj_factor",
    }
    assert all(item.duplicate_key_count == 0 for item in result.source_coverage)
