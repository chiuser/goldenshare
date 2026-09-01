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
    SectorAnalysisReplayScope,
    SectorAnalysisReplayUnit,
)
from src.ops.runtime.maintenance_executor import MaintenanceExecutionRequest
from src.ops.runtime.maintenance_executor import MaintenanceExecutionUnit
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.ingestion.run_errors import IngestionCanceledError


TARGET = date(2026, 8, 31)


class MaterializationStub:
    def __init__(self) -> None:
        self.preview_calls = 0
        self.materialize_calls = []

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
    def resolve_scope(self, session, *, start_date, end_date):  # type: ignore[no-untyped-def]
        del session
        assert start_date == TARGET
        assert end_date == TARGET
        return SectorAnalysisReplayScope(
            requested_start_date=TARGET,
            start_date=TARGET,
            end_date=TARGET,
            open_trade_dates=(TARGET,),
            hierarchy_version="hierarchy-v1",
        )

    def preview_unit(
        self,
        session,
        *,
        scope,
        trade_date,
        cancel_check=None,
        phase_update=None,
    ):  # type: ignore[no-untyped-def]
        del session
        assert scope.open_trade_dates == (TARGET,)
        assert trade_date == TARGET
        if cancel_check is not None:
            cancel_check()
        if phase_update is not None:
            phase_update("CALCULATING_FACTS")
        return SectorAnalysisReplayUnit(
            trade_date=TARGET,
            hierarchy_version="hierarchy-v1",
            source_hash="a" * 64,
            source_dates={},
            source_row_counts={},
            expected_fact_count_ranges={
                "wealth_sector_analysis_publish_batch": (1, 1),
            },
            warmup_start_date=date(2026, 6, 1),
        )

    def finalize(self, *, scope, results):  # type: ignore[no-untyped-def]
        assert scope.open_trade_dates == (TARGET,)
        assert len(results) == 1
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
                    warmup_start_date=date(2026, 6, 1),
                ),
            ),
            gaps=(),
            hierarchy_version="hierarchy-v1",
            apply_ready=True,
            plan_hash="d" * 64,
            expected_rows_min=1,
            expected_rows_max=1,
        )


class PlanContextStub:
    task_run_id = 1

    def __init__(self) -> None:
        self.phases = []
        self.checkpoints = []

    def is_cancel_requested(self) -> bool:
        return False

    def update_phase(self, **kwargs):  # type: ignore[no-untyped-def]
        self.phases.append(kwargs)

    def save_checkpoint(self, checkpoint):  # type: ignore[no-untyped-def]
        self.checkpoints.append(checkpoint)


class CancelDuringCalculationContext(PlanContextStub):
    def __init__(self) -> None:
        super().__init__()
        self.canceled = False

    def is_cancel_requested(self) -> bool:
        return self.canceled

    def update_phase(self, **kwargs):  # type: ignore[no-untyped-def]
        super().update_phase(**kwargs)
        if kwargs.get("phase") == "CALCULATING_FACTS":
            self.canceled = True


class DriftingReplayPlannerStub(ReplayPlannerStub):
    def __init__(self) -> None:
        self.scope_calls = 0

    def resolve_scope(self, session, *, start_date, end_date):  # type: ignore[no-untyped-def]
        scope = super().resolve_scope(session, start_date=start_date, end_date=end_date)
        self.scope_calls += 1
        if self.scope_calls == 2:
            return SectorAnalysisReplayScope(
                requested_start_date=scope.requested_start_date,
                start_date=scope.start_date,
                end_date=scope.end_date,
                open_trade_dates=scope.open_trade_dates,
                hierarchy_version="hierarchy-v2",
            )
        return scope

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

    plan = executor.plan_for_task_run(
        MaintenanceExecutionRequest(
            action_key=REPLAY_ACTION_KEY,
            params={"start_date": TARGET.isoformat(), "end_date": TARGET.isoformat()},
        ),
        context=PlanContextStub(),
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
    plan = executor.plan_for_task_run(
        MaintenanceExecutionRequest(
            action_key=REPLAY_ACTION_KEY,
            params={"start_date": TARGET.isoformat(), "end_date": TARGET.isoformat()},
        ),
        context=PlanContextStub(),
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


def test_replay_executor_cancels_during_calculation_without_checkpointing_current_date() -> None:
    context = CancelDuringCalculationContext()
    executor = SectorAnalysisDailyTaskExecutor(
        session_factory=_factory(),
        materialization_service=MaterializationStub(),  # type: ignore[arg-type]
        replay_planner=ReplayPlannerStub(),  # type: ignore[arg-type]
    )

    with pytest.raises(IngestionCanceledError):
        executor.plan_for_task_run(
            MaintenanceExecutionRequest(
                action_key=REPLAY_ACTION_KEY,
                params={"start_date": TARGET.isoformat(), "end_date": TARGET.isoformat()},
            ),
            context=context,
        )

    assert context.checkpoints == []


def test_replay_executor_rejects_final_scope_drift_after_last_checkpoint() -> None:
    context = PlanContextStub()
    executor = SectorAnalysisDailyTaskExecutor(
        session_factory=_factory(),
        materialization_service=MaterializationStub(),  # type: ignore[arg-type]
        replay_planner=DriftingReplayPlannerStub(),  # type: ignore[arg-type]
    )

    with pytest.raises(SectorAnalysisDailyFactsPlanDriftError, match="最终交易日清单或层级"):
        executor.plan_for_task_run(
            MaintenanceExecutionRequest(
                action_key=REPLAY_ACTION_KEY,
                params={"start_date": TARGET.isoformat(), "end_date": TARGET.isoformat()},
            ),
            context=context,
        )

    assert [checkpoint.unit_done for checkpoint in context.checkpoints] == [1]
