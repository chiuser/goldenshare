"""Connect the daily-basic column fill to existing maintenance PLAN/APPLY."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import date, datetime, timezone
from importlib.metadata import version

from sqlalchemy import select, text, update

from src.foundation.config.settings import get_settings
from src.foundation.ingestion.daily_basic_limit_status import (
    PLAN_CONTRACT,
    TARGET_TABLES,
    DailyBasicLimitStatusService,
    statement_timeout,
)
from src.foundation.ingestion.daily_basic_limit_status_fields import DAILY_BASIC_LIMIT_STATUS_DOWNLOAD_FIELDS
from src.foundation.ingestion.run_errors import IngestionCanceledError
from src.ops.action_catalog import get_maintenance_action
from src.ops.models.ops.task_run import TaskRun
from src.ops.models.ops.task_run_node import TaskRunNode
from src.ops.runtime.maintenance_executor import (
    MaintenanceExecutionPlan,
    MaintenanceExecutionResult,
    MaintenanceExecutionUnit,
    MaintenancePlanCheckpoint,
)
from src.ops.services.task_run_ingestion_context import TaskRunIngestionContext


ACTION_KEY = "maintenance.fill_daily_basic_limit_status"
LOGGER = logging.getLogger(__name__)


class DailyBasicLimitStatusTaskExecutor:
    def __init__(self, *, session_factory, service=None, clock=time.monotonic):
        self._session_factory = session_factory
        self._service = service if service is not None else DailyBasicLimitStatusService(session_factory=session_factory)
        self._clock = clock

    def plan(self, request):
        raise ValueError("每日指标补录必须通过带 TaskRun 上下文的 PLAN")

    def execute_unit(self, unit):
        raise ValueError("每日指标补录必须引用成功 PLAN 并通过 TaskRun APPLY")

    def plan_for_task_run(self, request, *, context):
        # The catalog owns the operational limits. They are not source API inputs.
        config = {key: get_maintenance_action(ACTION_KEY).execution_config[key] for key in (
            "source_timeout_seconds", "statement_timeout_seconds",
            "observation_timeout_seconds", "progress_interval_seconds",
        )}
        config["sync_batch_size"] = get_settings().sync_batch_size
        start = date.fromisoformat(str(request.params["start_date"]))
        end = date.fromisoformat(str(request.params["end_date"]))
        metadata = {
            "contract_kind": PLAN_CONTRACT, "dataset_key": "daily_basic", "action_key": ACTION_KEY,
            "start_date": str(start), "end_date": str(end), "target_tables": list(TARGET_TABLES),
            "key_fields": ["ts_code", "trade_date"], "update_columns": ["limit_status"],
            "source_fields": list(DAILY_BASIC_LIMIT_STATUS_DOWNLOAD_FIELDS),
            "missing_source_policy": "keep_existing_status_for_non_expected_stocks",
            "required_codes_source": "core_serving.equity_daily_bar",
            "update_scope": "exclude_b_shares",
            "expected_stock_sources": ["core_serving.equity_daily_bar", "raw_tushare.suspend_d"],
            "storage_mappings": {table: {"ts_code": "VARCHAR(16)", "trade_date": "DATE", "limit_status": "INTEGER"}
                                 for table in TARGET_TABLES},
            "execution_config": config, "code_version": version("goldenshare"),
            "config_sources": {"sync_batch_size": "Settings.sync_batch_size",
                               "limits": "maintenance.fill_daily_basic_limit_status.execution_config"},
        }

        def check():
            if context.is_cancel_requested():
                raise IngestionCanceledError("每日指标 PLAN 已收到停止请求")

        def checkpoint(payloads, total, phase):
            check()
            metadata["dates"] = [item["trade_date"] for item in payloads]
            metadata["date_counts"] = {item["trade_date"]: {
                "raw_count": item["raw_count"], "serving_count": item["serving_count"],
            } for item in payloads}
            context.save_checkpoint(MaintenancePlanCheckpoint(
                unit_done=len(payloads), unit_total=total,
                units=tuple(self._unit(payload) for payload in payloads), gaps=(),
                metadata=metadata, expected_rows=sum(item["serving_count"] for item in payloads), phase=phase,
                current_object={"entity": {"name": "每日指标"}, "time": {"start": str(start), "end": str(end)},
                                "attributes": {"enum_value": phase}},
            ))

        with self._session_factory() as session:
            payloads = self._service.plan_dates(session, start_date=start, end_date=end,
                config=config, check=check, on_batch=checkpoint)
        check()
        units = tuple(self._unit(payload) for payload in payloads)
        # Same snapshot/hash protocol as other maintenance actions; no new format.
        encoded = json.dumps({"metadata": metadata, "units": payloads}, sort_keys=True, separators=(",", ":")).encode()
        return MaintenanceExecutionPlan(plan_hash=hashlib.sha256(encoded).hexdigest(), units=units,
            expected_rows=sum(item["serving_count"] for item in payloads), metadata=metadata)

    @staticmethod
    def _unit(payload):
        return MaintenanceExecutionUnit(unit_key=f"daily_basic:{payload['trade_date']}", payload=dict(payload))

    def execute_unit_for_task_run(self, unit, *, context):
        # Dispatcher validated the referenced PLAN. Project only the inputs needed
        # by this date; never load its full date list or revalidate its hash here.
        with self._session_factory() as session:
            current = session.execute(select(
                TaskRun.request_payload_json, TaskRun.filters_json, TaskRun.current_node_id,
                TaskRun.unit_done, TaskRun.rows_fetched, TaskRun.rows_saved,
            ).where(TaskRun.id == context.task_run_id)).one()
            params = {**current.request_payload_json, **current.request_payload_json.get("filters", {}),
                      **current.filters_json}
            config, contract = session.execute(select(
                TaskRun.plan_snapshot_json["metadata"]["execution_config"],
                TaskRun.plan_snapshot_json["metadata"]["contract_kind"],
            ).where(
                TaskRun.id == int(params["plan_task_run_id"]),
            )).one()
        if contract != PLAN_CONTRACT:
            raise ValueError("旧补录计划的交易日应有股票范围或 B 股更新范围已变更，请重新生成 PLAN 后执行")
        last_write = None
        day = unit.payload["trade_date"]

        def observe(phase, *, page=None, tick=False):
            nonlocal last_write
            now = self._clock()
            if tick and last_write is not None and now - last_write < config["progress_interval_seconds"]:
                return
            last_write = now
            diagnostics = {"daily_basic_limit_status": {"phase": phase, "trade_date": day,
                "page": page, "eta": "暂无法估算"}}
            current_object = {"entity": {"kind": "enum", "name": "每日指标"},
                "time": {"start": day, "end": day, "field": "trade_date"},
                "attributes": {"enum_value": phase + (f"，第 {page} 页" if page is not None else "")
                               + "；预计完成：暂无法估算"}}
            try:
                with self._session_factory() as observation:
                    statement_timeout(observation, config["observation_timeout_seconds"])
                    observation.execute(text("SELECT set_config('lock_timeout', :value, true)"),
                                        {"value": f"{config['observation_timeout_seconds']}s"})
                    observation.execute(update(TaskRun).where(TaskRun.id == context.task_run_id).values(
                        current_object_json=current_object, ingestion_diagnostics_json=diagnostics,
                        updated_at=datetime.now(timezone.utc),
                    ))
                    observation.execute(update(TaskRunNode).where(TaskRunNode.id == current.current_node_id).values(
                        ingestion_diagnostics_json=diagnostics,
                    ))
                    observation.commit()
            except Exception:
                LOGGER.exception("每日指标补录进度保存失败，业务事务不受影响")

        with self._session_factory() as control:
            cancel = TaskRunIngestionContext(control, independent_cancel=True,
                                            timeout_seconds=config["observation_timeout_seconds"])

            def check():
                if cancel.is_cancel_requested(run_id=context.task_run_id):
                    raise IngestionCanceledError("每日指标补录已收到停止请求")

            check()
            result = self._service.execute_day(unit.payload, config=config, check=check, observe=observe)
        summary = f"{day} 每日指标收盘涨跌状态已覆盖 {result['rows_saved']} 行"
        phase = "已完成" if not result["already_complete"] else "已核对，跳过"
        null_codes = result.get("null_not_expected_codes", [])
        suspended_codes = result.get("null_suspended_codes", [])
        excluded_b_shares = result.get("excluded_b_share_codes", [])
        if null_codes:
            summary += f"，其中 {len(null_codes)} 行不属于交易日应有股票且源无有效状态，收盘涨跌状态留空"
        if suspended_codes:
            summary += f"，其中 {len(suspended_codes)} 行为当天无日线且全天停牌，收盘涨跌状态留空"
        if null_codes or suspended_codes:
            phase += f"，其中 {len(null_codes) + len(suspended_codes)} 行收盘涨跌状态留空"
        if excluded_b_shares:
            summary += f"，其中 {len(excluded_b_shares)} 行 B 股原样保留"
            phase += f"，其中 {len(excluded_b_shares)} 行 B 股原样保留"
        return MaintenanceExecutionResult(rows_fetched=result["rows_fetched"], rows_saved=result["rows_saved"],
            summary_message=summary,
            metadata={"daily_basic_limit_status": {**result, "trade_date": day,
                "phase": phase, "eta": "暂无法估算"}})
