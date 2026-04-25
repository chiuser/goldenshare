from __future__ import annotations

from calendar import monthrange
from dataclasses import replace
from datetime import date, datetime
import hashlib
import json
from typing import Any
from uuid import uuid4

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
    PlanUnitSnapshot,
    PlanWriting,
)
from src.foundation.services.sync_v2.contracts import RunRequest
from src.foundation.services.sync_v2.planner import SyncV2Planner
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.runtime_contract import to_runtime_contract
from src.foundation.services.sync_v2.validator import ContractValidator


class DatasetActionResolver:
    def __init__(self, session: Session, *, strict_contract: bool = True) -> None:
        self.session = session
        self.strict_contract = strict_contract
        self.validator = ContractValidator()
        self.planner = SyncV2Planner(session)

    def build_plan(self, request: DatasetActionRequest) -> DatasetExecutionPlan:
        if request.action != "maintain":
            raise ValueError(f"unsupported dataset action: {request.action}")
        definition = get_dataset_definition(request.dataset_key)
        action = definition.capabilities.get_action(request.action)
        if action is None:
            raise ValueError(f"dataset={request.dataset_key} does not support action={request.action}")

        contract = get_sync_v2_contract(request.dataset_key)
        normalized_time = self._normalize_time_input(request.time_input, contract.date_model.input_shape)
        run_profile = self._resolve_run_profile(normalized_time)
        params = self._build_params(normalized_time, request.filters)
        run_request = RunRequest(
            request_id=uuid4().hex,
            dataset_key=request.dataset_key,
            run_profile=run_profile,
            trigger_source=request.trigger_source,
            params=params,
            trade_date=normalized_time.trade_date,
            start_date=normalized_time.start_date,
            end_date=normalized_time.end_date,
            execution_id=request.execution_id,
        )
        validated = self.validator.validate(request=run_request, contract=contract, strict=self.strict_contract)
        runtime_contract = to_runtime_contract(contract)
        if runtime_contract.strategy_fn is not None:
            units = runtime_contract.strategy_fn(
                validated,
                contract,
                self.planner.dao,
                self.planner.settings,
                self.session,
            )
        else:
            units = self.planner.plan(validated, contract)

        unit_snapshots = tuple(
            PlanUnitSnapshot(
                unit_id=unit.unit_id,
                dataset_key=unit.dataset_key,
                source_key=unit.source_key,
                trade_date=unit.trade_date,
                request_params=dict(unit.request_params),
                progress_context=dict(unit.progress_context),
                pagination_policy=unit.pagination_policy,
                page_limit=unit.page_limit,
            )
            for unit in units
        )
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
            filters=dict(request.filters or {}),
            source=PlanSource(
                source_key=validated.source_key or contract.source_spec.source_key_default,
                adapter_key=contract.source_adapter_key,
                api_name=contract.source_spec.api_name,
                fields=contract.source_spec.fields,
            ),
            planning=PlanPlanning(
                universe_policy=contract.planning_spec.universe_policy,
                enum_fanout_fields=contract.planning_spec.enum_fanout_fields,
                enum_fanout_defaults=contract.planning_spec.enum_fanout_defaults,
                pagination_policy=contract.planning_spec.pagination_policy,
                chunk_size=contract.planning_spec.chunk_size,
                max_units_per_execution=contract.planning_spec.max_units_per_execution,
                unit_count=len(units),
            ),
            writing=PlanWriting(
                target_table=contract.write_spec.target_table,
                raw_dao_name=contract.write_spec.raw_dao_name,
                core_dao_name=contract.write_spec.core_dao_name,
                conflict_columns=contract.write_spec.conflict_columns,
                write_path=contract.write_spec.write_path,
            ),
            transaction=PlanTransactionPolicy(
                commit_policy=contract.transaction_spec.commit_policy,
                idempotent_write_required=contract.transaction_spec.idempotent_write_required,
                write_volume_assessment=contract.transaction_spec.write_volume_assessment,
            ),
            observability=PlanObservability(
                progress_label=contract.observe_spec.progress_label,
                observed_field=contract.date_model.observed_field,
                audit_applicable=contract.date_model.audit_applicable,
            ),
            units=unit_snapshots,
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
            return replace(
                normalized,
                month=month,
                trade_date=cls._month_end_date(month),
            )
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
    def _build_params(time_input: DatasetTimeInput, filters: dict[str, Any]) -> dict[str, Any]:
        params = dict(filters or {})
        for key in ("month", "date_field"):
            value = getattr(time_input, key)
            if value not in (None, ""):
                params[key] = value
        return params

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
            raise ValueError("month must be YYYYMM or YYYY-MM")
        month = int(text[4:6])
        if month < 1 or month > 12:
            raise ValueError("month must be a valid month")
        return text

    @staticmethod
    def _month_start_date(month: str) -> date:
        return date(int(month[:4]), int(month[4:6]), 1)

    @staticmethod
    def _month_end_date(month: str) -> date:
        year = int(month[:4])
        month_value = int(month[4:6])
        return date(year, month_value, monthrange(year, month_value)[1])
