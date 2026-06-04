from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from src.foundation.config.settings import get_settings
from src.foundation.connectors.factory import create_source_connector
from src.foundation.dao.security_dao import SecurityDAO
from src.foundation.dao.trade_calendar_dao import TradeCalendarDAO
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.execution_plan import DatasetActionRequest, DatasetTimeInput, PlanUnitSnapshot
from src.foundation.ingestion.plan_helpers import split_multi_values
from src.foundation.ingestion.resolver import DatasetActionResolver
from src.ops.models.ops.probe_rule import ProbeRule


STK_MINS_REMOTE_READY_CONDITION = "remote_stk_mins_ready"
STK_MINS_REMOTE_READY_LABEL = "源站已有分钟行情"
STK_MINS_ACTION_KEY = "stk_mins.maintain"
STK_MINS_DATASET_KEY = "stk_mins"
STK_MINS_ALLOWED_FREQS = ("1min", "5min", "15min", "30min", "60min")
STK_MINS_REMOTE_PROBE_FIELDS = ("ts_code", "trade_time")
DEFAULT_STK_MINS_SAMPLE_CODES = ("600000.SH", "000001.SZ", "300750.SZ", "601318.SH", "000858.SZ")
MAX_EXPLICIT_STK_MINS_SAMPLE_CODES = 3


@dataclass(frozen=True, slots=True)
class StkMinsRemoteReadinessProbeResult:
    matched: bool
    message: str
    payload: dict[str, Any]


class StkMinsRemoteReadinessProbeService:
    """Probe Tushare stk_mins readiness without touching business tables."""

    def evaluate(self, session: Session, rule: ProbeRule, *, current: datetime) -> StkMinsRemoteReadinessProbeResult:
        self._validate_rule(rule)
        business_date = current.astimezone(ZoneInfo("Asia/Shanghai")).date()
        exchange = str((rule.probe_condition_json or {}).get("exchange") or get_settings().default_exchange)
        latest_open_date = TradeCalendarDAO(session).get_latest_open_date(exchange, business_date)
        if latest_open_date is None:
            return StkMinsRemoteReadinessProbeResult(
                matched=False,
                message="交易日历没有可用的最近开市日",
                payload={
                    "dataset_key": STK_MINS_DATASET_KEY,
                    "condition_type": STK_MINS_REMOTE_READY_CONDITION,
                    "latest_open_date": None,
                    "checked_freqs": [],
                    "matched_freqs": [],
                    "sample_request_count": 0,
                    "sample_codes": [],
                },
            )

        action = dict(rule.on_success_action_json or {})
        request = dict(action.get("request") or {})
        filters = dict(request.get("filters") or {})
        freqs = self._resolve_freqs(filters)
        sample_codes = self._resolve_sample_codes(session, filters)
        if not sample_codes:
            raise ValueError("stk_mins 远程探测没有可用样本股票")

        connector = create_source_connector(get_dataset_definition(STK_MINS_DATASET_KEY).source.source_key_default)
        matched_freqs: list[str] = []
        sample_hits: list[dict[str, Any]] = []
        sample_request_count = 0

        for freq in freqs:
            freq_matched = False
            for ts_code in sample_codes:
                unit = self._build_sample_unit(
                    session,
                    latest_open_date=latest_open_date,
                    ts_code=ts_code,
                    freq=freq,
                    base_filters=filters,
                    rule=rule,
                )
                params = {**dict(unit.request_params), "limit": 1, "offset": 0}
                sample_request_count += 1
                rows = connector.call(
                    get_dataset_definition(STK_MINS_DATASET_KEY).source.api_name,
                    params=params,
                    fields=STK_MINS_REMOTE_PROBE_FIELDS,
                )
                matching_row = next((row for row in rows if self._row_matches_trade_date(row, latest_open_date)), None)
                if matching_row is not None:
                    freq_matched = True
                    matched_freqs.append(freq)
                    sample_hits.append(
                        {
                            "freq": freq,
                            "ts_code": ts_code,
                            "trade_time": str(matching_row.get("trade_time") or ""),
                        }
                    )
                    break
            if not freq_matched:
                return self._result(
                    matched=False,
                    message=f"源站尚未返回 {freq} 的最新交易日分钟行情",
                    latest_open_date=latest_open_date,
                    checked_freqs=freqs,
                    matched_freqs=matched_freqs,
                    sample_request_count=sample_request_count,
                    sample_codes=sample_codes,
                    sample_hits=sample_hits,
                )

        return self._result(
            matched=True,
            message="源站已返回目标交易日分钟行情",
            latest_open_date=latest_open_date,
            checked_freqs=freqs,
            matched_freqs=matched_freqs,
            sample_request_count=sample_request_count,
            sample_codes=sample_codes,
            sample_hits=sample_hits,
        )

    def _build_sample_unit(
        self,
        session: Session,
        *,
        latest_open_date: date,
        ts_code: str,
        freq: str,
        base_filters: dict[str, Any],
        rule: ProbeRule,
    ) -> PlanUnitSnapshot:
        sample_filters = {**base_filters, "ts_code": ts_code, "freq": freq}
        request = DatasetActionRequest(
            dataset_key=STK_MINS_DATASET_KEY,
            action="maintain",
            time_input=DatasetTimeInput(mode="point", trade_date=latest_open_date),
            filters=sample_filters,
            trigger_source="probe",
            requested_by_user_id=rule.updated_by_user_id or rule.created_by_user_id,
            schedule_id=rule.schedule_id,
        )
        plan = DatasetActionResolver(session).build_plan(request)
        if not plan.units:
            raise ValueError("stk_mins 远程探测未能生成 sample unit")
        return plan.units[0]

    @staticmethod
    def _validate_rule(rule: ProbeRule) -> None:
        if rule.dataset_key != STK_MINS_DATASET_KEY:
            raise ValueError("源站分钟行情探测只支持股票历史分钟行情维护")
        action = dict(rule.on_success_action_json or {})
        if str(action.get("action_type") or "dataset_action") != "dataset_action":
            raise ValueError("源站分钟行情探测只支持股票历史分钟行情维护")
        if str(action.get("action_key") or "").strip() != STK_MINS_ACTION_KEY:
            raise ValueError("源站分钟行情探测只支持股票历史分钟行情维护")
        request = dict(action.get("request") or {})
        time_input = request.get("time_input")
        if isinstance(time_input, dict) and time_input.get("trade_date") not in (None, ""):
            raise ValueError("源站分钟行情探测不能与固定维护日期混用")

    @staticmethod
    def _resolve_freqs(filters: dict[str, Any]) -> list[str]:
        freqs = split_multi_values(filters.get("freq"))
        normalized = [str(item).strip() for item in freqs if str(item).strip()]
        if not normalized:
            raise ValueError("stk_mins 远程探测必须配置分钟周期")
        invalid = [item for item in normalized if item not in STK_MINS_ALLOWED_FREQS]
        if invalid:
            raise ValueError(f"stk_mins 远程探测不支持的分钟周期：{', '.join(invalid)}")
        return list(dict.fromkeys(normalized))

    @staticmethod
    def _resolve_sample_codes(session: Session, filters: dict[str, Any]) -> list[str]:
        explicit_codes = [code.upper() for code in split_multi_values(filters.get("ts_code"))]
        if explicit_codes:
            return list(dict.fromkeys(explicit_codes))[:MAX_EXPLICIT_STK_MINS_SAMPLE_CODES]

        dao = SecurityDAO(session)
        samples: list[str] = []
        for code in DEFAULT_STK_MINS_SAMPLE_CODES:
            security = dao.get_by_ts_code(code)
            if security is None:
                continue
            if str(security.source or "").lower() != "tushare":
                continue
            if str(security.list_status or "").upper() != "L":
                continue
            samples.append(code)
        return samples

    @staticmethod
    def _row_matches_trade_date(row: dict[str, Any], expected: date) -> bool:
        trade_time = row.get("trade_time")
        if isinstance(trade_time, datetime):
            return trade_time.date() == expected
        if isinstance(trade_time, date):
            return trade_time == expected
        text = str(trade_time or "").strip().replace("/", "-")
        if len(text) < 10:
            return False
        try:
            return date.fromisoformat(text[:10]) == expected
        except ValueError:
            return False

    @staticmethod
    def _result(
        *,
        matched: bool,
        message: str,
        latest_open_date: date,
        checked_freqs: list[str],
        matched_freqs: list[str],
        sample_request_count: int,
        sample_codes: list[str],
        sample_hits: list[dict[str, Any]],
    ) -> StkMinsRemoteReadinessProbeResult:
        return StkMinsRemoteReadinessProbeResult(
            matched=matched,
            message=message,
            payload={
                "dataset_key": STK_MINS_DATASET_KEY,
                "condition_type": STK_MINS_REMOTE_READY_CONDITION,
                "latest_open_date": latest_open_date.isoformat(),
                "checked_freqs": checked_freqs,
                "matched_freqs": matched_freqs,
                "sample_request_count": sample_request_count,
                "sample_codes": sample_codes,
                "sample_hits": sample_hits,
                "message": message,
            },
        )
