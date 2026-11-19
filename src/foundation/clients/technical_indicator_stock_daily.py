"""Shared price projection and schedule rules for unadjusted stock daily bars."""

from datetime import date, timedelta

from goldenshare_technical_indicators.errors import SourceContractError, SourceUnsupportedError


DAILY_PRICE_FIELDS = ("open", "high", "low", "close", "volume", "amount")


INDEX_DAILY_ORIGINS = {"dg": date(2000, 1, 4), "prod_pg": date(1991, 7, 15)}


def daily_adjustment_paths(requirement, backend):
    if requirement.target.backend == backend and requirement.period == "day":
        if requirement.target.dataset_id == "stock_daily" and requirement.target_adjustment in ("none", "qfq"):
            return (("none", "none"), ("none", "qfq"))
        if (requirement.target.dataset_id == "index_daily" and requirement.ts_code == "000001.SH"
                and requirement.target_adjustment == "none"):
            return (("none", "none"),)
    raise SourceUnsupportedError("This reader supports stock daily and unadjusted SSE Composite daily bars")


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
