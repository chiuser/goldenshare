"""One bounded read and one in-memory calculation; no route or persistence."""
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import math
from uuid import uuid4

from src.biz.services.wealth.market.index_detail_daily_wave.budget import (
    DailyWaveBudget, DailyWaveBudgetExceeded,
    DailyWaveSourceInputError,
)
from src.biz.services.wealth.market.index_detail_daily_wave.calculator import (
    build_review, histogram_color,
)
from src.biz.services.wealth.market.index_detail_daily_wave.spec import DEFAULT_SPEC
from src.biz.services.wealth.market.index_detail_daily_wave.types import (
    CalendarDay, DateRange, decimal_text,
)
from .query import DailyWaveQuery, DailyWaveSourceError

SHANGHAI = timezone(timedelta(hours=8))
MARKET_COLUMNS = frozenset(("ts_code", "trade_date", "close", "macd_dif_bfq", "macd_dea_bfq", "macd_bfq"))


def _source_date(value):
    if type(value) is not date:
        raise DailyWaveSourceError("源日期必须为DATE，不能是文本或时间戳")
    return value


def normalize_source_row(row, *, calculated_at, spec):
    if not isinstance(row, Mapping) or set(row) != MARKET_COLUMNS:
        raise DailyWaveSourceError("源行情字段必须为约定六列")
    if not isinstance(row["ts_code"], str) or row["ts_code"] != spec.ts_code:
        raise DailyWaveSourceError("源行情对象错误")
    day = _source_date(row["trade_date"])
    if calculated_at.tzinfo is None or calculated_at.utcoffset() is None:
        raise DailyWaveSourceError("计算时间缺少时区")
    if datetime.combine(day, datetime.min.time(), SHANGHAI) + timedelta(hours=15) > calculated_at:
        raise DailyWaveSourceError("源行情尚未完成日线收盘")
    output = dict(tsCode=row["ts_code"], date=day.isoformat(), completed=True)
    for target, source in (("close", "close"), ("dif", "macd_dif_bfq"),
                           ("dea", "macd_dea_bfq"), ("macd", "macd_bfq")):
        value = row[source]
        if type(value) is not float or not math.isfinite(value):
            raise DailyWaveSourceError(f"源字段{source}必须为有限Float(53)")
        if target == "close" and value <= 0:
            raise DailyWaveSourceError("源收盘价必须大于零")
        output[target] = decimal_text(Decimal(str(value)))
    return output


def validate_calendar(rows, *, context_range, market_dates):
    if not rows:
        raise DailyWaveSourceError("缺少本次SSE日历")
    expected = date.fromisoformat(context_range.startDate)
    end = date.fromisoformat(context_range.endDate)
    output = []
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != {"exchange", "trade_date", "is_open"}:
            raise DailyWaveSourceError("源日历字段错误")
        day = _source_date(row["trade_date"])
        if row["exchange"] != "SSE" or type(row["is_open"]) is not bool or day != expected or day > end:
            raise DailyWaveSourceError(f"SSE日历不连续、重复或字段错误：{expected.isoformat()}")
        output.append(CalendarDay("SSE", day.isoformat(), row["is_open"]))
        expected += timedelta(days=1)
    if expected != end + timedelta(days=1):
        raise DailyWaveSourceError(f"SSE日历缺少日期：{expected.isoformat()}")
    open_days = {row.date for row in output if row.isOpen}
    market = set(market_dates)
    missing, extra = sorted(open_days - market), sorted(market - open_days)
    if missing or extra:
        raise DailyWaveSourceError(f"行情与SSE开市日不一致，缺少：{missing}；休市多出：{extra}")
    return tuple(output)


def needs_more_context(normalized_rows, *, observation_range):
    segments = []
    for row in normalized_rows:
        color = histogram_color(Decimal(row["macd"]))
        if color is None:
            if segments:
                segments[-1][2] = row["date"]
            continue
        if not segments or color != segments[-1][0]:
            segments.append([color, row["date"], row["date"]])
        else:
            segments[-1][2] = row["date"]
    for i, (_, start, end) in enumerate(segments):
        if start <= observation_range.endDate and end >= observation_range.startDate:
            return i < 2  # Segment zero has an unknown true left boundary.
    return True


def _validate_window(rows, *, before=None, start=None, end=None, spec):
    previous = None
    for row in rows:
        if not isinstance(row, Mapping) or row.get("ts_code") != spec.ts_code:
            raise DailyWaveSourceError("查询返回错误行情对象")
        day = _source_date(row.get("trade_date"))
        if day < date.fromisoformat(spec.absolute_start):
            raise DailyWaveSourceError("查询返回了绝对下界之前的行情")
        if before is not None:
            if day >= before or previous is not None and day >= previous:
                raise DailyWaveSourceError("前段日期必须严格倒序、唯一且早于指定日")
        elif not start <= day <= end or previous is not None and day <= previous:
            raise DailyWaveSourceError("主范围日期必须升序、唯一且位于请求范围")
        previous = day


class DailyWaveQueryService:
    def __init__(self, session_factory, query=None, clock=None, new_id=None):
        self.session_factory = session_factory
        self.query = query or DailyWaveQuery()
        self.clock = clock or (lambda: datetime.now(SHANGHAI))
        self.new_id = new_id or uuid4

    async def build(self, *, spec=DEFAULT_SPEC, check_cancelled=None, deadline=None):
        budget = DailyWaveBudget(spec, deadline=deadline, check_cancelled=check_cancelled)
        budget.check()
        when = self.clock()
        if not isinstance(when, datetime) or when.tzinfo is None or when.utcoffset() is None:
            raise DailyWaveSourceError("计算时间必须有时区")
        when = when.astimezone(SHANGHAI)
        identity = str(self.new_id())
        completed = when.date() if when.hour >= 15 else when.date() - timedelta(days=1)
        end = min(date.fromisoformat(spec.requested_end), completed)
        start = date.fromisoformat(spec.requested_start)
        normalized, calendar, observation = [], (), None
        async with self.session_factory(budget=budget) as session:
            main = await self.query.load_main_window(session, start_date=start, end_date=end, spec=spec)
            budget.check()
            if len(main) > spec.max_main_points:
                raise DailyWaveBudgetExceeded("主范围超过根数上限")
            _validate_window(main, start=start, end=end, spec=spec)
            if main:
                observation = DateRange(main[0]["trade_date"].isoformat(), main[-1]["trade_date"].isoformat())
                normalized_main = [normalize_source_row(row, calculated_at=when, spec=spec) for row in main]
                context = []
                before = main[0]["trade_date"]
                for batch in range(2):
                    budget.check()
                    rows = await self.query.load_context_window(session, before_date=before, spec=spec)
                    if len(rows) > spec.context_batch_points + 1:
                        raise DailyWaveBudgetExceeded("前段查询超过探测上限")
                    _validate_window(rows, before=before, spec=spec)
                    selected = rows[:spec.context_batch_points]
                    context = list(reversed([normalize_source_row(row, calculated_at=when, spec=spec)
                                             for row in selected])) + context
                    normalized = context + normalized_main
                    if len(context) > spec.max_context_points:
                        raise DailyWaveBudgetExceeded("前段超过根数上限")
                    if batch or len(rows) <= spec.context_batch_points or not needs_more_context(
                            normalized, observation_range=observation):
                        break
                    before = selected[-1]["trade_date"]
                days = [row["date"] for row in normalized]
                if len(set(days)) != len(days) or days != sorted(days):
                    raise DailyWaveSourceError("合并行情日期重复或逆序，不允许静默去重")
                if len(normalized) > spec.max_total_points:
                    raise DailyWaveBudgetExceeded("行情超过总根数上限")
                raw_calendar = await self.query.load_calendar(session,
                    context_start=date.fromisoformat(days[0]), observation_end=main[-1]["trade_date"], spec=spec)
                if len(raw_calendar) > spec.max_calendar_days:
                    raise DailyWaveBudgetExceeded("日历超过自然日上限")
                calendar = validate_calendar(raw_calendar,
                    context_range=DateRange(days[0], days[-1]), market_dates=days)
            budget.check()
        budget.check()
        try:
            # This sole base input validation also checks H; no local EMA or second scan.
            result = build_review(normalized, observation_range=observation, calendar=calendar,
                as_of=end.isoformat(), calculation_id=identity, calculated_at=when,
                spec=spec, deadline=budget.deadline, check_cancelled=check_cancelled)
        except DailyWaveSourceInputError as exc:
            raise DailyWaveSourceError(str(exc)) from exc
        budget.check()
        return result
