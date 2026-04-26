from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import delete, func, inspect, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.foundation.datasets.registry import get_dataset_definition_by_action_key
from src.foundation.models.core_serving_light.equity_daily_bar_light import EquityDailyBarLight
from src.ops.models.ops.dataset_layer_snapshot_history import DatasetLayerSnapshotHistory
from src.ops.models.ops.dataset_layer_snapshot_current import DatasetLayerSnapshotCurrent
from src.ops.models.ops.dataset_pipeline_mode import DatasetPipelineMode
from src.ops.models.ops.dataset_status_snapshot import DatasetStatusSnapshot
from src.ops.queries.freshness_query_service import OpsFreshnessQueryService
from src.ops.schemas.freshness import DatasetFreshnessItem, FreshnessGroup, OpsFreshnessResponse
from src.ops.dataset_status_projection import snapshot_row_to_freshness_item
from src.ops.specs import (
    get_dataset_freshness_spec,
    get_workflow_spec,
    list_dataset_freshness_specs,
)


class DatasetStatusSnapshotService:
    def __init__(self, query_service: OpsFreshnessQueryService | None = None) -> None:
        self.query_service = query_service or OpsFreshnessQueryService()

    def rebuild_all(self, session: Session, *, today: date | None = None, strict: bool = False) -> int:
        try:
            items = self.query_service.build_live_items(session, today=today)
            session.execute(delete(DatasetStatusSnapshot))
            snapshot_date = today or datetime.now(timezone.utc).date()
            self._upsert_items(session, items, snapshot_date=snapshot_date)
            self._append_history_items(session, items, snapshot_date=snapshot_date)
            self._upsert_current_items(session, items)
            session.commit()
            return len(items)
        except SQLAlchemyError:
            session.rollback()
            if strict:
                raise
            return 0

    def refresh_resources(self, session: Session, resource_keys: list[str], *, today: date | None = None, strict: bool = False) -> int:
        target_keys = sorted(set(resource_keys))
        if not target_keys:
            return 0
        try:
            items = self.query_service.build_live_items(session, today=today, resource_keys=target_keys)
            snapshot_date = today or datetime.now(timezone.utc).date()
            self._upsert_items(session, items, snapshot_date=snapshot_date)
            self._append_history_items(session, items, snapshot_date=snapshot_date)
            self._upsert_current_items(session, items)
            session.commit()
            return len(items)
        except SQLAlchemyError:
            session.rollback()
            if strict:
                raise
            return 0

    def refresh_for_execution(
        self,
        session: Session,
        *,
        spec_type: str,
        spec_key: str,
        today: date | None = None,
        strict: bool = False,
    ) -> int:
        return self.refresh_resources(
            session,
            self._resource_keys_for_spec(spec_type=spec_type, spec_key=spec_key),
            today=today,
            strict=strict,
        )

    def read_snapshot(self, session: Session) -> OpsFreshnessResponse | None:
        try:
            rows = list(session.scalars(select(DatasetStatusSnapshot).order_by(DatasetStatusSnapshot.domain_key, DatasetStatusSnapshot.display_name)))
            if not rows:
                return None
            items = [self._to_item(row) for row in rows]
            groups = self.query_service._group_items(items)
            summary = self.query_service._build_summary(items)
            return OpsFreshnessResponse(summary=summary, groups=groups)
        except SQLAlchemyError:
            session.rollback()
            return None

    @staticmethod
    def _to_item(row: DatasetStatusSnapshot) -> DatasetFreshnessItem:
        spec = get_dataset_freshness_spec(row.resource_key)
        return snapshot_row_to_freshness_item(row, raw_table=spec.raw_table if spec is not None else None)

    @staticmethod
    def _resource_keys_for_spec(*, spec_type: str, spec_key: str) -> list[str]:
        if spec_type == "dataset_action":
            try:
                definition, _action = get_dataset_definition_by_action_key(spec_key)
            except KeyError:
                return []
            resource_key = definition.dataset_key
            if get_dataset_freshness_spec(resource_key) is None:
                return []
            return [resource_key]
        if spec_type == "job":
            return []
        if spec_type == "workflow":
            workflow_spec = get_workflow_spec(spec_key)
            if workflow_spec is None:
                return []
            resource_keys: list[str] = []
            for step in workflow_spec.steps:
                try:
                    definition, _action = get_dataset_definition_by_action_key(step.job_key)
                except KeyError:
                    continue
                if get_dataset_freshness_spec(definition.dataset_key) is not None:
                    resource_keys.append(definition.dataset_key)
            return resource_keys
        return []

    def _upsert_items(self, session: Session, items: list[DatasetFreshnessItem], *, snapshot_date: date) -> None:
        calculated_at = datetime.now(timezone.utc)
        for item in items:
            row = session.get(DatasetStatusSnapshot, item.dataset_key)
            if row is None:
                row = DatasetStatusSnapshot(dataset_key=item.dataset_key)
                session.add(row)
            row.resource_key = item.resource_key
            row.display_name = item.display_name
            row.domain_key = item.domain_key
            row.domain_display_name = item.domain_display_name
            row.target_table = item.target_table
            row.cadence = item.cadence
            row.earliest_business_date = item.earliest_business_date
            row.observed_business_date = item.observed_business_date
            row.latest_business_date = item.latest_business_date
            row.freshness_note = item.freshness_note
            row.latest_success_at = item.latest_success_at
            row.last_sync_date = item.last_sync_date
            row.expected_business_date = item.expected_business_date
            row.lag_days = item.lag_days
            row.freshness_status = item.freshness_status
            row.recent_failure_message = item.recent_failure_message
            row.recent_failure_summary = item.recent_failure_summary
            row.recent_failure_at = item.recent_failure_at
            row.primary_action_key = item.primary_action_key
            row.snapshot_date = snapshot_date
            row.last_calculated_at = calculated_at

    @staticmethod
    def _append_history_items(session: Session, items: list[DatasetFreshnessItem], *, snapshot_date: date) -> None:
        calculated_at = datetime.now(timezone.utc)
        for item in items:
            session.add(
                DatasetLayerSnapshotHistory(
                    snapshot_date=snapshot_date,
                    dataset_key=item.dataset_key,
                    source_key=None,
                    stage="serving",
                    status=item.freshness_status,
                    rows_in=None,
                    rows_out=None,
                    error_count=1 if item.recent_failure_summary else 0,
                    last_success_at=item.latest_success_at,
                    last_failure_at=item.recent_failure_at,
                    lag_seconds=(item.lag_days * 86400) if item.lag_days is not None else None,
                    message=item.freshness_note,
                    calculated_at=calculated_at,
                    snapshot_at=calculated_at,
                    execution_id=None,
                    status_reason_code=DatasetStatusSnapshotService._status_reason_code(item.freshness_status),
                )
            )

    @staticmethod
    def _upsert_current_items(session: Session, items: list[DatasetFreshnessItem]) -> None:
        calculated_at = datetime.now(timezone.utc)
        keys = [item.dataset_key for item in items]
        mode_by_key = {
            row.dataset_key: row
            for row in session.scalars(select(DatasetPipelineMode).where(DatasetPipelineMode.dataset_key.in_(keys))).all()
        }
        light_snapshot_by_dataset = DatasetStatusSnapshotService._load_light_snapshot_by_dataset(session, keys)
        for item in items:
            mode = mode_by_key.get(item.dataset_key)
            if mode is None:
                mode = DatasetStatusSnapshotService._inferred_mode_from_item(item)
            source_key = "__all__"
            if "," not in mode.source_scope and mode.source_scope.strip():
                source_key = mode.source_scope.strip()

            def upsert_stage(stage: str, status: str, message: str | None) -> None:
                pk = (item.dataset_key, source_key, stage)
                row = session.get(DatasetLayerSnapshotCurrent, pk)
                if row is None:
                    row = DatasetLayerSnapshotCurrent(dataset_key=item.dataset_key, source_key=source_key, stage=stage)
                    session.add(row)
                row.status = status
                row.rows_in = None
                row.rows_out = None
                row.error_count = 1 if item.recent_failure_summary and stage == "serving" else 0
                row.last_success_at = item.latest_success_at if stage == "serving" else None
                row.last_failure_at = item.recent_failure_at if stage == "serving" else None
                row.lag_seconds = (item.lag_days * 86400) if (item.lag_days is not None and stage == "serving") else None
                row.message = message
                row.calculated_at = calculated_at
                row.state_updated_at = calculated_at
                row.status_reason_code = DatasetStatusSnapshotService._status_reason_code(status)
                row.execution_id = None
                row.run_profile = None

            upsert_stage("raw", item.freshness_status if mode.raw_enabled else "skipped", mode.notes)
            if mode.std_enabled:
                upsert_stage("std", "unobserved", "该层已启用，但暂未接入独立观测指标")
            else:
                upsert_stage("std", "skipped", "当前模式未启用 std 物化")
            if mode.resolution_enabled:
                upsert_stage("resolution", "unobserved", "该层已启用，但暂未接入独立观测指标")
            else:
                upsert_stage("resolution", "skipped", "当前模式未启用融合决策层")
            if mode.serving_enabled:
                upsert_stage("serving", item.freshness_status, item.freshness_note)
            else:
                upsert_stage("serving", "skipped", "当前模式不产出 serving")
            light_snapshot = light_snapshot_by_dataset.get(item.dataset_key)
            if item.dataset_key == "daily" and mode.serving_enabled:
                pk = (item.dataset_key, source_key, "light")
                row = session.get(DatasetLayerSnapshotCurrent, pk)
                if row is None:
                    row = DatasetLayerSnapshotCurrent(dataset_key=item.dataset_key, source_key=source_key, stage="light")
                    session.add(row)
                if light_snapshot is None:
                    row.status = "unknown"
                    row.rows_in = None
                    row.rows_out = None
                    row.error_count = 0
                    row.last_success_at = None
                    row.last_failure_at = None
                    row.lag_seconds = None
                    row.message = "轻量层尚未初始化，暂无可用快照。"
                else:
                    light_status = DatasetStatusSnapshotService._resolve_light_status(
                        expected_business_date=item.latest_business_date,
                        light_latest_business_date=light_snapshot["latest_business_date"],
                    )
                    row.status = light_status
                    row.rows_in = light_snapshot["rows_on_latest_day"]
                    row.rows_out = light_snapshot["rows_on_latest_day"]
                    row.error_count = 0
                    row.last_success_at = light_snapshot["updated_at"]
                    row.last_failure_at = None
                    row.lag_seconds = DatasetStatusSnapshotService._resolve_light_lag_seconds(
                        expected_business_date=item.latest_business_date,
                        light_latest_business_date=light_snapshot["latest_business_date"],
                    )
                    row.message = (
                        f"轻量层最新业务日 {light_snapshot['latest_business_date'].isoformat()}，"
                        f"最近刷新 {light_snapshot['updated_at'].isoformat() if light_snapshot['updated_at'] else '未知'}。"
                        if light_snapshot["latest_business_date"] is not None
                        else "轻量层暂无可用数据。"
                    )
                row.calculated_at = calculated_at

            snapshot_row = session.get(DatasetStatusSnapshot, item.dataset_key)
            if snapshot_row is not None:
                snapshot_row.pipeline_mode = mode.mode
                snapshot_row.raw_stage_status = item.freshness_status if mode.raw_enabled else "skipped"
                snapshot_row.std_stage_status = "unobserved" if mode.std_enabled else "skipped"
                snapshot_row.resolution_stage_status = "unobserved" if mode.resolution_enabled else "skipped"
                snapshot_row.serving_stage_status = item.freshness_status if mode.serving_enabled else "skipped"
                snapshot_row.state_updated_at = calculated_at

    @staticmethod
    def _status_reason_code(status: str | None) -> str | None:
        if status in {"healthy", "success"}:
            return "ok"
        if status in {"lagging", "stale"}:
            return "lagging"
        if status in {"unknown", "unobserved"}:
            return "unobserved"
        if status in {"failed", "error"}:
            return "failed"
        if status == "skipped":
            return "skipped"
        return None

    @staticmethod
    def _load_light_snapshot_by_dataset(session: Session, dataset_keys: list[str]) -> dict[str, dict[str, object | None]]:
        if "daily" not in dataset_keys:
            return {}
        bind = session.get_bind()
        if bind is None:
            return {}
        inspector = inspect(bind)
        if not inspector.has_table("equity_daily_bar_light", schema="core_serving_light"):
            return {}
        try:
            latest_business_date, updated_at = session.execute(
                select(
                    func.max(EquityDailyBarLight.trade_date),
                    func.max(EquityDailyBarLight.updated_at),
                )
            ).one()
            rows_on_latest_day = None
            if latest_business_date is not None:
                rows_on_latest_day = session.scalar(
                    select(func.count())
                    .select_from(EquityDailyBarLight)
                    .where(EquityDailyBarLight.trade_date == latest_business_date)
                )
            return {
                "daily": {
                    "latest_business_date": latest_business_date,
                    "updated_at": updated_at,
                    "rows_on_latest_day": int(rows_on_latest_day or 0) if latest_business_date is not None else None,
                }
            }
        except SQLAlchemyError:
            return {}

    @staticmethod
    def _resolve_light_status(
        *,
        expected_business_date: date | None,
        light_latest_business_date: date | None,
    ) -> str:
        if light_latest_business_date is None:
            return "unknown"
        if expected_business_date is None:
            return "healthy"
        lag_days = (expected_business_date - light_latest_business_date).days
        if lag_days <= 0:
            return "healthy"
        if lag_days <= 1:
            return "lagging"
        return "stale"

    @staticmethod
    def _resolve_light_lag_seconds(
        *,
        expected_business_date: date | None,
        light_latest_business_date: date | None,
    ) -> int | None:
        if expected_business_date is None or light_latest_business_date is None:
            return None
        lag_days = (expected_business_date - light_latest_business_date).days
        if lag_days <= 0:
            return 0
        return lag_days * 86400

    @staticmethod
    def _inferred_mode_from_item(item: DatasetFreshnessItem) -> DatasetPipelineMode:
        if item.dataset_key == "stock_basic":
            return DatasetPipelineMode(
                dataset_key=item.dataset_key,
                mode="multi_source_pipeline",
                source_scope="tushare,biying",
                raw_enabled=True,
                std_enabled=True,
                resolution_enabled=True,
                serving_enabled=True,
                notes="按规格推断：双源标准化+融合发布链路",
            )
        target = item.target_table or ""
        raw_table = item.raw_table or ""
        if target.startswith("raw_") or target.startswith("raw."):
            scope = "biying" if raw_table.startswith("raw_biying.") else "tushare"
            return DatasetPipelineMode(
                dataset_key=item.dataset_key,
                mode="raw_only",
                source_scope=scope,
                raw_enabled=True,
                std_enabled=False,
                resolution_enabled=False,
                serving_enabled=False,
                notes="按规格推断：仅采集原始数据",
            )
        if target.startswith("core_serving."):
            scope = "biying" if raw_table.startswith("raw_biying.") else "tushare"
            return DatasetPipelineMode(
                dataset_key=item.dataset_key,
                mode="single_source_direct",
                source_scope=scope,
                raw_enabled=True,
                std_enabled=False,
                resolution_enabled=False,
                serving_enabled=True,
                notes="按规格推断：单源直出 serving",
            )
        return DatasetPipelineMode(
            dataset_key=item.dataset_key,
            mode="legacy_core_direct",
            source_scope="tushare",
            raw_enabled=True,
            std_enabled=False,
            resolution_enabled=False,
            serving_enabled=False,
            notes="按规格推断：历史保留路径（core 口径）",
        )
