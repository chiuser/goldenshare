"""Shared contracts and schedule rules for ordinary stock and index daily bars."""

from datetime import date, timedelta

from goldenshare_technical_indicators.errors import SourceContractError, SourceReadError, SourceUnsupportedError


DAILY_PRICE_FIELDS = ("open", "high", "low", "close", "volume", "amount")


PROD_INDEX_DAILY_ORIGIN = date(1991, 7, 15)
_DG_INDEX_DAILY_ORIGINS = {
    "000001.SH": date(2000, 1, 4),
    "399001.SZ": date(2000, 1, 4),
    "000016.SH": date(2004, 1, 2),
    "000300.SH": date(2005, 1, 4),
    "000905.SH": date(2005, 1, 4),
    "000852.SH": date(2005, 1, 4),
    "399006.SZ": date(2010, 6, 1),
    "000688.SH": date(2020, 1, 2),  # 2019-12-31 contains only the 1,000-point base value.
    "899050.BJ": date(2022, 12, 19),
    "000510.SH": date(2024, 9, 23),
}


def dg_index_daily_origin(ts_code: str) -> date:
    origin = _DG_INDEX_DAILY_ORIGINS.get(ts_code)
    if origin is None:
        raise SourceReadError("读取数据失败", detail=f"{ts_code} 的 DG 普通指数日线未配置历史起点")
    return origin


def daily_adjustment_paths(requirement, backend):
    if requirement.target.backend == backend and requirement.period == "day":
        if requirement.target.dataset_id == "stock_daily" and requirement.target_adjustment in ("none", "qfq"):
            return (("none", "none"), ("none", "qfq"))
        if (requirement.target.dataset_id == "index_daily" and requirement.target_adjustment == "none"
                and (backend == "dg" or requirement.ts_code == "000001.SH")):
            return (("none", "none"),)
    raise SourceUnsupportedError("This reader supports stock daily and configured unadjusted index daily bars")


def daily_price_projection(fields):
    if not fields <= set(DAILY_PRICE_FIELDS):
        raise SourceContractError("The source cannot supply the requested fields")
    price_columns = tuple(
        ("vol" if field == "volume" else field, field) for field in DAILY_PRICE_FIELDS if field in fields
    )
    return (
        ("ts_code", "trade_date", *(column for column, _ in price_columns)),
        (
            *((name, 'CAST(b."trade_date" AS DATE)')
              for name in ("trade_date", "period_start", "period_end", "source_as_of")),
            *((field, f'CAST(b."{column}" AS DOUBLE)') for column, field in price_columns),
        ),
    )


def scheduled_stock_days(calendar, lifecycle, start, end):
    if (len(lifecycle) != 1 or type(lifecycle[0][0]) is not date
            or lifecycle[0][1] is not None and type(lifecycle[0][1]) is not date):
        raise SourceContractError("Stock lifecycle is missing or invalid")
    listed, delisted = lifecycle[0]
    start = max(start, listed)
    if delisted is not None:
        end = min(end, delisted - timedelta(days=1))
    yield from scheduled_open_days(calendar, start, end)


def scheduled_open_days(calendar, start, end):
    expected = start
    for day, is_open in calendar:
        if type(day) is not date:
            raise SourceContractError("Trading calendar has an invalid date")
        if day < start or day > end:
            continue
        if day != expected or type(is_open) is not bool:
            raise SourceContractError("Trading calendar is incomplete, duplicated or invalid")
        if is_open:
            yield day
        expected += timedelta(days=1)
    if expected <= end:
        raise SourceContractError("Trading calendar does not cover the selected daily range")


def full_day_suspension(records):
    rows = tuple(records)
    return bool(rows) and all(kind == "S" and timing is None for kind, timing in rows)
