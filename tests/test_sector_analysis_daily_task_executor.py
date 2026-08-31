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
from src.ops.runtime.maintenance_executor import MaintenanceExecutionRequest


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


def _factory():  # type: ignore[no-untyped-def]
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
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


def test_daily_executor_rejects_readiness_drift_and_m23_replay() -> None:
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
    with pytest.raises(ValueError, match="M23前不可执行"):
        executor.plan(
            MaintenanceExecutionRequest(
                action_key=REPLAY_ACTION_KEY,
                params={"start_date": "2025-01-01", "end_date": TARGET.isoformat()},
            )
        )
