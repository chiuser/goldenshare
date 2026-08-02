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
from src.ops.models.ops.probe_rule import ProbeRule
from src.ops.services.dataset_release_target_service import DatasetReleaseTargetService


MARGIN_DETAIL_REMOTE_READY_CONDITION = "remote_margin_detail_ready"
MARGIN_DETAIL_REMOTE_READY_LABEL = "源站已完整发布融资融券交易明细"
MARGIN_DETAIL_ACTION_KEY = "margin_detail.maintain"
MARGIN_DETAIL_DATASET_KEY = "margin_detail"
MARGIN_DETAIL_REQUIRED_SAMPLES = (
    ("SSE", "600000.SH"),
    ("SZSE", "000001.SZ"),
    ("BSE", "920992.BJ"),
)


@dataclass(frozen=True, slots=True)
class MarginDetailRemoteReadinessProbeResult:
    matched: bool
    message: str
    payload: dict[str, Any]


class MarginDetailRemoteReadinessProbeService:
    """Probe the three-market margin-detail release without touching serving data."""

    def __init__(self) -> None:
        self.release_target_service = DatasetReleaseTargetService()

    def evaluate(
        self,
        session: Session,
        rule: ProbeRule,
        *,
        current: datetime,
    ) -> MarginDetailRemoteReadinessProbeResult:
        self._validate_rule(rule)
        definition = get_dataset_definition(MARGIN_DETAIL_DATASET_KEY)
        business_date = current.astimezone(ZoneInfo("Asia/Shanghai")).date()
        open_trade_dates = TradeCalendarDAO(session).get_open_dates(
            get_settings().default_exchange,
            business_date - timedelta(days=31),
            business_date,
        )
        release_target = self.release_target_service.resolve(
            definition=definition,
            now=current,
            open_trade_dates=open_trade_dates,
        )
        if not release_target.is_resolved or release_target.target_trade_date is None:
            return self._result(
                matched=False,
                message=release_target.reason or "当前没有可探测的融资融券交易明细目标交易日",
                business_date=business_date,
                target_trade_date=None,
                matched_markets=[],
                missing_markets=[market for market, _code in MARGIN_DETAIL_REQUIRED_SAMPLES],
                sample_request_count=0,
                sample_hits=[],
            )

        connector = create_source_connector(definition.source.source_key_default)
        matched_markets: list[str] = []
        missing_markets: list[str] = []
        sample_hits: list[dict[str, str]] = []
        sample_request_count = 0
        for market, ts_code in MARGIN_DETAIL_REQUIRED_SAMPLES:
            params = {
                "trade_date": release_target.target_trade_date.strftime("%Y%m%d"),
                "ts_code": ts_code,
                "limit": 1,
                "offset": 0,
            }
            sample_request_count += 1
            rows = connector.call(
                definition.source.api_name,
                params=params,
                fields=definition.source.source_fields,
            )
            matching_row = next(
                (
                    row
                    for row in rows
                    if self._row_matches_target(
                        row,
                        target_trade_date=release_target.target_trade_date,
                        ts_code=ts_code,
                        required_fields=definition.source.source_fields,
                    )
                ),
                None,
            )
            if matching_row is None:
                missing_markets.append(market)
                continue
            matched_markets.append(market)
            sample_hits.append(
                {
                    "market": market,
                    "ts_code": str(matching_row.get("ts_code") or ""),
                    "trade_date": str(matching_row.get("trade_date") or ""),
                }
            )

        if missing_markets:
            return self._result(
                matched=False,
                message=f"源站尚未完整发布融资融券交易明细：缺少 {', '.join(missing_markets)}",
                business_date=business_date,
                target_trade_date=release_target.target_trade_date,
                matched_markets=matched_markets,
                missing_markets=missing_markets,
                sample_request_count=sample_request_count,
                sample_hits=sample_hits,
            )
        return self._result(
            matched=True,
            message=MARGIN_DETAIL_REMOTE_READY_LABEL,
            business_date=business_date,
            target_trade_date=release_target.target_trade_date,
            matched_markets=matched_markets,
            missing_markets=[],
            sample_request_count=sample_request_count,
            sample_hits=sample_hits,
        )

    @staticmethod
    def _validate_rule(rule: ProbeRule) -> None:
        if rule.dataset_key != MARGIN_DETAIL_DATASET_KEY:
            raise ValueError("源站融资融券交易明细探测只支持融资融券交易明细维护")
        action = dict(rule.on_success_action_json or {})
        if str(action.get("action_type") or "dataset_action") != "dataset_action":
            raise ValueError("源站融资融券交易明细探测只支持融资融券交易明细维护")
        if str(action.get("action_key") or "").strip() != MARGIN_DETAIL_ACTION_KEY:
            raise ValueError("源站融资融券交易明细探测只支持融资融券交易明细维护")
        request = dict(action.get("request") or {})
        if dict(request.get("filters") or {}):
            raise ValueError("源站融资融券交易明细探测不支持维护参数")
        if _has_fixed_or_non_point_time_input(request):
            raise ValueError("源站融资融券交易明细探测不能与固定维护日期混用")

    @staticmethod
    def _row_matches_target(
        row: object,
        *,
        target_trade_date: date,
        ts_code: str,
        required_fields: tuple[str, ...],
    ) -> bool:
        if not isinstance(row, dict):
            return False
        if not set(required_fields).issubset(row):
            return False
        if str(row.get("ts_code") or "").strip().upper() != ts_code:
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
        matched_markets: list[str],
        missing_markets: list[str],
        sample_request_count: int,
        sample_hits: list[dict[str, str]],
    ) -> MarginDetailRemoteReadinessProbeResult:
        return MarginDetailRemoteReadinessProbeResult(
            matched=matched,
            message=message,
            payload={
                "dataset_key": MARGIN_DETAIL_DATASET_KEY,
                "condition_type": MARGIN_DETAIL_REMOTE_READY_CONDITION,
                "business_date": business_date.isoformat(),
                "target_trade_date": target_trade_date.isoformat() if target_trade_date else None,
                "required_samples": [
                    {"market": market, "ts_code": ts_code}
                    for market, ts_code in MARGIN_DETAIL_REQUIRED_SAMPLES
                ],
                "matched_markets": matched_markets,
                "missing_markets": missing_markets,
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
