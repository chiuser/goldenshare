from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.biz.queries.wealth.market.common.sector_hierarchy_query import (
    SectorHierarchyNode,
    SectorHierarchySnapshot,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.replay_planner import (
    MIN_PUBLISH_DATE,
    SectorAnalysisReplayPlanner,
)
from src.foundation.models.core.trade_calendar import TradeCalendar


FIRST = MIN_PUBLISH_DATE
SECOND = date(2025, 8, 25)


def _hierarchy() -> SectorHierarchySnapshot:
    root = SectorHierarchyNode(
        sector_code="L1.DC",
        sector_name="一级行业",
        industry_level=1,
        parent_sector_code=None,
        parent_sector_name=None,
        root_sector_code="L1.DC",
        root_sector_name="一级行业",
        hierarchy_path="一级行业",
        display_order=1,
        is_leaf=False,
        baseline_version="hierarchy-v1",
    )
    return SectorHierarchySnapshot(
        baseline_version="hierarchy-v1",
        published_at=datetime(2026, 8, 31, tzinfo=timezone.utc),
        nodes=(root,),
        nodes_by_code={root.sector_code: root},
        children_by_parent={None: (root,)},
    )


class _HierarchyQueryStub:
    def __init__(self) -> None:
        self.calls = 0

    def load(self, session):  # type: ignore[no-untyped-def]
        del session
        self.calls += 1
        return _hierarchy()


def _engine():  # type: ignore[no-untyped-def]
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core_serving")
        TradeCalendar.__table__.create(connection)
        connection.execute(
            TradeCalendar.__table__.insert(),
            [
                {"exchange": "SSE", "trade_date": date(2025, 8, 21), "is_open": True},
                {"exchange": "SSE", "trade_date": FIRST, "is_open": True},
                {"exchange": "SSE", "trade_date": SECOND, "is_open": True},
            ],
        )
    return engine


def test_replay_scope_clamps_to_supported_date_and_loads_hierarchy_once() -> None:
    hierarchy_query = _HierarchyQueryStub()
    planner = SectorAnalysisReplayPlanner(hierarchy_query=hierarchy_query)  # type: ignore[arg-type]

    with Session(_engine()) as session:
        scope = planner.resolve_scope(
            session,
            start_date=date(2024, 1, 1),
            end_date=SECOND,
        )

    assert scope.requested_start_date == date(2024, 1, 1)
    assert scope.requested_end_date == SECOND
    assert scope.start_date == FIRST
    assert scope.end_date == SECOND
    assert scope.open_trade_dates == (FIRST, SECOND)
    assert scope.hierarchy_version == "hierarchy-v1"
    assert hierarchy_query.calls == 1
    assert not hasattr(planner, "preview_unit")
    assert not hasattr(planner, "finalize")


def test_replay_scope_rejects_invalid_or_empty_window_without_formula_preview() -> None:
    planner = SectorAnalysisReplayPlanner(
        hierarchy_query=_HierarchyQueryStub()  # type: ignore[arg-type]
    )
    with Session(_engine()) as session:
        with pytest.raises(ValueError, match="later"):
            planner.resolve_scope(session, start_date=SECOND, end_date=FIRST)
        with pytest.raises(ValueError, match="no SSE open"):
            planner.resolve_scope(
                session,
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 2),
            )
