from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.biz.services.wealth.market.sector_analysis.daily_facts.contract import (
    DailyFactsPreview,
    SectorAnalysisDailyFactsSourceNotReadyError,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.replay_planner import (
    SectorAnalysisReplayGap,
    SectorAnalysisReplayPlanner,
    SectorAnalysisReplayScope,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.source_query import (
    ensure_repeatable_read_only_transaction,
)
from src.foundation.models.core.trade_calendar import TradeCalendar


FIRST = date(2025, 8, 22)
SECOND = date(2025, 8, 25)


def _preview(
    trade_date: date,
    *,
    hierarchy_version: str = "hierarchy-v1",
    source_hash: str = "a" * 64,
) -> DailyFactsPreview:
    return DailyFactsPreview(
        trade_date=trade_date,
        hierarchy_version=hierarchy_version,
        source_hash=source_hash,
        plan_hash="b" * 64,
        content_hash="c" * 64,
        source_dates={
            "trade_calendar": f"2025-05-30..{trade_date.isoformat()}",
            "wealth_sector_hierarchy": "2026-08-31T00:00:00+00:00",
        },
        source_row_counts={
            "trade_calendar": 60,
            "wealth_sector_hierarchy": 3,
            "dc_daily": 180,
        },
        expected_fact_counts={
            "wealth_sector_analysis_publish_batch": 1,
            "wealth_sector_momentum_daily": 25,
            "wealth_sector_dual_momentum_daily": 20,
            "wealth_sector_relative_rotation_daily": 20,
            "wealth_sector_member_breadth_daily": 5,
            "wealth_sector_member_ma_breadth_daily": 30,
            "wealth_sector_price_volume_daily": 25,
            "wealth_sector_daily_insight_summary": 3,
            "wealth_sector_daily_insight_item": 3,
        },
        missing_counts={},
        finite_summary={},
    )


@dataclass
class _MaterializerStub:
    previews: dict[date, DailyFactsPreview]
    blocked_dates: set[date] = field(default_factory=set)
    calls: list[date] = field(default_factory=list)

    def preview_trade_date(
        self,
        session,
        *,
        trade_date,
        cancel_check=None,
        phase_update=None,
    ):  # type: ignore[no-untyped-def]
        del session
        if cancel_check is not None:
            cancel_check()
        if phase_update is not None:
            phase_update("CALCULATING_FACTS")
        self.calls.append(trade_date)
        if trade_date in self.blocked_dates:
            raise SectorAnalysisDailyFactsSourceNotReadyError(
                f"{trade_date.isoformat()} source blocked"
            )
        return self.previews[trade_date]


class _HierarchyQueryStub:
    def __init__(self, version: str = "hierarchy-v1") -> None:
        self.version = version

    def load(self, session):  # type: ignore[no-untyped-def]
        del session
        return type("Hierarchy", (), {"baseline_version": self.version})()


class _PostgresBindStub:
    class Dialect:
        name = "postgresql"

    dialect = Dialect()


class _PostgresSessionStub:
    def __init__(self) -> None:
        self.info: dict[str, object] = {}
        self.transaction: object | None = None
        self.events: list[str] = []

    def get_bind(self):  # type: ignore[no-untyped-def]
        return _PostgresBindStub()

    def get_transaction(self):  # type: ignore[no-untyped-def]
        return self.transaction

    def execute(self, statement):  # type: ignore[no-untyped-def]
        self.events.append(str(statement))
        if self.transaction is None:
            self.transaction = object()

    def scalars(self, statement):  # type: ignore[no-untyped-def]
        del statement
        self.events.append("SELECT trade_calendar")
        return (FIRST, SECOND)

    def rollback(self) -> None:
        return None


@dataclass
class _TransactionAwareMaterializer:
    events: list[str]

    def preview_trade_date(
        self,
        session,
        *,
        trade_date,
        cancel_check=None,
        phase_update=None,
    ):  # type: ignore[no-untyped-def]
        if cancel_check is not None:
            cancel_check()
        ensure_repeatable_read_only_transaction(session)
        if phase_update is not None:
            phase_update("CALCULATING_FACTS")
        self.events.append(f"PREVIEW {trade_date.isoformat()}")
        return _preview(trade_date)


def _build_plan(planner: SectorAnalysisReplayPlanner, session: Session, *, start_date: date, end_date: date):  # type: ignore[no-untyped-def]
    scope = planner.resolve_scope(session, start_date=start_date, end_date=end_date)
    results = tuple(
        planner.preview_unit(session, scope=scope, trade_date=trade_date)
        for trade_date in scope.open_trade_dates
    )
    return planner.finalize(scope=scope, results=results)


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


def test_replay_plan_clamps_to_first_supported_publish_date_and_freezes_evidence() -> None:
    materializer = _MaterializerStub(
        previews={FIRST: _preview(FIRST), SECOND: _preview(SECOND, source_hash="d" * 64)}
    )
    planner = SectorAnalysisReplayPlanner(
        materializer,  # type: ignore[arg-type]
        hierarchy_query=_HierarchyQueryStub(),  # type: ignore[arg-type]
    )
    with Session(_engine()) as session:
        first = _build_plan(
            planner,
            session,
            start_date=date(2024, 1, 1),
            end_date=SECOND,
        )
        second = _build_plan(
            planner,
            session,
            start_date=date(2024, 1, 1),
            end_date=SECOND,
        )

    assert first.start_date == FIRST
    assert first.open_trade_dates == (FIRST, SECOND)
    assert tuple(unit.trade_date for unit in first.units) == (FIRST, SECOND)
    assert first.warmup_start_date == date(2025, 5, 30)
    assert first.hierarchy_version == "hierarchy-v1"
    assert first.units[0].expected_fact_count_ranges[
        "wealth_sector_daily_insight_item"
    ] == (0, 6)
    assert first.apply_ready is True
    assert first.gaps == ()
    assert first.plan_hash == second.plan_hash


def test_replay_plan_uses_one_short_read_only_transaction_per_scope_and_trade_date() -> None:
    scope_session = _PostgresSessionStub()
    first_session = _PostgresSessionStub()
    second_session = _PostgresSessionStub()
    planner = SectorAnalysisReplayPlanner(
        _TransactionAwareMaterializer([]),  # type: ignore[arg-type]
        hierarchy_query=_HierarchyQueryStub(),  # type: ignore[arg-type]
    )

    scope = planner.resolve_scope(  # type: ignore[arg-type]
        scope_session,
        start_date=FIRST,
        end_date=SECOND,
    )
    results = (
        planner.preview_unit(first_session, scope=scope, trade_date=FIRST),  # type: ignore[arg-type]
        planner.preview_unit(second_session, scope=scope, trade_date=SECOND),  # type: ignore[arg-type]
    )
    plan = planner.finalize(scope=scope, results=results)

    assert plan.apply_ready is True
    assert scope_session.events == [
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY",
        "SELECT trade_calendar",
    ]
    assert first_session.events[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
    assert second_session.events[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
    assert first_session.transaction is not second_session.transaction


def test_replay_plan_keeps_every_blocked_date_and_never_silently_skips() -> None:
    materializer = _MaterializerStub(
        previews={FIRST: _preview(FIRST), SECOND: _preview(SECOND)},
        blocked_dates={FIRST},
    )
    planner = SectorAnalysisReplayPlanner(
        materializer,  # type: ignore[arg-type]
        hierarchy_query=_HierarchyQueryStub(),  # type: ignore[arg-type]
    )
    with Session(_engine()) as session:
        plan = _build_plan(planner, session, start_date=FIRST, end_date=SECOND)

    assert plan.open_trade_dates == (FIRST, SECOND)
    assert tuple(unit.trade_date for unit in plan.units) == (SECOND,)
    assert tuple(gap.trade_date for gap in plan.gaps) == (FIRST,)
    assert plan.gaps[0].reason_code == "SA_DAILY_FACT_SOURCE_NOT_READY"
    assert plan.apply_ready is False


def test_replay_plan_blocks_mixed_hierarchy_versions() -> None:
    materializer = _MaterializerStub(
        previews={
            FIRST: _preview(FIRST),
            SECOND: _preview(SECOND, hierarchy_version="hierarchy-v2"),
        }
    )
    planner = SectorAnalysisReplayPlanner(
        materializer,  # type: ignore[arg-type]
        hierarchy_query=_HierarchyQueryStub(),  # type: ignore[arg-type]
    )
    with Session(_engine()) as session:
        scope = planner.resolve_scope(session, start_date=FIRST, end_date=SECOND)
        results = tuple(
            planner.preview_unit(session, scope=scope, trade_date=trade_date)
            for trade_date in scope.open_trade_dates
        )
        plan = planner.finalize(scope=scope, results=results)

    assert tuple(unit.trade_date for unit in plan.units) == (FIRST,)
    assert tuple(gap.trade_date for gap in plan.gaps) == (SECOND,)
    assert plan.gaps[0].reason_code == "SA_DAILY_FACT_PLAN_DRIFT"
    assert plan.apply_ready is False


def test_replay_finalize_rejects_partial_or_out_of_order_results() -> None:
    planner = SectorAnalysisReplayPlanner(
        _MaterializerStub(previews={FIRST: _preview(FIRST), SECOND: _preview(SECOND)}),  # type: ignore[arg-type]
        hierarchy_query=_HierarchyQueryStub(),  # type: ignore[arg-type]
    )
    scope = SectorAnalysisReplayScope(
        requested_start_date=FIRST,
        start_date=FIRST,
        end_date=SECOND,
        open_trade_dates=(FIRST, SECOND),
        hierarchy_version="hierarchy-v1",
    )
    with pytest.raises(ValueError, match="frozen scope"):
        planner.finalize(
            scope=scope,
            results=(SectorAnalysisReplayGap(FIRST, "missing", "missing"),),
        )
