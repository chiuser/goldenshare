from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.runtime.sector_analysis_daily_task_executor import (
    DAILY_ACTION_KEY,
    REPLAY_ACTION_KEY,
    SectorAnalysisDailyTaskExecutor,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.contract import (
    DailyFactsMaterializationResult,
    DailyFactsPreview,
    SectorAnalysisDailyFactsPlanDriftError,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.replay_planner import (
    SectorAnalysisReplayPlan,
    SectorAnalysisReplayUnit,
)
from src.ops.runtime.maintenance_executor import MaintenanceExecutionRequest
from src.ops.runtime.maintenance_executor import MaintenanceExecutionUnit
from src.foundation.models.core.trade_calendar import TradeCalendar


TARGET = date(2026, 8, 31)


class MaterializationStub:
    def __init__(self) -> None:
        self.preview_calls = 0
        self.materialize_calls = []

    def preview_trade_date(self, session, *, trade_date):  # type: ignore[no-untyped-def]
        del session
        self.preview_calls += 1
        assert trade_date == TARGET
        return DailyFactsPreview(
            trade_date=TARGET,
            hierarchy_version="hierarchy-v1",
            source_hash="a" * 64,
            plan_hash="b" * 64,
            content_hash="c" * 64,
            source_dates={},
            source_row_counts={},
            expected_fact_counts={"wealth_sector_analysis_publish_batch": 1},
            missing_counts={},
            finite_summary={},
        )

    def materialize_trade_date(self, **kwargs):  # type: ignore[no-untyped-def]
        self.materialize_calls.append(kwargs)
        return DailyFactsMaterializationResult(
            trade_date=TARGET,
            batch_id=None,
            status="PUBLISHED",
            rows_saved=25_020,
            plan_hash="b" * 64,
            content_hash="c" * 64,
            idempotent=False,
        )


class ReplayPlannerStub:
    def plan(self, session, *, start_date, end_date):  # type: ignore[no-untyped-def]
        del session
        assert start_date == TARGET
        assert end_date == TARGET
        return SectorAnalysisReplayPlan(
            start_date=TARGET,
            end_date=TARGET,
            warmup_start_date=date(2026, 6, 1),
            open_trade_dates=(TARGET,),
            units=(
                SectorAnalysisReplayUnit(
                    trade_date=TARGET,
                    hierarchy_version="hierarchy-v1",
                    source_hash="a" * 64,
                    source_dates={},
                    source_row_counts={},
                    expected_fact_count_ranges={
                        "wealth_sector_analysis_publish_batch": (1, 1),
                    },
                ),
            ),
            gaps=(),
            hierarchy_version="hierarchy-v1",
            apply_ready=True,
            plan_hash="d" * 64,
            expected_rows_min=1,
            expected_rows_max=1,
        )

def _factory():  # type: ignore[no-untyped-def]
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    return sessionmaker(bind=engine, expire_on_commit=False)


def _calendar_factory():  # type: ignore[no-untyped-def]
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
            [{"exchange": "SSE", "trade_date": TARGET, "is_open": True}],
        )
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_daily_executor_plans_one_bound_unit_and_executes_only_frozen_hashes() -> None:
    materializer = MaterializationStub()
    executor = SectorAnalysisDailyTaskExecutor(
        session_factory=_factory(),
        materialization_service=materializer,  # type: ignore[arg-type]
    )
    plan = executor.plan(
        MaintenanceExecutionRequest(
            action_key=DAILY_ACTION_KEY,
            params={
                "trade_date": TARGET.isoformat(),
                "readiness": {
                    "sourceHash": "a" * 64,
                    "planHash": "b" * 64,
                    "contentHash": "c" * 64,
                },
            },
        )
    )

    assert len(plan.units) == 1
    assert plan.units[0].unit_key == f"wealth-sector-analysis-daily:{TARGET.isoformat()}"
    assert plan.units[0].payload["expected_source_hash"] == "a" * 64
    result = executor.execute_unit(plan.units[0])
    assert result.rows_saved == 25_020
    assert materializer.materialize_calls == [
        {
            "trade_date": TARGET,
            "expected_source_hash": "a" * 64,
            "expected_plan_hash": "b" * 64,
            "expected_content_hash": "c" * 64,
        }
    ]


def test_daily_executor_rejects_readiness_drift() -> None:
    executor = SectorAnalysisDailyTaskExecutor(
        session_factory=_factory(),
        materialization_service=MaterializationStub(),  # type: ignore[arg-type]
    )
    with pytest.raises(SectorAnalysisDailyFactsPlanDriftError):
        executor.plan(
            MaintenanceExecutionRequest(
                action_key=DAILY_ACTION_KEY,
                params={
                    "trade_date": TARGET.isoformat(),
                    "readiness": {"sourceHash": "f" * 64},
                },
            )
        )


def test_replay_executor_freezes_plan_and_executes_only_matching_source() -> None:
    materializer = MaterializationStub()
    executor = SectorAnalysisDailyTaskExecutor(
        session_factory=_factory(),
        materialization_service=materializer,  # type: ignore[arg-type]
        replay_planner=ReplayPlannerStub(),  # type: ignore[arg-type]
    )

    plan = executor.plan(
        MaintenanceExecutionRequest(
            action_key=REPLAY_ACTION_KEY,
            params={"start_date": TARGET.isoformat(), "end_date": TARGET.isoformat()},
        )
    )

    assert plan.apply_ready is True
    assert plan.plan_hash == "d" * 64
    assert len(plan.units) == 1
    assert plan.units[0].payload["expected_source_hash"] == "a" * 64
    payload = {**plan.units[0].payload, "validate_replay_scope": False}
    result = executor.execute_unit(
        MaintenanceExecutionUnit(unit_key=plan.units[0].unit_key, payload=payload)
    )
    assert result.rows_saved == 25_020
    assert materializer.materialize_calls == [
        {
            "trade_date": TARGET,
            "expected_source_hash": "a" * 64,
            "expected_plan_hash": "b" * 64,
            "expected_content_hash": "c" * 64,
        }
    ]

    with pytest.raises(SectorAnalysisDailyFactsPlanDriftError, match="来源hash"):
        executor.execute_unit(
            MaintenanceExecutionUnit(
                unit_key=plan.units[0].unit_key,
                payload={
                    **payload,
                    "expected_source_hash": "f" * 64,
                },
            )
        )


def test_replay_executor_rejects_sse_date_list_drift_before_preview_or_write() -> None:
    materializer = MaterializationStub()
    executor = SectorAnalysisDailyTaskExecutor(
        session_factory=_calendar_factory(),
        materialization_service=materializer,  # type: ignore[arg-type]
        replay_planner=ReplayPlannerStub(),  # type: ignore[arg-type]
    )
    plan = executor.plan(
        MaintenanceExecutionRequest(
            action_key=REPLAY_ACTION_KEY,
            params={"start_date": TARGET.isoformat(), "end_date": TARGET.isoformat()},
        )
    )

    with pytest.raises(SectorAnalysisDailyFactsPlanDriftError, match="交易日清单"):
        executor.execute_unit(
            MaintenanceExecutionUnit(
                unit_key=plan.units[0].unit_key,
                payload={**plan.units[0].payload, "target_dates_hash": "f" * 64},
            )
        )

    assert materializer.preview_calls == 0
    assert materializer.materialize_calls == []
