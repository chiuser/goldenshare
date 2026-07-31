from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from src.foundation.config.settings import get_settings
from src.foundation.connectors.factory import create_source_connector
from src.foundation.dao.trade_calendar_dao import TradeCalendarDAO
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.execution_plan import DatasetActionRequest, DatasetTimeInput, PlanUnitSnapshot
from src.foundation.ingestion.resolver import DatasetActionResolver
from src.ops.models.ops.probe_rule import ProbeRule


IDX_FACTOR_PRO_REMOTE_READY_CONDITION = "remote_idx_factor_pro_ready"
IDX_FACTOR_PRO_REMOTE_READY_LABEL = "源站已有指数技术因子"
IDX_FACTOR_PRO_ACTION_KEY = "idx_factor_pro.maintain"
IDX_FACTOR_PRO_DATASET_KEY = "idx_factor_pro"
IDX_FACTOR_PRO_REMOTE_PROBE_FIELDS = ("ts_code", "trade_date")


@dataclass(frozen=True, slots=True)
class IdxFactorProRemoteReadinessProbeResult:
    matched: bool
    message: str
    payload: dict[str, Any]


class IdxFactorProRemoteReadinessProbeService:
    """Check same-day source availability without reading or writing business tables."""

    def evaluate(self, session: Session, rule: ProbeRule, *, current: datetime) -> IdxFactorProRemoteReadinessProbeResult:
        self._validate_rule(rule)
        business_date = current.astimezone(ZoneInfo("Asia/Shanghai")).date()
        exchange = str((rule.probe_condition_json or {}).get("exchange") or get_settings().default_exchange)
        business_day = TradeCalendarDAO(session).fetch_by_pk(exchange, business_date)
        if business_day is None:
            return self._non_trading_day_result(
                message=f"交易日历缺少 {business_date.isoformat()} 记录，已跳过源站指数技术因子探测",
                business_date=business_date,
                is_open=None,
            )
        if business_day.is_open is not True:
            return self._non_trading_day_result(
                message=f"{business_date.isoformat()} 非交易日，已跳过源站指数技术因子探测",
                business_date=business_date,
                is_open=False,
            )

        unit = self._build_probe_unit(session, latest_open_date=business_date, rule=rule)
        connector = create_source_connector(get_dataset_definition(IDX_FACTOR_PRO_DATASET_KEY).source.source_key_default)
        rows = connector.call(
            get_dataset_definition(IDX_FACTOR_PRO_DATASET_KEY).source.api_name,
            params={**dict(unit.request_params), "limit": 1, "offset": 0},
            fields=IDX_FACTOR_PRO_REMOTE_PROBE_FIELDS,
        )
        first_row = rows[0] if rows else None
        if not self._row_matches_trade_date(first_row, business_date):
            return self._result(
                matched=False,
                message="源站尚未返回目标交易日指数技术因子",
                business_date=business_date,
                latest_open_date=business_date,
                sample_request_count=1,
                row=first_row,
            )
        return self._result(
            matched=True,
            message="源站已返回目标交易日指数技术因子",
            business_date=business_date,
            latest_open_date=business_date,
            sample_request_count=1,
            row=first_row,
        )

    @staticmethod
    def _validate_rule(rule: ProbeRule) -> None:
        if rule.dataset_key != IDX_FACTOR_PRO_DATASET_KEY:
            raise ValueError("源站指数技术因子探测只支持指数技术因子（专业版）维护")
        action = dict(rule.on_success_action_json or {})
        if str(action.get("action_type") or "dataset_action") != "dataset_action":
            raise ValueError("源站指数技术因子探测只支持指数技术因子（专业版）维护")
        if str(action.get("action_key") or "").strip() != IDX_FACTOR_PRO_ACTION_KEY:
            raise ValueError("源站指数技术因子探测只支持指数技术因子（专业版）维护")
        request = dict(action.get("request") or {})
        if dict(request.get("filters") or {}):
            raise ValueError("源站指数技术因子探测不支持维护参数")
        if _has_fixed_or_non_point_time_input(request):
            raise ValueError("源站指数技术因子探测不能与固定维护日期混用")

    @staticmethod
    def _build_probe_unit(
        session: Session,
        *,
        latest_open_date: date,
        rule: ProbeRule,
    ) -> PlanUnitSnapshot:
        request = DatasetActionRequest(
            dataset_key=IDX_FACTOR_PRO_DATASET_KEY,
            action="maintain",
            time_input=DatasetTimeInput(mode="point", trade_date=latest_open_date),
            filters={},
            trigger_source="probe",
            requested_by_user_id=rule.updated_by_user_id or rule.created_by_user_id,
            schedule_id=rule.schedule_id,
        )
        plan = DatasetActionResolver(session).build_plan(request)
        if len(plan.units) != 1:
            raise ValueError("idx_factor_pro 远程探测未能生成单日 unit")
        return plan.units[0]

    @staticmethod
    def _row_matches_trade_date(row: object, expected: date) -> bool:
        if not isinstance(row, dict) or not str(row.get("ts_code") or "").strip():
            return False
        trade_date = row.get("trade_date")
        if isinstance(trade_date, datetime):
            return trade_date.date() == expected
        if isinstance(trade_date, date):
            return trade_date == expected
        text = str(trade_date or "").strip().replace("/", "-")
        if len(text) == 8 and text.isdigit():
            try:
                return date(int(text[:4]), int(text[4:6]), int(text[6:8])) == expected
            except ValueError:
                return False
        if len(text) >= 10:
            try:
                return date.fromisoformat(text[:10]) == expected
            except ValueError:
                return False
        return False

    @staticmethod
    def _non_trading_day_result(
        *,
        message: str,
        business_date: date,
        is_open: bool | None,
    ) -> IdxFactorProRemoteReadinessProbeResult:
        return IdxFactorProRemoteReadinessProbeResult(
            matched=False,
            message=message,
            payload={
                "dataset_key": IDX_FACTOR_PRO_DATASET_KEY,
                "condition_type": IDX_FACTOR_PRO_REMOTE_READY_CONDITION,
                "business_date": business_date.isoformat(),
                "is_open": is_open,
                "latest_open_date": None,
                "sample_request_count": 0,
                "message": message,
            },
        )

    @staticmethod
    def _result(
        *,
        matched: bool,
        message: str,
        business_date: date,
        latest_open_date: date,
        sample_request_count: int,
        row: object,
    ) -> IdxFactorProRemoteReadinessProbeResult:
        source_row = row if isinstance(row, dict) else {}
        return IdxFactorProRemoteReadinessProbeResult(
            matched=matched,
            message=message,
            payload={
                "dataset_key": IDX_FACTOR_PRO_DATASET_KEY,
                "condition_type": IDX_FACTOR_PRO_REMOTE_READY_CONDITION,
                "business_date": business_date.isoformat(),
                "latest_open_date": latest_open_date.isoformat(),
                "sample_request_count": sample_request_count,
                "matched_ts_code": str(source_row.get("ts_code") or "").strip() or None,
                "matched_trade_date": str(source_row.get("trade_date") or "").strip() or None,
                "message": message,
            },
        )


_TIME_INPUT_KEYS = {"trade_date", "ann_date", "month", "start_date", "end_date", "start_month", "end_month"}


def _has_fixed_or_non_point_time_input(request: dict[str, Any]) -> bool:
    if any(request.get(key) not in (None, "") for key in _TIME_INPUT_KEYS):
        return True
    time_input = request.get("time_input")
    if not isinstance(time_input, dict):
        return False
    if str(time_input.get("mode") or "point") != "point":
        return True
    return any(time_input.get(key) not in (None, "") for key in _TIME_INPUT_KEYS)
