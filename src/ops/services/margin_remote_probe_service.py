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


MARGIN_REMOTE_READY_CONDITION = "remote_margin_ready"
MARGIN_REMOTE_READY_LABEL = "源站已完整发布融资融券汇总"
MARGIN_ACTION_KEY = "margin.maintain"
MARGIN_DATASET_KEY = "margin"
MARGIN_REQUIRED_EXCHANGES = ("SSE", "SZSE", "BSE")
MARGIN_REMOTE_PROBE_FIELDS = ("trade_date", "exchange_id")


@dataclass(frozen=True, slots=True)
class MarginRemoteReadinessProbeResult:
    matched: bool
    message: str
    payload: dict[str, Any]


class MarginRemoteReadinessProbeService:
    """Probe all margin exchanges before creating a business-data TaskRun."""

    def __init__(self) -> None:
        self.release_target_service = DatasetReleaseTargetService()

    def evaluate(self, session: Session, rule: ProbeRule, *, current: datetime) -> MarginRemoteReadinessProbeResult:
        self._validate_rule(rule)
        definition = get_dataset_definition(MARGIN_DATASET_KEY)
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
                message=release_target.reason or "当前没有可探测的融资融券目标交易日",
                business_date=business_date,
                target_trade_date=None,
                matched_exchanges=[],
                missing_exchanges=list(MARGIN_REQUIRED_EXCHANGES),
                sample_request_count=0,
                sample_hits=[],
            )

        connector = create_source_connector(definition.source.source_key_default)
        matched_exchanges: list[str] = []
        missing_exchanges: list[str] = []
        sample_hits: list[dict[str, str]] = []
        sample_request_count = 0
        for exchange_id in MARGIN_REQUIRED_EXCHANGES:
            unit = self._build_sample_unit(
                session,
                target_trade_date=release_target.target_trade_date,
                exchange_id=exchange_id,
                rule=rule,
            )
            sample_request_count += 1
            rows = connector.call(
                definition.source.api_name,
                params={**dict(unit.request_params), "limit": 1, "offset": 0},
                fields=MARGIN_REMOTE_PROBE_FIELDS,
            )
            matching_row = next(
                (
                    row
                    for row in rows
                    if self._row_matches_target(
                        row,
                        target_trade_date=release_target.target_trade_date,
                        exchange_id=exchange_id,
                    )
                ),
                None,
            )
            if matching_row is None:
                missing_exchanges.append(exchange_id)
                continue
            matched_exchanges.append(exchange_id)
            sample_hits.append(
                {
                    "exchange_id": str(matching_row.get("exchange_id") or ""),
                    "trade_date": str(matching_row.get("trade_date") or ""),
                }
            )

        if missing_exchanges:
            return self._result(
                matched=False,
                message=f"源站尚未完整发布融资融券汇总：缺少 {', '.join(missing_exchanges)}",
                business_date=business_date,
                target_trade_date=release_target.target_trade_date,
                matched_exchanges=matched_exchanges,
                missing_exchanges=missing_exchanges,
                sample_request_count=sample_request_count,
                sample_hits=sample_hits,
            )
        return self._result(
            matched=True,
            message="源站已完整发布融资融券汇总",
            business_date=business_date,
            target_trade_date=release_target.target_trade_date,
            matched_exchanges=matched_exchanges,
            missing_exchanges=[],
            sample_request_count=sample_request_count,
            sample_hits=sample_hits,
        )

    @staticmethod
    def _validate_rule(rule: ProbeRule) -> None:
        if rule.dataset_key != MARGIN_DATASET_KEY:
            raise ValueError("源站融资融券汇总探测只支持融资融券汇总维护")
        action = dict(rule.on_success_action_json or {})
        if str(action.get("action_type") or "dataset_action") != "dataset_action":
            raise ValueError("源站融资融券汇总探测只支持融资融券汇总维护")
        if str(action.get("action_key") or "").strip() != MARGIN_ACTION_KEY:
            raise ValueError("源站融资融券汇总探测只支持融资融券汇总维护")
        request = dict(action.get("request") or {})
        if dict(request.get("filters") or {}):
            raise ValueError("源站融资融券汇总探测不支持维护参数")
        if _has_fixed_or_non_point_time_input(request):
            raise ValueError("源站融资融券汇总探测不能与固定维护日期混用")

    @staticmethod
    def _build_sample_unit(
        session: Session,
        *,
        target_trade_date: date,
        exchange_id: str,
        rule: ProbeRule,
    ) -> PlanUnitSnapshot:
        request = DatasetActionRequest(
            dataset_key=MARGIN_DATASET_KEY,
            action="maintain",
            time_input=DatasetTimeInput(mode="point", trade_date=target_trade_date),
            filters={"exchange_id": exchange_id},
            trigger_source="probe",
            requested_by_user_id=rule.updated_by_user_id or rule.created_by_user_id,
            schedule_id=rule.schedule_id,
        )
        plan = DatasetActionResolver(session).build_plan(request)
        if len(plan.units) != 1:
            raise ValueError("margin 远程探测未能生成单交易所单日 unit")
        return plan.units[0]

    @staticmethod
    def _row_matches_target(row: object, *, target_trade_date: date, exchange_id: str) -> bool:
        if not isinstance(row, dict):
            return False
        if str(row.get("exchange_id") or "").strip().upper() != exchange_id:
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
        matched_exchanges: list[str],
        missing_exchanges: list[str],
        sample_request_count: int,
        sample_hits: list[dict[str, str]],
    ) -> MarginRemoteReadinessProbeResult:
        return MarginRemoteReadinessProbeResult(
            matched=matched,
            message=message,
            payload={
                "dataset_key": MARGIN_DATASET_KEY,
                "condition_type": MARGIN_REMOTE_READY_CONDITION,
                "business_date": business_date.isoformat(),
                "target_trade_date": target_trade_date.isoformat() if target_trade_date else None,
                "required_exchanges": list(MARGIN_REQUIRED_EXCHANGES),
                "matched_exchanges": matched_exchanges,
                "missing_exchanges": missing_exchanges,
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
