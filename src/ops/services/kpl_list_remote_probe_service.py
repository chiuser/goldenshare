from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
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
from src.ops.services.dataset_release_target_service import DatasetReleaseTargetService


KPL_LIST_REMOTE_READY_CONDITION = "remote_kpl_list_ready"
KPL_LIST_REMOTE_READY_LABEL = "源站已有开盘啦榜单"
KPL_LIST_ACTION_KEY = "kpl_list.maintain"
KPL_LIST_DATASET_KEY = "kpl_list"
KPL_LIST_PROBE_TAG = "竞价"
KPL_LIST_REMOTE_PROBE_FIELDS = ("ts_code", "trade_date", "tag")


@dataclass(frozen=True, slots=True)
class KplListRemoteReadinessProbeResult:
    matched: bool
    message: str
    payload: dict[str, Any]


class KplListRemoteReadinessProbeService:
    """Probe the next-day kpl_list release without writing business data."""

    def __init__(self) -> None:
        self.release_target_service = DatasetReleaseTargetService()

    def evaluate(self, session: Session, rule: ProbeRule, *, current: datetime) -> KplListRemoteReadinessProbeResult:
        self._validate_rule(rule)
        definition = get_dataset_definition(KPL_LIST_DATASET_KEY)
        business_date = current.astimezone(ZoneInfo("Asia/Shanghai")).date()
        exchange = str((rule.probe_condition_json or {}).get("exchange") or get_settings().default_exchange)
        open_trade_dates = TradeCalendarDAO(session).get_open_dates(
            exchange,
            business_date - timedelta(days=31),
            business_date,
        )
        release_target = self.release_target_service.resolve(
            definition=definition,
            now=current,
            open_trade_dates=open_trade_dates,
        )
        if not release_target.is_resolved or release_target.target_trade_date is None:
            raise ValueError(release_target.reason or "未找到已到源端发布时间的开市日")

        action = dict(rule.on_success_action_json or {})
        request = dict(action.get("request") or {})
        filters = dict(request.get("filters") or {})
        filters.pop("source_key", None)
        unit = self._build_sample_unit(
            session,
            target_trade_date=release_target.target_trade_date,
            base_filters=filters,
            rule=rule,
        )
        rows = create_source_connector(definition.source.source_key_default).call(
            definition.source.api_name,
            params={**dict(unit.request_params), "limit": 1, "offset": 0},
            fields=KPL_LIST_REMOTE_PROBE_FIELDS,
        )
        matching_row = next(
            (
                row
                for row in rows
                if self._row_matches_target(row, target_trade_date=release_target.target_trade_date)
            ),
            None,
        )
        if matching_row is None:
            return self._result(
                matched=False,
                message="源站尚未返回目标交易日开盘啦榜单",
                business_date=business_date,
                target_trade_date=release_target.target_trade_date,
                sample_request_count=1,
                sample_hit=None,
            )

        return self._result(
            matched=True,
            message="源站已返回目标交易日开盘啦榜单",
            business_date=business_date,
            target_trade_date=release_target.target_trade_date,
            sample_request_count=1,
            sample_hit={
                "ts_code": str(matching_row.get("ts_code") or ""),
                "trade_date": str(matching_row.get("trade_date") or ""),
                "tag": str(matching_row.get("tag") or ""),
            },
        )

    @staticmethod
    def _build_sample_unit(
        session: Session,
        *,
        target_trade_date: date,
        base_filters: dict[str, Any],
        rule: ProbeRule,
    ) -> PlanUnitSnapshot:
        request = DatasetActionRequest(
            dataset_key=KPL_LIST_DATASET_KEY,
            action="maintain",
            time_input=DatasetTimeInput(mode="point", trade_date=target_trade_date),
            filters={**base_filters, "tag": KPL_LIST_PROBE_TAG},
            trigger_source="probe",
            requested_by_user_id=rule.updated_by_user_id or rule.created_by_user_id,
            schedule_id=rule.schedule_id,
        )
        plan = DatasetActionResolver(session).build_plan(request)
        if not plan.units:
            raise ValueError("kpl_list 远程探测未能生成 sample unit")
        return plan.units[0]

    @staticmethod
    def _validate_rule(rule: ProbeRule) -> None:
        if rule.dataset_key != KPL_LIST_DATASET_KEY:
            raise ValueError("源站开盘啦榜单探测只支持开盘啦榜单维护")
        action = dict(rule.on_success_action_json or {})
        if str(action.get("action_type") or "dataset_action") != "dataset_action":
            raise ValueError("源站开盘啦榜单探测只支持开盘啦榜单维护")
        if str(action.get("action_key") or "").strip() != KPL_LIST_ACTION_KEY:
            raise ValueError("源站开盘啦榜单探测只支持开盘啦榜单维护")
        request = dict(action.get("request") or {})
        if _has_fixed_or_non_point_time_input(request):
            raise ValueError("源站开盘啦榜单探测不能与固定维护日期混用")

    @staticmethod
    def _row_matches_target(row: dict[str, Any], *, target_trade_date: date) -> bool:
        if str(row.get("tag") or "").strip() != KPL_LIST_PROBE_TAG:
            return False
        value = row.get("trade_date")
        if isinstance(value, datetime):
            return value.date() == target_trade_date
        if isinstance(value, date):
            return value == target_trade_date
        text = str(value or "").strip().replace("/", "-")
        if len(text) == 8 and text.isdigit():
            try:
                return date(int(text[:4]), int(text[4:6]), int(text[6:8])) == target_trade_date
            except ValueError:
                return False
        if len(text) >= 10:
            try:
                return date.fromisoformat(text[:10]) == target_trade_date
            except ValueError:
                return False
        return False

    @staticmethod
    def _result(
        *,
        matched: bool,
        message: str,
        business_date: date,
        target_trade_date: date | None,
        sample_request_count: int,
        sample_hit: dict[str, str] | None,
    ) -> KplListRemoteReadinessProbeResult:
        return KplListRemoteReadinessProbeResult(
            matched=matched,
            message=message,
            payload={
                "dataset_key": KPL_LIST_DATASET_KEY,
                "condition_type": KPL_LIST_REMOTE_READY_CONDITION,
                "business_date": business_date.isoformat(),
                "target_trade_date": target_trade_date.isoformat() if target_trade_date else None,
                "probe_tag": KPL_LIST_PROBE_TAG,
                "sample_request_count": sample_request_count,
                "sample_hit": sample_hit,
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
