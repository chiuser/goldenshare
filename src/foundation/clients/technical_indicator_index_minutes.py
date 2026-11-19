"""Physical and standard field contracts for verified index five-minute bars."""

from goldenshare_technical_indicators.errors import SourceUnsupportedError

from .technical_indicator_stock_daily import DAILY_PRICE_FIELDS


INDEX_MINUTE_VOLUME_UNITS = {
    "000001.SH": "lot",
    "000016.SH": "lot",
    "000688.SH": "lot",
    "000300.SH": "lot",
    "000905.SH": "lot",
    "399001.SZ": "share",
    "399006.SZ": "share",
    "399106.SZ": "share",
}


def index_minute_volume_unit(requirement, backend):
    if (requirement.target.backend != backend or requirement.target.dataset_id != "index_mins_5m"
            or requirement.period != "5m" or requirement.target_adjustment != "none"
            or requirement.ts_code not in INDEX_MINUTE_VOLUME_UNITS):
        raise SourceUnsupportedError("This source has no verified unadjusted five-minute contract for this index")
    return INDEX_MINUTE_VOLUME_UNITS[requirement.ts_code]


def index_minute_projection(fields):
    price_columns = tuple(
        ("vol" if field == "volume" else field, field) for field in DAILY_PRICE_FIELDS if field in fields
    )
    return (
        ("ts_code", "trade_date", "trade_time", "freq", *(column for column, _ in price_columns)),
        (
            ("trade_date", 'CAST(b."trade_date" AS DATE)'),
            ("trade_time", 'CAST(b."trade_time" AS TIMESTAMP)'),
            *((field, f'CAST(b."{column}" AS DOUBLE)') for column, field in price_columns),
        ),
    )
