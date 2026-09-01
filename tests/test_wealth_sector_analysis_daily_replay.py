from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.biz.services.wealth.market.sector_analysis.daily_facts.contract import (
    DailyFactsPreview,
    SectorAnalysisDailyFactsSourceNotReadyError,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.replay_planner import (
    SectorAnalysisReplayPlanner,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.source_query import (
    ensure_repeatable_read_only_transaction,
)
from src.foundation.models.core.trade_calendar import TradeCalendar


FIRST = date(2025, 1, 2)
SECOND = date(2025, 1, 3)


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
            "trade_calendar": f"2024-10-10..{trade_date.isoformat()}",
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

    def preview_trade_date(self, session, *, trade_date):  # type: ignore[no-untyped-def]
        del session
        self.calls.append(trade_date)
        if trade_date in self.blocked_dates:
            raise SectorAnalysisDailyFactsSourceNotReadyError(
                f"{trade_date.isoformat()} source blocked"
            )
        return self.previews[trade_date]


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


@dataclass
class _TransactionAwareMaterializer:
    events: list[str]

    def preview_trade_date(self, session, *, trade_date):  # type: ignore[no-untyped-def]
        ensure_repeatable_read_only_transaction(session)
        self.events.append(f"PREVIEW {trade_date.isoformat()}")
        return _preview(trade_date)


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
                {"exchange": "SSE", "trade_date": date(2024, 12, 31), "is_open": True},
                {"exchange": "SSE", "trade_date": FIRST, "is_open": True},
                {"exchange": "SSE", "trade_date": SECOND, "is_open": True},
            ],
        )
    return engine


def test_replay_plan_clamps_to_2025_and_freezes_ascending_source_evidence() -> None:
    materializer = _MaterializerStub(
        previews={FIRST: _preview(FIRST), SECOND: _preview(SECOND, source_hash="d" * 64)}
    )
    planner = SectorAnalysisReplayPlanner(materializer)  # type: ignore[arg-type]
    with Session(_engine()) as session:
        first = planner.plan(
            session,
            start_date=date(2024, 1, 1),
            end_date=SECOND,
        )
        second = planner.plan(
            session,
            start_date=date(2024, 1, 1),
            end_date=SECOND,
        )

    assert first.start_date == FIRST
    assert first.open_trade_dates == (FIRST, SECOND)
    assert tuple(unit.trade_date for unit in first.units) == (FIRST, SECOND)
    assert first.warmup_start_date == date(2024, 10, 10)
    assert first.hierarchy_version == "hierarchy-v1"
    assert first.units[0].expected_fact_count_ranges[
        "wealth_sector_daily_insight_item"
    ] == (0, 6)
    assert first.apply_ready is True
    assert first.gaps == ()
    assert first.plan_hash == second.plan_hash


def test_replay_plan_starts_one_read_only_snapshot_before_calendar_and_all_previews() -> None:
    session = _PostgresSessionStub()
    planner = SectorAnalysisReplayPlanner(
        _TransactionAwareMaterializer(session.events)  # type: ignore[arg-type]
    )

    plan = planner.plan(  # type: ignore[arg-type]
        session,
        start_date=FIRST,
        end_date=SECOND,
    )

    assert plan.apply_ready is True
    assert session.events == [
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY",
        "SELECT trade_calendar",
        f"PREVIEW {FIRST.isoformat()}",
        f"PREVIEW {SECOND.isoformat()}",
    ]


def test_replay_plan_keeps_every_blocked_date_and_never_silently_skips() -> None:
    materializer = _MaterializerStub(
        previews={FIRST: _preview(FIRST), SECOND: _preview(SECOND)},
        blocked_dates={FIRST},
    )
    planner = SectorAnalysisReplayPlanner(materializer)  # type: ignore[arg-type]
    with Session(_engine()) as session:
        plan = planner.plan(session, start_date=FIRST, end_date=SECOND)

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
    planner = SectorAnalysisReplayPlanner(materializer)  # type: ignore[arg-type]
    with Session(_engine()) as session:
        plan = planner.plan(session, start_date=FIRST, end_date=SECOND)

    assert tuple(unit.trade_date for unit in plan.units) == (FIRST,)
    assert tuple(gap.trade_date for gap in plan.gaps) == (SECOND,)
    assert plan.gaps[0].reason_code == "SA_DAILY_FACT_PLAN_DRIFT"
    assert plan.apply_ready is False
