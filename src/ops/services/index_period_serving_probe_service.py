"""Read only the inputs needed by the two index Serving maintenance actions."""

from datetime import datetime, time

from sqlalchemy.orm import Session

from src.foundation.config.settings import get_settings
from src.foundation.ingestion.index_period_serving import SHANGHAI, load_index_serving_inputs
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.ops.models.ops.probe_rule import ProbeRule
from src.ops.runtime.index_period_serving_executor import IndexPeriodServingExecutor
from src.ops.services.index_period_schedule import INDEX_PERIOD_SERVING_TARGETS


class IndexPeriodServingProbeService:
    def evaluate(self, session: Session, rule: ProbeRule, *, current: datetime) -> tuple[bool, str, dict]:
        action_key = rule.on_success_action_json["action_key"]
        frequency, dataset_key = INDEX_PERIOD_SERVING_TARGETS[action_key]
        local_now = current.astimezone(SHANGHAI)
        target = local_now.date()
        payload = {"dataset_key": dataset_key, "frequency": frequency,
                   "target_trade_date": target.isoformat()}
        if local_now.time() < time.fromisoformat(rule.window_start):
            return False, "尚未进入当天 Serving 探测窗口", payload
        calendar = session.get(TradeCalendar, (get_settings().default_exchange, target))
        if calendar is None or not calendar.is_open:
            return False, "目标日不是已确认的交易日", payload
        period, codes, list_dates = IndexPeriodServingExecutor.prepare_in_session(
            session, frequency, {"trade_date": target.isoformat()}, now=current,
        )
        ready, failures = [], []
        rows_fetched = 0
        for code in codes:
            inputs = load_index_serving_inputs(
                session, period=period, ts_code=code, list_date=list_dates.get(code),
            )
            rows_fetched += inputs.result.rows_fetched
            failure = inputs.result.failure
            if failure is None:
                ready.append(code)
            else:
                failures.append({"code": failure.error_code, "message": failure.message, **failure.details})
        payload.update(ready_codes=ready, ready_count=len(ready), required_count=len(codes),
                       failures=failures, rows_fetched=rows_fetched)
        if failures:
            missing_codes = ", ".join(item["ts_code"] for item in failures)
            return False, f"Serving 所需数据尚未齐备：{missing_codes}", payload
        return True, "池内指数均具备 Serving 更新条件", payload
