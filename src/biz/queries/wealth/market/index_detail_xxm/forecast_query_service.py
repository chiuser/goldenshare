from bisect import bisect_right
from datetime import date, datetime, time as daytime, timedelta
import hashlib
import json
import time

from sqlalchemy import select
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.biz.schemas.wealth.market.index_detail_xxm_forecast import ForecastResponseDto
from src.biz.services.wealth.market.index_detail_xxm.forecast import forecast, inactive_result
from src.biz.services.wealth.market.index_detail_xxm.forecast_spec import FORECAST_SPEC
from src.biz.services.wealth.market.index_detail_xxm.forecast_text import make_display
from src.biz.services.wealth.market.index_detail_xxm.projection import recover_projection, ProjectionPrecisionError
from src.biz.services.wealth.market.index_detail_xxm.spec import MAIN_SPEC
from .query_service import IndexDetailXxmQueryService, XxmQueryError
from .source import CN_ZONE, ENDPOINTS, expected_through


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def future_calendar(session, period, through, check):
    anchor = date.fromisoformat(through[:10])
    end = anchor + timedelta(days=FORECAST_SPEC.future_calendar_days)
    check()
    rows = session.execute(select(TradeCalendar.trade_date, TradeCalendar.is_open).where(
        TradeCalendar.exchange == "SSE", TradeCalendar.trade_date >= anchor, TradeCalendar.trade_date <= end)
        .order_by(TradeCalendar.trade_date).limit(FORECAST_SPEC.future_calendar_days + 1)).all()
    check()
    slots = (daytime(15),) if period == "day" else ENDPOINTS[int(period[1:])]
    endpoints, identity = [], []
    previous = anchor - timedelta(days=1)
    for day, opened in rows:
        if day != previous + timedelta(days=1):
            raise XxmQueryError("XXM_SOURCE_CONTRACT_INVALID", "未来交易日历存在缺口。")
        previous = day
        identity.append((day.isoformat(), bool(opened)))
        if opened:
            for slot in slots:
                stamp = day.isoformat() if period == "day" else datetime.combine(day, slot, CN_ZONE).isoformat()
                if stamp > through:
                    endpoints.append(stamp)
                if len(endpoints) == FORECAST_SPEC.max_future_bars:
                    return tuple(endpoints), digest(identity)
    raise XxmQueryError("XXM_SOURCE_CONTRACT_INVALID", "未来交易日历未覆盖预测范围。")


class IndexDetailXxmForecastQueryService:
    def __init__(self, *, lake_root=None, cache=None):
        self.source = IndexDetailXxmQueryService(lake_root=lake_root, cache=cache)

    def build(self, session, *, period, as_of=None, now=None):
        mode = "REPLAY" if as_of is not None else "LATEST"
        with self.source.load_entry(session, period=period, now=now) as (entry, current, open_dates, remaining):
            end_date = date.fromisoformat(as_of[:10]) if as_of else None
            expected = expected_through(period, open_dates, current, end_date)
            if as_of is not None:
                if expected is None or as_of > expected or end_date not in open_dates:
                    raise XxmQueryError("XXM_REQUEST_INVALID", "asOf 必须是已完成的开市端点。", 400)
                expected = as_of
            n = bisect_right([b.time for b in entry.processed], expected) if expected else 0
            bars = entry.processed[:n]
            through = bars[-1].time if bars else None
            data_status = "EMPTY" if not through else "DELAYED" if expected and through < expected else "READY"
            result = inactive_result(data_status, "SOURCE_EMPTY" if not through else "SOURCE_DELAYED")
            calendar_id = None
            ordinary = entry.points[n - 1]["ordinaryState"] if n else None
            hist = entry.points[n - 1]["hist"] if n else 0
            direction = "TOP" if hist > 0 else "BOTTOM" if hist < 0 else None
            confirmation = next((e for e in reversed(entry.events) if e["time"] <= through and e["type"] == "STRUCTURE"), None) if through else None
            compute_start = None
            check = remaining
            if data_status == "READY" and (ordinary == "STRUCTURE" or confirmation and confirmation["time"] == through):
                result = inactive_result("CONFIRMED")
            elif data_status == "READY":
                endpoints, calendar_id = future_calendar(session, period, through, remaining)
                compute_start = time.perf_counter()
                def check():
                    remaining()
                    if (time.perf_counter() - compute_start) * 1000 > FORECAST_SPEC.forecast_compute_budget_ms:
                        raise XxmQueryError("XXM_BUDGET_EXCEEDED", "预测计算超过预算。", 503)
                calculator = entry.calculator_at(n, check)
                try:
                    projection = recover_projection(bars, period, check)
                    result = forecast(calculator, projection, endpoints, check)
                except ProjectionPrecisionError as exc:
                    result = inactive_result("PRECISION_PENDING", exc.reason)
                check()
            confirmed = result["status"] == "CONFIRMED"
            result["confirmedAt"] = confirmation["time"] if confirmed and confirmation else None
            result["confirmedDirection"] = confirmation["direction"] if confirmed and confirmation else None
            result["direction"] = result["confirmedDirection"] if confirmed else direction
            result["applicabilityText"] = (
                "目标只适用于列出的前置收盘范围；例子不是必须命中的价格。"
                if result["activation"] else "按当前真实状态与明确的中间走势假设计算。"
            )
            result["invalidationText"] = (
                "原钝化消失、零柱或前序走势变化时重新计算；未达结构条件不等于钝化已消失。"
                if result["status"] in ("READY", "CONDITIONAL_ENTRY", "ENTRY_ONLY") else "新完成行情到达后重新判断。"
            )
            payload = dict(tsCode="000001.SH", period=period, forecastVersion=FORECAST_SPEC.forecast_version,
                           forecastSpecHash=FORECAST_SPEC.spec_hash, detectorSpecHash=MAIN_SPEC.spec_hash,
                           sourceInputId=entry.fingerprints[n - 1] if n else None, calendarInputId=calendar_id,
                           computedThrough=through, requestedAsOf=as_of, mode=mode, dataStatus=data_status,
                           ordinaryState=ordinary, precisionPolicy="rounded3_guarded" if period == "day" else "full_float", **result)
            payload["forecastId"] = digest(payload)
            payload["display"] = make_display(result, period, through, mode)
            payload["refreshAfterMs"] = FORECAST_SPEC.refresh_after_ms
            response = ForecastResponseDto(**payload)
            if len(response.model_dump_json().encode()) > FORECAST_SPEC.max_response_bytes:
                raise XxmQueryError("XXM_BUDGET_EXCEEDED", "预测响应超过预算。", 503)
            check()
            return response
