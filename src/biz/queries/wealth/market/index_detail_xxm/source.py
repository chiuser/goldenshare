from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.foundation.clients.local_lake.index_daily_reader import IndexDailyLakeReader
from src.foundation.clients.local_lake.major_index_mins_contract import GOLD_INDICATOR_VERSION
from src.foundation.clients.local_lake.major_index_mins_reader import MajorIndexMinsLakeReader, IndexMinuteReadRequest
from src.foundation.models.core.index_factor_pro import IndexFactorPro
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.biz.services.wealth.market.index_detail_xxm.runtime import BUDGET
from goldenshare_technical_indicators.xxm.types import XxmBar, XxmPeriod


CN_ZONE = ZoneInfo("Asia/Shanghai")
DAILY_START = date(2010, 1, 4)
_DAILY_COLUMNS = ("trade_date", "close", "macd_dif_bfq", "macd_dea_bfq", "macd_bfq")
ENDPOINTS = {30: (time(10), time(10, 30), time(11), time(11, 30),
                  time(13, 30), time(14), time(14, 30), time(15)),
             60: (time(10, 30), time(11, 30), time(14), time(15)),
             90: (time(11), time(14), time(15)), 120: (time(11, 30), time(15))}


class XxmSourceError(ValueError):
    pass


class XxmLakeCalendar:
    """One request's SSE rows, reused by context, source and forecast."""

    def __init__(self, reader: IndexDailyLakeReader) -> None:
        self.reader = reader
        self.rows: tuple[tuple[date, bool, date | None], ...] = ()

    def range(self, *, start: date, end: date) -> tuple[tuple[date, bool, date | None], ...]:
        if start > end:
            return ()
        if not self.rows or end < self.rows[0][0] or start > self.rows[-1][0]:
            self.rows = self.reader.calendar_rows(start=start, end=end)
            return self.rows
        if start < self.rows[0][0]:
            earlier = self.reader.calendar_rows(start=start, end=self.rows[0][0] - timedelta(days=1))
            self.rows = earlier + self.rows
        if end > self.rows[-1][0]:
            later = self.reader.calendar_rows(start=self.rows[-1][0] + timedelta(days=1), end=end)
            self.rows += later
        first = bisect_left(self.rows, start, key=lambda row: row[0])
        last = bisect_right(self.rows, end, key=lambda row: row[0])
        return self.rows[first:last]

    def recent(self, *, end: date, open_days: int) -> tuple[tuple[date, bool, date | None], ...]:
        if not self.rows or not self.rows[0][0] <= end <= self.rows[-1][0]:
            self.rows = self.reader.calendar_rows(end=end, recent_open_days=open_days)
            return self.rows
        last = bisect_right(self.rows, end, key=lambda row: row[0])
        visible = self.rows[:last]
        opens = [index for index, (_, opened, _) in enumerate(visible) if opened]
        if len(opens) >= open_days:
            return visible[opens[-open_days]:]
        earlier = self.reader.calendar_rows(end=self.rows[0][0] - timedelta(days=1),
                                            recent_open_days=open_days - len(opens))
        self.rows = earlier + self.rows
        return earlier + visible


@dataclass(frozen=True, slots=True)
class MinuteSourceWindow:
    output_rows: int
    read_rows: int
    start_time: datetime | None
    end_time: datetime | None
    open_dates: tuple[date, ...]


def normalize_minute_end(*, period: XxmPeriod, requested_end: date | datetime | None,
                         context, now: datetime) -> datetime | None:
    completed = expected_through(period, (context.trade_date,), now, context.trade_date)
    if completed is None:
        return None
    upper = datetime.fromisoformat(completed)
    if isinstance(requested_end, datetime):
        return min(requested_end.astimezone(CN_ZONE), upper)
    if requested_end is not None:
        return min(datetime.combine(requested_end, ENDPOINTS[int(period[1:])][-1], CN_ZONE), upper)
    return upper


def plan_minute_window(session: Session, *, period: XxmPeriod, output_rows: int,
                       requested_end: datetime | None, context, now: datetime,
                       check: Callable[[], object], lake_calendar: XxmLakeCalendar | None = None) -> MinuteSourceWindow:
    """Plan completed endpoints before discovering any minute files (LLD 0.9)."""
    if type(output_rows) is not int or not 1 <= output_rows <= BUDGET.max_response_rows:
        raise ValueError("分钟返回根数不合法。")
    read_rows = output_rows + BUDGET.source_extra_rows
    check()
    if requested_end is None or requested_end.date() < date(1990, 1, 1):
        return MinuteSourceWindow(output_rows, read_rows, None, None, ())
    end = requested_end.date()
    slots = ENDPOINTS[int(period[1:])]
    open_day_count = (read_rows + len(slots) - 1) // len(slots) + 1
    if lake_calendar is not None:
        rows = tuple((day, opened) for day, opened, _ in lake_calendar.recent(end=end, open_days=open_day_count))
    else:
        recent = (select(TradeCalendar.trade_date).where(
            TradeCalendar.exchange == "SSE", TradeCalendar.is_open.is_(True), TradeCalendar.trade_date <= end)
            .order_by(TradeCalendar.trade_date.desc()).limit(open_day_count).cte("xxm_recent_open_dates"))
        first = select(func.min(recent.c.trade_date)).scalar_subquery()
        rows = session.execute(select(TradeCalendar.trade_date, TradeCalendar.is_open).where(
            TradeCalendar.exchange == "SSE", TradeCalendar.trade_date >= func.coalesce(first, end),
            TradeCalendar.trade_date <= end).order_by(TradeCalendar.trade_date)).all()
    check()
    if not rows or rows[-1][0] != end:
        raise XxmSourceError("SSE 交易日历未覆盖计算日期。")
    open_dates = []
    previous = None
    for day, opened in rows:
        check()
        if (type(day) is not date or type(opened) is not bool
                or previous is not None and day != previous + timedelta(days=1)):
            raise XxmSourceError("SSE 交易日历存在缺口或字段异常。")
        previous = day
        if opened:
            open_dates.append(day)
    endpoints = []
    for day in open_dates:
        check()
        for slot in slots:
            stamp = datetime.combine(day, slot, CN_ZONE)
            if stamp <= requested_end and stamp <= now:
                endpoints.append(stamp)
    selected = endpoints[-read_rows:]
    return MinuteSourceWindow(output_rows, read_rows, selected[0] if selected else None,
                              selected[-1] if selected else None, tuple(open_dates))


def calendar_dates(session: Session, *, start: date, end: date) -> tuple[date, ...]:
    if start > end:
        raise XxmSourceError("SSE 交易日历查询起止日期不合法。")
    rows = session.execute(select(TradeCalendar.trade_date, TradeCalendar.is_open).where(
        TradeCalendar.exchange == "SSE", TradeCalendar.trade_date >= start,
        TradeCalendar.trade_date <= end).order_by(TradeCalendar.trade_date)).all()
    if not rows or rows[-1][0] != end:
        raise XxmSourceError("SSE 交易日历未覆盖计算日期。")
    return tuple(row[0] for row in rows if row[1])


def is_open_date(session: Session, day: date) -> bool:
    rows = session.execute(select(TradeCalendar.trade_date, TradeCalendar.is_open).where(
        TradeCalendar.exchange == "SSE", TradeCalendar.trade_date == day)).all()
    if len(rows) != 1 or rows[0][0] != day or type(rows[0][1]) is not bool:
        raise XxmSourceError("SSE 交易日历未覆盖请求日期或字段异常。")
    return rows[0][1]


def expected_through(period: XxmPeriod, open_dates: tuple[date, ...], now: datetime, end: date | None) -> str | None:
    upper = min(now.date(), end or now.date())
    times = (time(15),) if period == "day" else ENDPOINTS[int(period[1:])]
    for day in reversed(open_dates):
        if day > upper:
            continue
        for endpoint in reversed(times):
            stamp = datetime.combine(day, endpoint, CN_ZONE)
            if stamp <= now:
                return day.isoformat() if period == "day" else stamp.isoformat()
    return None


def read_daily(session: Session, *, ts_code: str, completed: str | None,
               check: Callable[[], None]) -> tuple[XxmBar, ...]:
    if completed is None:
        return ()
    values, after = [], None
    while True:
        check()
        conditions = [IndexFactorPro.ts_code == ts_code, IndexFactorPro.trade_date <= date.fromisoformat(completed)]
        if after is not None:
            conditions.append(IndexFactorPro.trade_date > after)
        batch = session.execute(select(IndexFactorPro.trade_date, IndexFactorPro.close, IndexFactorPro.macd_dif_bfq,
                                       IndexFactorPro.macd_dea_bfq, IndexFactorPro.macd_bfq).where(*conditions)
                                .order_by(IndexFactorPro.trade_date).limit(BUDGET.source_batch_rows)).all()
        if not batch:
            break
        for row in batch:
            values.append(_daily_bar(*row))
        if len(values) > BUDGET.max_source_rows:
            raise OverflowError("XXM 日线源行数超预算。")
        after = batch[-1][0]
    return tuple(values)


def read_lake_daily(reader: IndexDailyLakeReader, *, ts_code: str, completed: str | None,
                    check: Callable[[], None]) -> tuple[XxmBar, ...]:
    if completed is None or (end := date.fromisoformat(completed)) < DAILY_START:
        return ()
    check()
    dates = reader.factor_dates(start=DAILY_START, end=end)
    check()
    rows = reader.factor_rows(ts_code=ts_code, dates=dates, columns=_DAILY_COLUMNS, limit=BUDGET.max_source_rows + 1)
    check()
    if len(rows) > BUDGET.max_source_rows:
        raise OverflowError("XXM 日线源行数超预算。")
    return tuple(_daily_bar(*(row[column] for column in _DAILY_COLUMNS)) for row in rows)


def _daily_bar(day: date, *values: float) -> XxmBar:
    try:
        bar = XxmBar(day.isoformat(), *(float(value) for value in values))
        bar.validate("day")
    except (AttributeError, ValueError, TypeError) as exc:
        raise XxmSourceError("日线必需指标或收盘值异常。") from exc
    return bar


def minute_request(freq: int, window: MinuteSourceWindow, *, ts_code: str) -> IndexMinuteReadRequest:
    if window.start_time is None or window.end_time is None:
        raise ValueError("空分钟范围不能读取文件。")
    return IndexMinuteReadRequest(ts_code, freq, window.start_time.date(), window.end_time.date(),
                                  window.read_rows, None)


def read_minutes(reader: MajorIndexMinsLakeReader, *, ts_code: str, freq: int, window: MinuteSourceWindow,
                 deadline: Callable[[], float]) -> tuple[XxmBar, ...]:
    request = minute_request(freq, window, ts_code=ts_code)
    bars, indicators = reader.read_complete_history_pair(request, timeout_seconds=deadline(),
        max_rows=window.read_rows,
        time_window=(window.start_time.replace(tzinfo=None), window.end_time.replace(tzinfo=None)),
        bar_value_columns=("close",), indicator_value_columns=("macd_dif", "macd_dea", "macd"))
    if len(bars.rows) != len(indicators.rows):
        raise XxmSourceError("分钟价格与指标的完整时间集合不一致。")
    result = []
    for price, indicator in zip(bars.rows, indicators.rows, strict=True):
        if ((price["ts_code"], price["freq"], price["trade_date"], price["trade_time"])
                != (indicator["ts_code"], indicator["freq"], indicator["trade_date"], indicator["trade_time"])):
            raise XxmSourceError("分钟价格与指标的完整时间集合不一致。")
        stamp = price["trade_time"]
        if stamp.tzinfo is not None:
            raise XxmSourceError("正式分钟时间应为上海本地无时区时间。")
        try:
            bar = XxmBar(stamp.replace(tzinfo=CN_ZONE).isoformat(), float(price["close"]),
                         float(indicator["macd_dif"]), float(indicator["macd_dea"]), float(indicator["macd"]))
            bar.validate(f"m{freq}")
        except (ValueError, TypeError) as exc:
            raise XxmSourceError("分钟必需指标异常。") from exc
        result.append(bar)
    return tuple(result)


def assert_continuous(values: tuple[XxmBar, ...], *, period: XxmPeriod, open_dates: tuple[date, ...]) -> None:
    if not values:
        return
    actual = tuple(bar.time for bar in values)
    first_date, last_date = date.fromisoformat(actual[0][:10]), date.fromisoformat(actual[-1][:10])
    days = [day for day in open_dates if first_date <= day <= last_date]
    if period == "day":
        expected = tuple(day.isoformat() for day in days)
    else:
        expected = tuple(datetime.combine(day, endpoint, CN_ZONE).isoformat() for day in days
                         for endpoint in ENDPOINTS[int(period[1:])]
                         if actual[0] <= datetime.combine(day, endpoint, CN_ZONE).isoformat() <= actual[-1])
    if expected != actual:
        raise XxmSourceError("正式输入存在交易日／分钟端点缺口或非法端点。")


def minute_reader(root: Path) -> MajorIndexMinsLakeReader:
    return MajorIndexMinsLakeReader(root)


INDICATOR_VERSION = GOLD_INDICATOR_VERSION
