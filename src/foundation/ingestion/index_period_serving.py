"""Update an index Serving bar from the official period or complete daily Raw."""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, load_only

from src.foundation.ingestion.errors import IngestionValidationError, StructuredError
from src.foundation.ingestion.index_month_calendar import load_complete_open_dates
from src.foundation.models.core_serving.index_monthly_serving import IndexMonthlyServing
from src.foundation.models.core_serving.index_weekly_serving import IndexWeeklyServing
from src.foundation.models.raw.raw_index_daily import RawIndexDaily
from src.foundation.models.raw.raw_index_monthly_bar import RawIndexMonthlyBar
from src.foundation.models.raw.raw_index_weekly_bar import RawIndexWeeklyBar


IndexPeriodFrequency = Literal["week", "month"]
SHANGHAI = ZoneInfo("Asia/Shanghai")
# The closing time of the A-share session used by both index periods.
MARKET_CLOSE = time(15)
_DAILY_FIELDS = ("open", "high", "low", "close", "pre_close", "vol", "amount")
_BAR_VALUES = (*_DAILY_FIELDS, "pct_chg")


@dataclass(frozen=True, slots=True)
class IndexServingPeriod:
    frequency: IndexPeriodFrequency
    trade_date: date
    open_dates: tuple[date, ...]
    is_current: bool


@dataclass(frozen=True, slots=True)
class IndexServingCodeResult:
    rows_fetched: int = 0
    rows_saved: int = 0
    failure: StructuredError | None = None


@dataclass(frozen=True, slots=True)
class IndexServingInputs:
    result: IndexServingCodeResult = IndexServingCodeResult()
    formal: RawIndexWeeklyBar | RawIndexMonthlyBar | None = None
    daily: tuple[RawIndexDaily, ...] = ()


def _period_bounds(day: date, frequency: IndexPeriodFrequency) -> tuple[date, date]:
    if frequency == "week":
        start = day - timedelta(days=day.weekday())
        return start, start + timedelta(days=6)
    return day.replace(day=1), day.replace(day=monthrange(day.year, day.month)[1])


def invalid_serving_request(code: str, message: str, **details) -> IngestionValidationError:
    return IngestionValidationError(StructuredError(code, "validation", "plan", message, False, details=details))


def resolve_index_serving_period(
    session: Session, *, frequency: IndexPeriodFrequency, trade_date: date, exchange: str, now: datetime,
) -> IndexServingPeriod:
    local_now = now.astimezone(SHANGHAI)
    today = local_now.date()
    scope = {"frequency": frequency, "trade_date": trade_date.isoformat()}
    if trade_date > today or (trade_date == today and local_now.time() < MARKET_CLOSE):
        raise invalid_serving_request("index_period_serving.target_date", "目标交易日尚未收盘。", **scope)

    start, end = _period_bounds(trade_date, frequency)
    open_dates = load_complete_open_dates(session, exchange=exchange, start=start, end=end)
    if open_dates is None:
        raise invalid_serving_request("index_period_serving.calendar", "目标周期的交易日历不完整。", **scope)
    if trade_date not in open_dates:
        raise invalid_serving_request("index_period_serving.target_date", "目标日不是交易日。", **scope)
    is_current = end >= today
    if not is_current and trade_date != open_dates[-1]:
        raise invalid_serving_request(
            "index_period_serving.target_date", "过去周期须选择实际最后一个交易日。",
            period_end_date=open_dates[-1].isoformat(), **scope,
        )
    return IndexServingPeriod(frequency, trade_date, open_dates, is_current)


def load_index_serving_inputs(
    session: Session, *, period: IndexServingPeriod, ts_code: str, list_date: date | None,
    for_update: bool = False,
) -> IndexServingInputs:
    if list_date is None:
        return IndexServingInputs(result=_failure(period, ts_code, "list_date", "缺少指数发布日期。"))
    if period.trade_date < list_date:
        return IndexServingInputs()

    raw_model, model = ((RawIndexWeeklyBar, IndexWeeklyServing) if period.frequency == "week"
                        else (RawIndexMonthlyBar, IndexMonthlyServing))
    period_start, period_end = period.open_dates[0], period.open_dates[-1]
    formal = session.get(raw_model, (ts_code, period_end))
    if period.frequency == "month" and formal is not None and formal.api_name != "index_monthly":
        formal = None

    current_query = select(model).where(
        model.ts_code == ts_code, model.period_start_date == period_start,
    )
    if for_update:
        current_query = current_query.with_for_update()
    current = session.scalar(current_query)

    if formal is not None:
        return IndexServingInputs(result=IndexServingCodeResult(rows_fetched=1), formal=formal)

    if current is not None and (current.source == "api" or current.trade_date > period.trade_date):
        return IndexServingInputs()

    expected = tuple(day for day in period.open_dates if list_date <= day <= period.trade_date)
    if period.is_current and len(expected) > 1:
        actual = current.trade_date if current is not None else None
        if actual not in {expected[-2], period.trade_date}:
            return IndexServingInputs(result=_failure(
                period, ts_code, "continuity", "指数 Serving 截至日与上一交易日不一致。",
                expected_trade_date=expected[-2].isoformat(),
                actual_trade_date=actual.isoformat() if actual else None,
            ))

    daily = session.scalars(select(RawIndexDaily).where(
        RawIndexDaily.ts_code == ts_code, RawIndexDaily.trade_date.in_(expected),
    ).options(load_only(RawIndexDaily.trade_date, *(getattr(RawIndexDaily, field) for field in _DAILY_FIELDS)))
      .order_by(RawIndexDaily.trade_date)).all()
    present = {row.trade_date for row in daily}
    missing = [day.isoformat() for day in expected if day not in present]
    if missing:
        return IndexServingInputs(result=_failure(
            period, ts_code, "daily_missing", "指数 Raw 日线缺少应有交易日。",
            rows_fetched=len(daily), missing_dates=missing,
        ))
    invalid = [
        row.trade_date.isoformat() for row in daily
        if any(value is None or not value.is_finite() for value in (getattr(row, field) for field in _DAILY_FIELDS))
    ]
    if invalid or daily[0].pre_close == 0:
        return IndexServingInputs(result=_failure(
            period, ts_code, "daily_invalid", "指数 Raw 日线含有无效的行情值或计算起始日前收盘为零。",
            rows_fetched=len(daily), invalid_dates=invalid or [daily[0].trade_date.isoformat()],
        ))

    return IndexServingInputs(result=IndexServingCodeResult(rows_fetched=len(daily)), daily=tuple(daily))


def update_index_serving_bar(
    session: Session, *, period: IndexServingPeriod, ts_code: str, list_date: date | None,
) -> IndexServingCodeResult:
    inputs = load_index_serving_inputs(
        session, period=period, ts_code=ts_code, list_date=list_date, for_update=True,
    )
    if inputs.result.failure is not None or (inputs.formal is None and not inputs.daily):
        return inputs.result
    model = IndexWeeklyServing if period.frequency == "week" else IndexMonthlyServing
    period_start = period.open_dates[0]
    if inputs.formal is not None:
        formal = inputs.formal
        values = {field: getattr(formal, field) for field in _BAR_VALUES}
        rows_saved = _upsert_bar(
            session, model, ts_code=ts_code, period_start=period_start, trade_date=formal.trade_date,
            source="api", values={**values, "change_amount": formal.change},
        )
        return IndexServingCodeResult(rows_fetched=1, rows_saved=rows_saved)
    daily = inputs.daily
    first, last = daily[0], daily[-1]
    values = {
        "open": first.open, "high": max(row.high for row in daily),
        "low": min(row.low for row in daily), "close": last.close, "pre_close": first.pre_close,
        "change_amount": last.close - first.pre_close,
        "pct_chg": (last.close / first.pre_close - 1).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
        "vol": sum(row.vol for row in daily) * 100, "amount": sum(row.amount for row in daily) * 1000,
    }
    rows_saved = _upsert_bar(
        session, model, ts_code=ts_code, period_start=period_start, trade_date=period.trade_date,
        source="derived_daily", values=values,
    )
    return IndexServingCodeResult(rows_fetched=len(daily), rows_saved=rows_saved)


def _failure(
    period: IndexServingPeriod, ts_code: str, stage: str, message: str, *, rows_fetched: int = 0, **details,
) -> IndexServingCodeResult:
    return IndexServingCodeResult(rows_fetched=rows_fetched, failure=StructuredError(
        f"index_period_serving.{stage}", "validation", stage, message, False,
        details={"frequency": period.frequency, "ts_code": ts_code, "trade_date": period.trade_date.isoformat(),
                 "period_end_date": period.open_dates[-1].isoformat(), **details},
    ))


def _upsert_bar(
    session: Session, model, *, ts_code: str, period_start: date, trade_date: date, source: str, values: dict,
) -> int:
    row = {"trade_date": trade_date, "source": source, **values}
    statement = insert(model).values(ts_code=ts_code, period_start_date=period_start, **row)
    statement = statement.on_conflict_do_update(
        index_elements=[model.ts_code, model.period_start_date],
        set_={**{column: statement.excluded[column] for column in row}, "updated_at": func.now()},
        where=(statement.excluded.source == "api")
        | ((model.source != "api") & (model.trade_date <= statement.excluded.trade_date)),
    ).returning(model.ts_code)
    return int(session.scalar(statement) is not None)
