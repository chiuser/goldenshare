from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.biz.services.wealth.market.sector_overview.sector_heat_contract import PriorPublishedHeat
from src.biz.services.wealth.market.sector_overview.sector_heat_materialization_service import (
    SectorHeatPreviewResult,
)
from src.biz.services.wealth.market.sector_overview.sector_heat_replay_planner import (
    SectorHeatReplayPlanner,
)
from src.biz.services.wealth.market.sector_overview.sector_heat_source_query import (
    SectorHeatSourceNotReadyError,
)
from src.foundation.models.core.trade_calendar import TradeCalendar


def _calendar_engine():  # type: ignore[no-untyped-def]
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS core_serving")
        TradeCalendar.__table__.create(connection)
    return engine


class _PreviewServiceStub:
    def __init__(self, *, gap_date: date | None = None) -> None:
        self.gap_date = gap_date
        self.calls: list[tuple[date, dict[date, dict[str, PriorPublishedHeat]] | None]] = []

    def preview_trade_date(  # type: ignore[no-untyped-def]
        self,
        session,
        *,
        trade_date,
        completion_evidence=(),
        prior_published_override=None,
    ):
        del session, completion_evidence
        copied_override = (
            {day: dict(rows) for day, rows in prior_published_override.items()}
            if prior_published_override is not None
            else None
        )
        self.calls.append((trade_date, copied_override))
        if trade_date == self.gap_date:
            raise SectorHeatSourceNotReadyError(f"missing source for {trade_date.isoformat()}")
        published = PriorPublishedHeat(
            trade_date=trade_date,
            heat_status="VALID",
            heat_score=Decimal("80.0000"),
            raw_heat_trend="STABLE",
            score_version="concept-heat-eod-v1",
            config_hash="c" * 64,
        )
        return SectorHeatPreviewResult(
            trade_date=trade_date,
            rows_fetched=100,
            rows_written=2,
            valid_count=1,
            invalid_count=1,
            invalid_reason_counts={"FEATURE_MISSING": 1},
            config_version="1.0.0",
            score_version="concept-heat-eod-v1",
            config_hash="c" * 64,
            source_hash=f"source-{trade_date.isoformat()}",
            plan_hash=f"plan-{trade_date.isoformat()}",
            content_hash=f"content-{trade_date.isoformat()}",
            source_dates={"target": trade_date.isoformat(), "allOpenDates": [trade_date.isoformat()]},
            source_row_counts={"dc_index": 2},
            published_by_code={"A.DC": published},
        )


def _seed_open_dates(session: Session) -> tuple[date, ...]:
    start = date(2026, 5, 20)
    dates = tuple(start + timedelta(days=offset) for offset in range(60))
    session.add_all(TradeCalendar(exchange="SSE", trade_date=day, is_open=True) for day in dates)
    session.commit()
    return dates


def test_replay_plan_builds_sixty_day_lineage_and_freezes_source_diagnostics() -> None:
    engine = _calendar_engine()
    service = _PreviewServiceStub()
    with Session(engine) as session:
        dates = _seed_open_dates(session)
        plan = SectorHeatReplayPlanner(service).plan(  # type: ignore[arg-type]
            session,
            start_date=dates[0],
            end_date=dates[-1],
        )

    assert plan.apply_ready is True
    assert len(plan.open_trade_dates) == 60
    assert len(plan.units) == 60
    assert plan.expected_rows == 120
    assert service.calls[0][1] is None
    assert service.calls[1][1] is not None
    assert dates[0] in service.calls[1][1]
    assert plan.units[0].source_dates["target"] == dates[0].isoformat()
    assert plan.units[0].source_row_counts == {"dc_index": 2}
    assert len(plan.plan_hash) == 64


def test_replay_plan_stops_preview_after_first_source_gap_and_blocks_apply() -> None:
    engine = _calendar_engine()
    with Session(engine) as session:
        dates = _seed_open_dates(session)
        service = _PreviewServiceStub(gap_date=dates[2])
        plan = SectorHeatReplayPlanner(service).plan(  # type: ignore[arg-type]
            session,
            start_date=dates[0],
            end_date=dates[-1],
        )

    assert plan.apply_ready is False
    assert len(plan.units) == 2
    assert len(plan.gaps) == 58
    assert plan.gaps[0].reason_code == "SOURCE_NOT_READY"
    assert all(gap.reason_code == "PREDECESSOR_GAP" for gap in plan.gaps[1:])
    assert len(service.calls) == 3
