from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.clients.local_lake.major_index_mins_contract import GOLD_INDICATOR_VERSION
from src.foundation.clients.local_lake.major_index_mins_reader import MajorIndexMinsLakeReader, IndexMinuteReadRequest
from src.foundation.models.core.index_factor_pro import IndexFactorPro
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.biz.services.wealth.market.index_detail_xxm.runtime import BUDGET
from src.biz.services.wealth.market.index_detail_xxm.types import XxmBar, XxmPeriod


CN_ZONE = ZoneInfo("Asia/Shanghai")
ENDPOINTS = {60: (time(10, 30), time(11, 30), time(14), time(15)),
             90: (time(11), time(14), time(15)), 120: (time(11, 30), time(15))}


class XxmSourceError(ValueError):
    pass


def calendar_dates(session: Session, *, end: date) -> tuple[date, ...]:
    rows = session.execute(select(TradeCalendar.trade_date, TradeCalendar.is_open).where(
        TradeCalendar.exchange == "SSE", TradeCalendar.trade_date >= date(1990, 1, 1),
        TradeCalendar.trade_date <= end).order_by(TradeCalendar.trade_date)).all()
    if not rows or rows[-1][0] != end:
        raise XxmSourceError("SSE 交易日历未覆盖计算日期。")
    return tuple(row[0] for row in rows if row[1])


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


def read_daily(session: Session, *, completed: str | None, check: Callable[[], None]) -> tuple[XxmBar, ...]:
    if completed is None:
        return ()
    values, after = [], None
    while True:
        check()
        conditions = [IndexFactorPro.ts_code == "000001.SH", IndexFactorPro.trade_date <= date.fromisoformat(completed)]
        if after is not None:
            conditions.append(IndexFactorPro.trade_date > after)
        batch = session.execute(select(IndexFactorPro.trade_date, IndexFactorPro.close, IndexFactorPro.macd_dif_bfq,
                                       IndexFactorPro.macd_dea_bfq, IndexFactorPro.macd_bfq).where(*conditions)
                                .order_by(IndexFactorPro.trade_date).limit(BUDGET.source_batch_rows)).all()
        if not batch:
            break
        for row in batch:
            try:
                bar = XxmBar(row[0].isoformat(), *(float(value) for value in row[1:]))
                bar.validate("day")
            except (ValueError, TypeError) as exc:
                raise XxmSourceError("日线必需指标或收盘值异常。") from exc
            values.append(bar)
        if len(values) > BUDGET.max_source_rows:
            raise OverflowError("XXM 日线源行数超预算。")
        after = batch[-1][0]
    return tuple(values)


def minute_request(freq: int, end: date, start: date | None = None) -> IndexMinuteReadRequest:
    return IndexMinuteReadRequest("000001.SH", freq, start, end, BUDGET.source_batch_rows, None)


def read_minutes(reader: MajorIndexMinsLakeReader, *, freq: int, end: date, deadline: Callable[[], float],
                 start: date | None = None) -> tuple[XxmBar, ...]:
    request = minute_request(freq, end, start)
    bars = reader.read_complete_history(request, dataset="bars", timeout_seconds=deadline())
    indicators = reader.read_complete_history(request, dataset="indicators", timeout_seconds=deadline())
    key = lambda row: (row["ts_code"], row["freq"], row["trade_date"], row["trade_time"])
    if tuple(map(key, bars.rows)) != tuple(map(key, indicators.rows)):
        raise XxmSourceError("分钟价格与指标的完整时间集合不一致。")
    result = []
    for price, indicator in zip(bars.rows, indicators.rows, strict=True):
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
    if actual != tuple(sorted(set(actual))):
        raise XxmSourceError("输入时间重复或乱序。")
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
