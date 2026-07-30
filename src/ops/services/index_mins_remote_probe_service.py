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


INDEX_MINS_REMOTE_READY_CONDITION = "remote_index_mins_ready"
INDEX_MINS_REMOTE_READY_LABEL = "源站已有指数分钟行情"
INDEX_MINS_ACTION_KEY = "index_mins.maintain"
INDEX_MINS_DATASET_KEY = "index_mins"
INDEX_MINS_ACTIVE_POOL_RESOURCE = "index_mins"
INDEX_MINS_ALLOWED_FREQS = ("1min", "5min", "15min", "30min", "60min")
INDEX_MINS_MIN_PROBE_INTERVAL_SECONDS = 300
INDEX_MINS_REMOTE_PROBE_FIELDS = ("ts_code", "trade_time")
DEFAULT_INDEX_MINS_SAMPLE_CODES = (
    "000001.SH",
    "000003.SH",
    "000004.SH",
    "000015.SH",
    "000019.SH",
    "000028.SH",
    "399100.SZ",
    "399001.SZ",
    "399231.SZ",
    "399269.SZ",
    "399295.SZ",
    "399013.SZ",
    "000855.SH",
    "399429.SZ",
    "399699.SZ",
)


@dataclass(frozen=True, slots=True)
class IndexMinsRemoteReadinessProbeResult:
    matched: bool
    message: str
    payload: dict[str, Any]


class IndexMinsRemoteReadinessProbeService:
    """Probe Tushare index-minute readiness without touching business tables."""

    def evaluate(self, session: Session, rule: ProbeRule, *, current: datetime) -> IndexMinsRemoteReadinessProbeResult:
        self._validate_rule(rule)
        business_date = current.astimezone(ZoneInfo("Asia/Shanghai")).date()
        exchange = str((rule.probe_condition_json or {}).get("exchange") or get_settings().default_exchange)
        business_day = TradeCalendarDAO(session).fetch_by_pk(exchange, business_date)
        if business_day is None:
            message = f"交易日历缺少 {business_date.isoformat()} 记录，已跳过源站指数分钟行情探测"
            return self._non_trading_day_result(
                message=message,
                business_date=business_date,
                is_open=None,
                pretrade_date=None,
            )
        if business_day.is_open is not True:
            message = f"{business_date.isoformat()} 非交易日，已跳过源站指数分钟行情探测"
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
        sample_codes = self._resolve_sample_codes(session)
        connector = create_source_connector(get_dataset_definition(INDEX_MINS_DATASET_KEY).source.source_key_default)
        sample_hits: list[dict[str, Any]] = []
        sample_request_count = 0

        # Probe in a stable order and stop at the first unavailable sample.
        for ts_code in sample_codes:
            for freq in INDEX_MINS_ALLOWED_FREQS:
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
                    get_dataset_definition(INDEX_MINS_DATASET_KEY).source.api_name,
                    params=params,
                    fields=INDEX_MINS_REMOTE_PROBE_FIELDS,
                )
                matching_row = next(
                    (
                        row
                        for row in rows
                        if self._row_matches_sample(row, expected_ts_code=ts_code, expected_trade_date=latest_open_date)
                    ),
                    None,
                )
                if matching_row is None:
                    return self._result(
                        matched=False,
                        message=f"源站尚未返回 {ts_code} {freq} 的目标交易日指数分钟行情",
                        latest_open_date=latest_open_date,
                        sample_codes=sample_codes,
                        sample_request_count=sample_request_count,
                        sample_hits=sample_hits,
                        first_missing_sample={"ts_code": ts_code, "freq": freq},
                    )
                sample_hits.append(
                    {
                        "ts_code": ts_code,
                        "freq": freq,
                        "trade_time": str(matching_row.get("trade_time") or ""),
                    }
                )

        return self._result(
            matched=True,
            message="源站已返回目标交易日指数分钟行情",
            latest_open_date=latest_open_date,
            sample_codes=sample_codes,
            sample_request_count=sample_request_count,
            sample_hits=sample_hits,
            first_missing_sample=None,
        )

    @staticmethod
    def _non_trading_day_result(
        *,
        message: str,
        business_date: date,
        is_open: bool | None,
        pretrade_date: date | None,
    ) -> IndexMinsRemoteReadinessProbeResult:
        return IndexMinsRemoteReadinessProbeResult(
            matched=False,
            message=message,
            payload={
                "dataset_key": INDEX_MINS_DATASET_KEY,
                "condition_type": INDEX_MINS_REMOTE_READY_CONDITION,
                "business_date": business_date.isoformat(),
                "is_open": is_open,
                "pretrade_date": pretrade_date.isoformat() if pretrade_date else None,
                "latest_open_date": None,
                "checked_freqs": [],
                "sample_codes": [],
                "sample_request_count": 0,
                "sample_hits": [],
                "first_missing_sample": None,
                "message": message,
            },
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
            dataset_key=INDEX_MINS_DATASET_KEY,
            action="maintain",
            time_input=DatasetTimeInput(mode="point", trade_date=latest_open_date),
            filters=sample_filters,
            trigger_source="probe",
            requested_by_user_id=rule.updated_by_user_id or rule.created_by_user_id,
            schedule_id=rule.schedule_id,
        )
        plan = DatasetActionResolver(session).build_plan(request)
        if not plan.units:
            raise ValueError("index_mins 远程探测未能生成 sample unit")
        return plan.units[0]

    @staticmethod
    def _validate_rule(rule: ProbeRule) -> None:
        if rule.dataset_key != INDEX_MINS_DATASET_KEY:
            raise ValueError("源站指数分钟行情探测只支持指数历史分钟行情维护")
        action = dict(rule.on_success_action_json or {})
        if str(action.get("action_type") or "dataset_action") != "dataset_action":
            raise ValueError("源站指数分钟行情探测只支持指数历史分钟行情维护")
        if str(action.get("action_key") or "").strip() != INDEX_MINS_ACTION_KEY:
            raise ValueError("源站指数分钟行情探测只支持指数历史分钟行情维护")
        request = dict(action.get("request") or {})
        if _has_fixed_or_non_point_time_input(request):
            raise ValueError("源站指数分钟行情探测不能与固定维护日期混用")
        freqs = [str(item).strip() for item in split_multi_values(dict(request.get("filters") or {}).get("freq")) if str(item).strip()]
        if len(freqs) != len(INDEX_MINS_ALLOWED_FREQS) or set(freqs) != set(INDEX_MINS_ALLOWED_FREQS):
            raise ValueError("源站指数分钟行情探测必须完整配置 1min/5min/15min/30min/60min")

    @staticmethod
    def _resolve_sample_codes(session: Session) -> list[str]:
        active_codes = {
            str(code).strip().upper()
            for code in DAOFactory(session).index_series_active.list_active_codes(INDEX_MINS_ACTIVE_POOL_RESOURCE)
            if str(code).strip()
        }
        missing = [code for code in DEFAULT_INDEX_MINS_SAMPLE_CODES if code not in active_codes]
        if missing:
            raise ValueError(f"指数分钟线代表样本未配置完整：{', '.join(missing)}")
        return list(DEFAULT_INDEX_MINS_SAMPLE_CODES)

    @staticmethod
    def _row_matches_sample(row: dict[str, Any], *, expected_ts_code: str, expected_trade_date: date) -> bool:
        actual_ts_code = str(row.get("ts_code") or "").strip().upper()
        if actual_ts_code != expected_ts_code:
            return False
        trade_time = row.get("trade_time")
        if isinstance(trade_time, datetime):
            return trade_time.date() == expected_trade_date
        if isinstance(trade_time, date):
            return trade_time == expected_trade_date
        text = str(trade_time or "").strip().replace("/", "-")
        if len(text) < 10:
            return False
        try:
            return date.fromisoformat(text[:10]) == expected_trade_date
        except ValueError:
            return False

    @staticmethod
    def _result(
        *,
        matched: bool,
        message: str,
        latest_open_date: date,
        sample_codes: list[str],
        sample_request_count: int,
        sample_hits: list[dict[str, Any]],
        first_missing_sample: dict[str, str] | None,
    ) -> IndexMinsRemoteReadinessProbeResult:
        return IndexMinsRemoteReadinessProbeResult(
            matched=matched,
            message=message,
            payload={
                "dataset_key": INDEX_MINS_DATASET_KEY,
                "condition_type": INDEX_MINS_REMOTE_READY_CONDITION,
                "latest_open_date": latest_open_date.isoformat(),
                "checked_freqs": list(INDEX_MINS_ALLOWED_FREQS),
                "sample_codes": sample_codes,
                "sample_request_count": sample_request_count,
                "sample_hits": sample_hits,
                "first_missing_sample": first_missing_sample,
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
