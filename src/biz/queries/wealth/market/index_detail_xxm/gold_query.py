"""Bounded ordinary history reads from the DG quantitative structure dataset."""
from collections import Counter
from datetime import date, datetime, time
from time import perf_counter

from goldenshare_technical_indicators.xxm.spec import MAIN_SPEC

from src.biz.queries.wealth.market.context.market_page_context_query import MarketPageContextQuery
from src.biz.schemas.wealth.market.index_detail_xxm_gold import GoldXxmResponseDto
from src.biz.services.wealth.market.index_detail_xxm.runtime import BUDGET, REQUEST_SLOTS
from src.foundation.clients.local_lake.index_daily_reader import IndexDailyLakeSourceError
from src.foundation.clients.local_lake.major_index_mins_reader import IndexMinuteHistoryBudgetError, IndexMinuteQueryError, IndexMinuteSourceContractError
from src.foundation.clients.local_lake.major_index_quantitative_structure_reader import read_structure_days
from .query_service import XxmQueryError, require_xxm_code
from .source import (
    CN_ZONE, DAILY_START, ENDPOINTS, MinuteSourceWindow, XxmLakeCalendar, minute_reader, read_minutes,
)

_DAILY_COLUMNS = ("trade_date", "close", "macd_dif_bfq", "macd_dea_bfq", "macd_bfq")
_DAILY_STARTS = {
    "399006.SZ": date(2010, 6, 1),
    "000688.SH": date(2019, 12, 31),
    "000510.SH": date(2024, 9, 23),
}
_MINUTE_STARTS = {
    **_DAILY_STARTS,
    "000688.SH": date(2020, 7, 23),
    "000852.SH": date(2014, 10, 17),
    "000510.SH": date(2024, 10, 22),
}


def _points(daily_lake, lake_root, *, ts_code, period, days, covered, remaining):
    if not covered:
        return []
    if period == "day":
        rows = daily_lake.factor_rows(
            ts_code=ts_code, dates=days, columns=_DAILY_COLUMNS, limit=len(covered), timeout_seconds=remaining(),
        )
        return [
            dict(time=row["trade_date"].isoformat(), close=row["close"], dif=row["macd_dif_bfq"],
                 dea=row["macd_dea_bfq"], hist=row["macd_bfq"])
            for row in rows
        ]
    window = MinuteSourceWindow(len(covered), len(covered), covered[0], covered[-1], days)
    return [
        dict(time=bar.time, close=bar.close, dif=bar.dif, dea=bar.dea, hist=bar.hist)
        for bar in read_minutes(minute_reader(lake_root), ts_code=ts_code, freq=int(period[1:]),
                                window=window, deadline=remaining)
    ]


def _stamp(period, day, endpoint):
    return day.isoformat() if period == "day" else datetime.combine(day, endpoint, CN_ZONE).isoformat()


def build_gold_history(*, daily_lake, lake_root=None, ts_code, period, start_date, end_date, limit, now=None):
    started = perf_counter()

    def remaining():
        left = BUDGET.request_deadline_seconds - (perf_counter() - started)
        if left <= 0:
            raise TimeoutError
        return left

    ts_code = require_xxm_code(ts_code)
    if daily_lake is None or daily_lake.root is None:
        raise XxmQueryError("XXM_QUERY_FAILED", "本机主要指数量化结构来源未配置。", 503)

    try:
        if not REQUEST_SLOTS.acquire(timeout=remaining()):
            raise TimeoutError
        try:
            return _read_window(daily_lake, lake_root, ts_code, period, start_date, end_date, limit,
                                (now or datetime.now(CN_ZONE)).astimezone(CN_ZONE), remaining)
        finally:
            REQUEST_SLOTS.release()
    except (TimeoutError, IndexMinuteHistoryBudgetError) as exc:
        raise XxmQueryError("XXM_BUDGET_EXCEEDED", "研究指标查询超时。", 503) from exc
    except (ValueError, TypeError, IndexDailyLakeSourceError, IndexMinuteSourceContractError) as exc:
        raise XxmQueryError("XXM_SOURCE_CONTRACT_INVALID", "研究指标来源存在缺口或字段不一致。") from exc
    except IndexMinuteQueryError as exc:
        raise XxmQueryError("XXM_QUERY_FAILED", "研究指标查询失败，请重试。") from exc


def _read_window(daily_lake, lake_root, ts_code, period, start_date, end_date, limit, now, remaining):
    calendar = XxmLakeCalendar(daily_lake, remaining=remaining)
    context = MarketPageContextQuery().resolve_local_context(
        daily_lake, market="CN_A", requested_trade_date=None, now=now,
        calendar_rows=calendar.recent(end=now.date(), open_days=2),
    )
    is_daily = period == "day"
    effective = (_DAILY_STARTS if is_daily else _MINUTE_STARTS).get(ts_code, DAILY_START)
    lower = max(effective, start_date or effective)
    upper = min(end_date or context.trade_date, context.trade_date)
    slots = (time(15),) if is_daily else ENDPOINTS[int(period[1:])]
    n = len(slots)
    selected = []
    if lower <= upper:
        dates = calendar.recent(end=upper, open_days=(limit + n - 1) // n + 1)
        selected = [
            stamp for day, opened, _ in dates if opened and lower <= day <= upper
            for endpoint in slots if (stamp := datetime.combine(day, endpoint, CN_ZONE)) <= now
        ][-limit:]
    days = tuple(dict.fromkeys(stamp.date() for stamp in selected))
    records = read_structure_days(daily_lake.root, days=days, ts_code=ts_code, period=period, remaining=remaining)
    last_day = max(records, default=None)
    for day in days:
        if day in records and not records[day][0]:
            raise XxmQueryError("XXM_QUERY_FAILED", f"{day} 量化结构识别失败。")
        if last_day is not None and day < last_day and day not in records:
            raise ValueError(f"{day} 缺少主要指数量化结构文件。")

    covered = [stamp for stamp in selected if stamp.date() in records]
    times = [_stamp(period, stamp.date(), stamp.time()) for stamp in covered]
    points = _points(daily_lake, lake_root, ts_code=ts_code, period=period,
                     days=tuple(day for day in days if day in records), covered=covered, remaining=remaining)
    if [point["time"] for point in points] != times:
        raise ValueError("量化结构曲线与识别窗口的完成端点不一致。")

    events = []
    order = Counter()
    time_set = set(times)
    for day in days:
        if day not in records:
            continue
        for event in records[day][1]:
            event_time = _stamp(period, day, event["bar_end_time"])
            if event_time in time_set:
                order[event_time] += 1
                events.append(dict(id=f"{ts_code}|{period}|{event_time}|{order[event_time]}",
                                   time=event_time, type=event["event_type"], direction=event["direction"],
                                   displayOnChart=event["display_on_chart"]))
    through = times[-1] if times else None
    if not times:
        status, message = "EMPTY", "量化结构结果尚未生成。" if selected else "暂无量化结构数据。"
    elif len(times) < len(selected):
        status, message = "DELAYED", f"量化结构结果截至 {through}。"
    else:
        status, message = "READY", None
    response = GoldXxmResponseDto(
        tsCode=ts_code, period=period, algorithmVersion=MAIN_SPEC.algorithm_version, specHash=MAIN_SPEC.spec_hash,
        points=points, events=events, meta=dict(count=len(points), responseStart=times[0] if times else None,
                                               responseEnd=through),
        dataStatus=dict(status=status, message=message, asOf=through),
    )
    body = response.model_dump_json().encode("utf-8")
    if len(body) > BUDGET.max_response_bytes:
        raise XxmQueryError("XXM_BUDGET_EXCEEDED", "研究指标响应超过预算。", 503)
    remaining()
    return body
