from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.runtime.sector_analysis_daily_task_executor import (
    DAILY_ACTION_KEY,
    REPLAY_ACTION_KEY,
    SectorAnalysisDailyTaskExecutor,
)
from src.biz.queries.wealth.market.common.sector_hierarchy_query import (
    SectorHierarchyNode,
    SectorHierarchySnapshot,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.contract import (
    FORMULA_BUNDLE_VERSION,
    HISTORY_INPUT_AUDIT_CONTRACT_VERSION,
    TEMPLATE_VERSION,
    DailyFactsMaterializationResult,
    DailyFactsPreview,
    SectorAnalysisDailyFactsPlanDriftError,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.history_input_auditor import (
    SectorAnalysisHistoryInputAudit,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.replay_planner import (
    SectorAnalysisReplayScope,
)
from src.foundation.ingestion.run_errors import IngestionCanceledError
from src.ops.runtime.maintenance_executor import (
    MaintenanceExecutionRequest,
    MaintenanceExecutionUnit,
    MaintenanceTaskRunContext,
)


TARGET = date(2026, 8, 31)


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


class MaterializationStub:
    def __init__(self) -> None:
        self.preview_calls = 0
        self.materialize_calls = []

    def preview_trade_date(self, session, *, trade_date, **kwargs):  # type: ignore[no-untyped-def]
        del session, kwargs
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
        cancel_check = kwargs.get("cancel_check")
        phase_update = kwargs.get("phase_update")
        if cancel_check:
            cancel_check()
        if phase_update:
            phase_update("CALCULATING_FACTS")
        return DailyFactsMaterializationResult(
            trade_date=TARGET,
            batch_id=None,
            status="PUBLISHED",
            rows_saved=25_020,
            plan_hash="b" * 64,
            content_hash="c" * 64,
            idempotent=False,
        )


class HistoryAuditorStub:
    def __init__(self, *, apply_ready: bool = True) -> None:
        self.calls = 0
        self.apply_ready = apply_ready

    def audit(self, session, *, start_date, end_date, cancel_check, progress_update):  # type: ignore[no-untyped-def]
        del session
        self.calls += 1
        assert start_date == TARGET and end_date == TARGET
        cancel_check()
        progress_update(0, 6, "trade_calendar")
        progress_update(6, 6, "equity_adj_factor")
        issues = ()
        if not self.apply_ready:
            from src.biz.services.wealth.market.sector_analysis.daily_facts.history_input_auditor import (
                HistoryInputAuditIssue,
            )

            issues = (
                HistoryInputAuditIssue(
                    code="SA_DAILY_FACT_SOURCE_NOT_READY",
                    source="dc_daily",
                    message="missing",
                    blocking=True,
                ),
            )
        return SectorAnalysisHistoryInputAudit(
            requested_start_date=TARGET,
            requested_end_date=TARGET,
            effective_start_date=TARGET,
            effective_end_date=TARGET,
            warmup_start_date=date(2026, 6, 1),
            ordered_trade_dates=(TARGET,),
            hierarchy_version="hierarchy-v1",
            source_coverage=(),
            issues=issues,
            audit_hash="d" * 64,
        )


class ReplayPlannerStub:
    def __init__(self, *, hierarchy_version: str = "hierarchy-v1") -> None:
        self.hierarchy_version = hierarchy_version
        self.calls = 0

    def resolve_scope(self, session, *, start_date, end_date):  # type: ignore[no-untyped-def]
        del session
        self.calls += 1
        assert start_date == TARGET and end_date == TARGET
        hierarchy = _hierarchy()
        if self.hierarchy_version != hierarchy.baseline_version:
            hierarchy = SectorHierarchySnapshot(
                baseline_version=self.hierarchy_version,
                published_at=hierarchy.published_at,
                nodes=hierarchy.nodes,
                nodes_by_code=hierarchy.nodes_by_code,
                children_by_parent=hierarchy.children_by_parent,
            )
        return SectorAnalysisReplayScope(
            requested_start_date=TARGET,
            requested_end_date=TARGET,
            start_date=TARGET,
            end_date=TARGET,
            open_trade_dates=(TARGET,),
            hierarchy=hierarchy,
        )


class AuditContextStub:
    task_run_id = 1

    def __init__(self, *, canceled: bool = False) -> None:
        self.canceled = canceled
        self.phases = []

    def is_cancel_requested(self) -> bool:
        return self.canceled

    def update_audit_phase(self, **kwargs):  # type: ignore[no-untyped-def]
        self.phases.append(kwargs)


class RunContextStub:
    def __init__(self, *, canceled: bool = False) -> None:
        self.canceled = canceled
        self.progress = []

    def is_cancel_requested(self, *, run_id):  # type: ignore[no-untyped-def]
        assert run_id == 7
        return self.canceled

    def update_progress(self, **kwargs):  # type: ignore[no-untyped-def]
        self.progress.append(kwargs)


def _factory():  # type: ignore[no-untyped-def]
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    return sessionmaker(bind=engine, expire_on_commit=False)


def _executor(*, materializer=None, planner=None, auditor=None):  # type: ignore[no-untyped-def]
    return SectorAnalysisDailyTaskExecutor(
        session_factory=_factory(),
        materialization_service=materializer or MaterializationStub(),  # type: ignore[arg-type]
        replay_planner=planner or ReplayPlannerStub(),  # type: ignore[arg-type]
        history_input_auditor=auditor or HistoryAuditorStub(),  # type: ignore[arg-type]
    )


def test_daily_executor_keeps_existing_preview_bound_hash_contract() -> None:
    materializer = MaterializationStub()
    executor = _executor(materializer=materializer)
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
    executor.execute_unit(plan.units[0])

    assert materializer.preview_calls == 1
    assert materializer.materialize_calls == [
        {
            "trade_date": TARGET,
            "expected_source_hash": "a" * 64,
            "expected_plan_hash": "b" * 64,
            "expected_content_hash": "c" * 64,
        }
    ]


def test_history_audit_creates_static_units_without_preview_or_formula_hashes() -> None:
    materializer = MaterializationStub()
    auditor = HistoryAuditorStub()
    context = AuditContextStub()
    executor = _executor(materializer=materializer, auditor=auditor)

    plan = executor.audit_for_task_run(
        MaintenanceExecutionRequest(
            action_key=REPLAY_ACTION_KEY,
            params={"start_date": TARGET.isoformat(), "end_date": TARGET.isoformat()},
        ),
        context=context,
    )

    assert plan.apply_ready is True
    assert plan.plan_hash == "d" * 64
    assert materializer.preview_calls == 0
    assert materializer.materialize_calls == []
    assert plan.units[0].payload["audit_contract_version"] == (
        HISTORY_INPUT_AUDIT_CONTRACT_VERSION
    )
    assert "expected_source_hash" not in plan.units[0].payload
    assert "expected_fact_count_ranges" not in plan.units[0].payload
    assert context.phases[-1]["audit_done"] == 6


def test_history_apply_materializes_once_without_preview_and_reports_progress() -> None:
    materializer = MaterializationStub()
    executor = _executor(materializer=materializer)
    plan = executor.audit_for_task_run(
        MaintenanceExecutionRequest(
            action_key=REPLAY_ACTION_KEY,
            params={"start_date": TARGET.isoformat(), "end_date": TARGET.isoformat()},
        ),
        context=AuditContextStub(),
    )
    run_context = RunContextStub()

    result = executor.execute_unit_for_task_run(
        plan.units[0],
        context=MaintenanceTaskRunContext(task_run_id=7, run_context=run_context),  # type: ignore[arg-type]
    )

    assert result.rows_saved == 25_020
    assert materializer.preview_calls == 0
    assert len(materializer.materialize_calls) == 1
    call = materializer.materialize_calls[0]
    assert call["expected_hierarchy_version"] == "hierarchy-v1"
    assert "expected_source_hash" not in call
    assert run_context.progress[-1]["unit_done"] == 0


def test_history_apply_rejects_old_plan_contract_before_preview_or_write() -> None:
    materializer = MaterializationStub()
    executor = _executor(materializer=materializer)
    old_unit = MaintenanceExecutionUnit(
        unit_key=f"wealth-sector-analysis-daily:{TARGET.isoformat()}",
        payload={
            "replay_unit": True,
            "trade_date": TARGET.isoformat(),
            "expected_source_hash": "a" * 64,
        },
    )

    with pytest.raises(
        SectorAnalysisDailyFactsPlanDriftError,
        match="旧版历史PLAN",
    ):
        executor.execute_unit(old_unit)
    assert materializer.preview_calls == 0
    assert materializer.materialize_calls == []


def test_history_apply_rejects_scope_drift_and_cancellation_before_write() -> None:
    materializer = MaterializationStub()
    executor = _executor(
        materializer=materializer,
        planner=ReplayPlannerStub(hierarchy_version="hierarchy-v2"),
    )
    plan = executor.audit_for_task_run(
        MaintenanceExecutionRequest(
            action_key=REPLAY_ACTION_KEY,
            params={"start_date": TARGET.isoformat(), "end_date": TARGET.isoformat()},
        ),
        context=AuditContextStub(),
    )
    with pytest.raises(SectorAnalysisDailyFactsPlanDriftError, match="层级版本"):
        executor.execute_unit(plan.units[0])
    assert materializer.materialize_calls == []

    canceled_executor = _executor(materializer=materializer)
    with pytest.raises(IngestionCanceledError):
        canceled_executor.execute_unit_for_task_run(
            plan.units[0],
            context=MaintenanceTaskRunContext(
                task_run_id=7,
                run_context=RunContextStub(canceled=True),  # type: ignore[arg-type]
            ),
        )
    assert materializer.materialize_calls == []


def test_history_request_rejects_legacy_plan_apply_parameters() -> None:
    with pytest.raises(ValueError, match="no longer accepts"):
        _executor().audit_for_task_run(
            MaintenanceExecutionRequest(
                action_key=REPLAY_ACTION_KEY,
                params={
                    "start_date": TARGET.isoformat(),
                    "end_date": TARGET.isoformat(),
                    "execution_mode": "PLAN",
                },
            ),
            context=AuditContextStub(),
        )

    assert FORMULA_BUNDLE_VERSION and TEMPLATE_VERSION
