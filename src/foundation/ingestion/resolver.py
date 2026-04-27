from __future__ import annotations

from calendar import monthrange
from dataclasses import replace
from datetime import date
import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.execution_plan import (
    DatasetActionRequest,
    DatasetExecutionPlan,
    DatasetTimeInput,
    ExecutionTimeScope,
    PlanObservability,
    PlanPlanning,
    PlanSource,
    PlanTransactionPolicy,
    PlanWriting,
)
from src.foundation.ingestion.unit_planner import DatasetUnitPlanner
from src.foundation.ingestion.validator import DatasetRequestValidator


class DatasetActionResolver:
    def __init__(self, session: Session, *, strict_contract: bool = True) -> None:
        self.session = session
        self.strict_contract = strict_contract
        self.validator = DatasetRequestValidator()
        self.unit_planner = DatasetUnitPlanner(session)

    def build_plan(self, request: DatasetActionRequest) -> DatasetExecutionPlan:
        if request.action != "maintain":
            raise ValueError(f"unsupported dataset action: {request.action}")
        definition = get_dataset_definition(request.dataset_key)
        action = definition.capabilities.get_action(request.action)
        if action is None:
            raise ValueError(f"dataset={request.dataset_key} does not support action={request.action}")

        normalized_time = self._normalize_time_input(request.time_input, definition.date_model.input_shape)
        run_profile = self._resolve_run_profile(normalized_time)
        normalized_request = replace(request, time_input=normalized_time)
        validated = self.validator.validate(
            request=normalized_request,
            definition=definition,
            run_profile=run_profile,
            strict=self.strict_contract,
        )
        units = self.unit_planner.plan(validated, definition)

        plan_id = self._plan_id(
            dataset_key=request.dataset_key,
            action=request.action,
            run_profile=run_profile,
            params=validated.params,
            unit_ids=tuple(unit.unit_id for unit in units),
        )
        return DatasetExecutionPlan(
            plan_id=plan_id,
            dataset_key=request.dataset_key,
            action=request.action,
            run_profile=run_profile,
            time_scope=self._time_scope(normalized_time),
            filters=dict(validated.params),
            source=PlanSource(
                source_key=validated.source_key or definition.source.source_key_default,
                adapter_key=definition.source.adapter_key,
                api_name=definition.source.api_name,
                fields=definition.source.source_fields,
            ),
            planning=PlanPlanning(
                universe_policy=definition.planning.universe_policy,
                enum_fanout_fields=definition.planning.enum_fanout_fields,
                enum_fanout_defaults=definition.planning.enum_fanout_defaults,
                pagination_policy=definition.planning.pagination_policy,
                chunk_size=definition.planning.chunk_size,
                max_units_per_execution=definition.planning.max_units_per_execution,
                unit_count=len(units),
            ),
            writing=PlanWriting(
                target_table=definition.storage.target_table,
                raw_dao_name=definition.storage.raw_dao_name,
                core_dao_name=definition.storage.core_dao_name,
                conflict_columns=definition.storage.conflict_columns,
                write_path=definition.storage.write_path,
            ),
            transaction=PlanTransactionPolicy(
                commit_policy=definition.transaction.commit_policy,
                idempotent_write_required=definition.transaction.idempotent_write_required,
                write_volume_assessment=definition.transaction.write_volume_assessment,
            ),
            observability=PlanObservability(
                progress_label=definition.observability.progress_label,
                observed_field=definition.date_model.observed_field,
                audit_applicable=definition.date_model.audit_applicable,
            ),
            units=units,
        )

    @staticmethod
    def _resolve_run_profile(time_input: DatasetTimeInput) -> str:
        if time_input.mode == "point":
            return "point_incremental"
        if time_input.mode == "range":
            return "range_rebuild"
        if time_input.mode == "none":
            return "snapshot_refresh"
        raise ValueError(f"unsupported time_input.mode={time_input.mode}")

    @classmethod
    def _normalize_time_input(cls, time_input: DatasetTimeInput, input_shape: str) -> DatasetTimeInput:
        mode = str(time_input.mode or "none").strip() or "none"
        normalized = replace(time_input, mode=mode)
        if mode == "point" and input_shape == "month_or_range":
            month = cls._normalize_month(normalized.month)
            return replace(normalized, month=month, trade_date=cls._month_end_date(month))
        if mode == "range" and input_shape in {"month_or_range", "start_end_month_window"}:
            start_month = cls._normalize_month(normalized.start_month)
            end_month = cls._normalize_month(normalized.end_month)
            return replace(
                normalized,
                start_month=start_month,
                end_month=end_month,
                start_date=cls._month_start_date(start_month),
                end_date=cls._month_end_date(end_month),
            )
        return normalized

    @staticmethod
    def _time_scope(time_input: DatasetTimeInput) -> ExecutionTimeScope:
        if time_input.mode == "point":
            value = time_input.month or time_input.trade_date
            return ExecutionTimeScope(mode="point", start=value, end=value, label=str(value or ""))
        if time_input.mode == "range":
            start = time_input.start_month or time_input.start_date
            end = time_input.end_month or time_input.end_date
            return ExecutionTimeScope(mode="range", start=start, end=end, label=f"{start} ~ {end}")
        return ExecutionTimeScope(mode="none", label="无时间维度")

    @staticmethod
    def _plan_id(*, dataset_key: str, action: str, run_profile: str, params: dict[str, Any], unit_ids: tuple[str, ...]) -> str:
        payload = json.dumps(
            {
                "dataset_key": dataset_key,
                "action": action,
                "run_profile": run_profile,
                "params": DatasetActionResolver._jsonable(params),
                "unit_ids": unit_ids,
            },
            ensure_ascii=True,
            sort_keys=True,
        )
        digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
        return f"{dataset_key}:{action}:{run_profile}:{digest}"

    @staticmethod
    def _jsonable(value: Any) -> Any:
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, dict):
            return {key: DatasetActionResolver._jsonable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [DatasetActionResolver._jsonable(item) for item in value]
        return value

    @staticmethod
    def _normalize_month(value: str | None) -> str:
        text = str(value or "").strip().replace("-", "")
        if len(text) != 6 or not text.isdigit():
            raise ValueError("月份必须是 YYYYMM 或 YYYY-MM")
        month = int(text[4:6])
        if month < 1 or month > 12:
            raise ValueError("月份值无效")
        return text

    @staticmethod
    def _month_start_date(month: str) -> date:
        return date(int(month[:4]), int(month[4:6]), 1)

    @staticmethod
    def _month_end_date(month: str) -> date:
        year = int(month[:4])
        month_value = int(month[4:6])
        return date(year, month_value, monthrange(year, month_value)[1])
