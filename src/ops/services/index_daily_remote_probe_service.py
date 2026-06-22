from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from src.foundation.config.settings import get_settings
from src.foundation.connectors.factory import create_source_connector
from src.foundation.dao.factory import DAOFactory
from src.foundation.dao.trade_calendar_dao import TradeCalendarDAO
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.execution_plan import DatasetActionRequest, DatasetTimeInput, PlanUnitSnapshot
from src.foundation.ingestion.plan_helpers import split_multi_values
from src.foundation.ingestion.resolver import DatasetActionResolver
from src.ops.models.ops.probe_rule import ProbeRule


INDEX_DAILY_REMOTE_READY_CONDITION = "remote_index_daily_ready"
INDEX_DAILY_REMOTE_READY_LABEL = "源站已有指数日线"
INDEX_DAILY_ACTION_KEY = "index_daily.maintain"
INDEX_DAILY_DATASET_KEY = "index_daily"
INDEX_DAILY_RAW_REQUEST_POOL = "index_daily_raw"
INDEX_DAILY_REMOTE_PROBE_FIELDS = ("ts_code", "trade_date")
DEFAULT_INDEX_DAILY_SAMPLE_CODES = ("000001.SH", "399001.SZ", "399300.SZ", "000016.SH", "000905.SH")
MAX_EXPLICIT_INDEX_DAILY_SAMPLE_CODES = 5


@dataclass(frozen=True, slots=True)
class IndexDailyRemoteReadinessProbeResult:
    matched: bool
    message: str
    payload: dict[str, Any]


class IndexDailyRemoteReadinessProbeService:
    """Probe Tushare index_daily readiness without touching business tables."""

    def evaluate(self, session: Session, rule: ProbeRule, *, current: datetime) -> IndexDailyRemoteReadinessProbeResult:
        self._validate_rule(rule)
        business_date = current.astimezone(ZoneInfo("Asia/Shanghai")).date()
        exchange = str((rule.probe_condition_json or {}).get("exchange") or get_settings().default_exchange)
        business_day = TradeCalendarDAO(session).fetch_by_pk(exchange, business_date)
        if business_day is None:
            message = f"交易日历缺少 {business_date.isoformat()} 记录，已跳过源站指数日线探测"
            return self._non_trading_day_result(
                message=message,
                business_date=business_date,
                is_open=None,
                pretrade_date=None,
            )
        if business_day.is_open is not True:
            message = f"{business_date.isoformat()} 非交易日，已跳过源站指数日线探测"
            return self._non_trading_day_result(
                message=message,
                business_date=business_date,
                is_open=False,
                pretrade_date=business_day.pretrade_date,
            )
        latest_open_date = business_date

        action = dict(rule.on_success_action_json or {})
        request = dict(action.get("request") or {})
        filters = dict(request.get("filters") or {})
        filters.pop("source_key", None)
        sample_codes = self._resolve_sample_codes(session, filters)
        connector = create_source_connector(get_dataset_definition(INDEX_DAILY_DATASET_KEY).source.source_key_default)

        matched_codes: list[str] = []
        missing_codes: list[str] = []
        sample_hits: list[dict[str, Any]] = []
        sample_request_count = 0

        for ts_code in sample_codes:
            unit = self._build_sample_unit(
                session,
                latest_open_date=latest_open_date,
                ts_code=ts_code,
                base_filters=filters,
                rule=rule,
            )
            params = {**dict(unit.request_params), "limit": 1, "offset": 0}
            sample_request_count += 1
            rows = connector.call(
                get_dataset_definition(INDEX_DAILY_DATASET_KEY).source.api_name,
                params=params,
                fields=INDEX_DAILY_REMOTE_PROBE_FIELDS,
            )
            matching_row = next((row for row in rows if self._row_matches_trade_date(row, latest_open_date)), None)
            if matching_row is None:
                missing_codes.append(ts_code)
                continue
            matched_codes.append(ts_code)
            sample_hits.append(
                {
                    "ts_code": str(matching_row.get("ts_code") or ts_code),
                    "trade_date": str(matching_row.get("trade_date") or ""),
                }
            )

        if missing_codes:
            return self._result(
                matched=False,
                message=f"源站尚未返回全部指数日线：缺少 {', '.join(missing_codes)}",
                business_date=business_date,
                latest_open_date=latest_open_date,
                sample_codes=sample_codes,
                matched_codes=matched_codes,
                missing_codes=missing_codes,
                sample_request_count=sample_request_count,
                sample_hits=sample_hits,
            )

        return self._result(
            matched=True,
            message="源站已返回目标交易日指数日线",
            business_date=business_date,
            latest_open_date=latest_open_date,
            sample_codes=sample_codes,
            matched_codes=matched_codes,
            missing_codes=[],
            sample_request_count=sample_request_count,
            sample_hits=sample_hits,
        )

    @staticmethod
    def _non_trading_day_result(
        *,
        message: str,
        business_date: date,
        is_open: bool | None,
        pretrade_date: date | None,
    ) -> IndexDailyRemoteReadinessProbeResult:
        return IndexDailyRemoteReadinessProbeResult(
            matched=False,
            message=message,
            payload={
                "dataset_key": INDEX_DAILY_DATASET_KEY,
                "condition_type": INDEX_DAILY_REMOTE_READY_CONDITION,
                "business_date": business_date.isoformat(),
                "is_open": is_open,
                "pretrade_date": pretrade_date.isoformat() if pretrade_date else None,
                "latest_open_date": None,
                "sample_codes": [],
                "matched_codes": [],
                "missing_codes": [],
                "sample_request_count": 0,
                "sample_hits": [],
                "message": message,
            },
        )

    def _build_sample_unit(
        self,
        session: Session,
        *,
        latest_open_date: date,
        ts_code: str,
        base_filters: dict[str, Any],
        rule: ProbeRule,
    ) -> PlanUnitSnapshot:
        sample_filters = {**base_filters, "ts_code": ts_code}
        request = DatasetActionRequest(
            dataset_key=INDEX_DAILY_DATASET_KEY,
            action="maintain",
            time_input=DatasetTimeInput(mode="point", trade_date=latest_open_date),
            filters=sample_filters,
            trigger_source="probe",
            requested_by_user_id=rule.updated_by_user_id or rule.created_by_user_id,
            schedule_id=rule.schedule_id,
        )
        plan = DatasetActionResolver(session).build_plan(request)
        if not plan.units:
            raise ValueError("index_daily 远程探测未能生成 sample unit")
        return plan.units[0]

    @staticmethod
    def _validate_rule(rule: ProbeRule) -> None:
        if rule.dataset_key != INDEX_DAILY_DATASET_KEY:
            raise ValueError("源站指数日线探测只支持指数日线行情维护")
        action = dict(rule.on_success_action_json or {})
        if str(action.get("action_type") or "dataset_action") != "dataset_action":
            raise ValueError("源站指数日线探测只支持指数日线行情维护")
        if str(action.get("action_key") or "").strip() != INDEX_DAILY_ACTION_KEY:
            raise ValueError("源站指数日线探测只支持指数日线行情维护")
        request = dict(action.get("request") or {})
        if _has_fixed_or_non_point_time_input(request):
            raise ValueError("源站指数日线探测不能与固定维护日期混用")

    @staticmethod
    def _resolve_sample_codes(session: Session, filters: dict[str, Any]) -> list[str]:
        explicit_codes = [str(code).strip().upper() for code in split_multi_values(filters.get("ts_code")) if str(code).strip()]
        if explicit_codes:
            return list(dict.fromkeys(explicit_codes))[:MAX_EXPLICIT_INDEX_DAILY_SAMPLE_CODES]

        raw_pool_codes = {
            str(code).strip().upper()
            for code in DAOFactory(session).index_series_active.list_active_codes(INDEX_DAILY_RAW_REQUEST_POOL)
            if str(code).strip()
        }
        missing = [code for code in DEFAULT_INDEX_DAILY_SAMPLE_CODES if code not in raw_pool_codes]
        if missing:
            raise ValueError(f"指数日线默认探测样本未配置完整：{', '.join(missing)}")
        return list(DEFAULT_INDEX_DAILY_SAMPLE_CODES)

    @staticmethod
    def _row_matches_trade_date(row: dict[str, Any], expected: date) -> bool:
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
    def _result(
        *,
        matched: bool,
        message: str,
        business_date: date,
        latest_open_date: date,
        sample_codes: list[str],
        matched_codes: list[str],
        missing_codes: list[str],
        sample_request_count: int,
        sample_hits: list[dict[str, Any]],
    ) -> IndexDailyRemoteReadinessProbeResult:
        return IndexDailyRemoteReadinessProbeResult(
            matched=matched,
            message=message,
            payload={
                "dataset_key": INDEX_DAILY_DATASET_KEY,
                "condition_type": INDEX_DAILY_REMOTE_READY_CONDITION,
                "business_date": business_date.isoformat(),
                "latest_open_date": latest_open_date.isoformat(),
                "sample_codes": sample_codes,
                "matched_codes": matched_codes,
                "missing_codes": missing_codes,
                "sample_request_count": sample_request_count,
                "sample_hits": sample_hits,
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
