"""Physical locations for stock and index market data. Enablement is separate per backend."""


DATASET_LOCATIONS = {
    "trade_calendar": {
        "dg": {"relative_path": "silver/calendar/trade_calendar/full/part-000.parquet"},
        "prod_pg": {"schema": "core_serving", "relation": "trade_calendar", "filters": {"exchange": "SSE"}},
    },
    "stock_lifecycle": {
        "dg": {"relative_path": "silver/basic/stock_lifecycle/full/part-000.parquet"},
        "prod_pg": {"schema": "core_serving", "relation": "security_serving"},
    },
    "stock_suspend_daily": {
        "dg": {"relative_path": "silver/quote/stock_suspend_daily/trade_date={trade_date}/part-000.parquet"},
        "prod_pg": {"schema": "core_serving", "relation": "equity_suspend_d"},
    },
    "stock_daily": {
        "dg": {"relative_path": "silver/quote/stock_daily/trade_date={trade_date}/part-000.parquet"},
        "prod_pg": {"schema": "core_serving", "relation": "equity_daily_bar"},
    },
    "stock_weekly": {
        "dg": {"relative_path": "silver/quote/stock_weekly/week_end={week_end}/part-000.parquet"},
        "prod_pg": {"schema": "core_serving", "relation": "stk_period_bar_adj", "filters": {"freq": "week"}},
    },
    "stock_monthly": {
        "dg": {"relative_path": "silver/quote/stock_monthly/month={month}/part-000.parquet"},
        "prod_pg": {"schema": "core_serving", "relation": "stk_period_bar_adj", "filters": {"freq": "month"}},
    },
    "index_daily": {
        "dg": {"relative_path": "silver/index_daily/trade_date={trade_date}/part-000.parquet"},
        "prod_pg": {"schema": "core_serving", "relation": "index_daily_serving"},
    },
    "index_weekly": {
        "dg": {"relative_path": "silver/index_weekly/full/part-000.parquet"},
        "prod_pg": {"schema": "core_serving", "relation": "index_weekly_serving"},
    },
    "index_monthly": {
        "dg": {"relative_path": "silver/index_monthly/full/part-000.parquet"},
        "prod_pg": {"schema": "core_serving", "relation": "index_monthly_serving"},
    },
}

MARKET_DATASETS = {
    ("stock", "day"): "stock_daily",
    ("stock", "week"): "stock_weekly",
    ("stock", "month"): "stock_monthly",
    ("index", "day"): "index_daily",
    ("index", "week"): "index_weekly",
    ("index", "month"): "index_monthly",
}

for _frequency in (1, 5, 15, 30, 60, 90, 120):
    _period = f"{_frequency}m"
    _stock_id = f"stock_mins_{_period}"
    _index_id = f"index_mins_{_period}"
    MARKET_DATASETS["stock", _period] = _stock_id
    MARKET_DATASETS["index", _period] = _index_id
    _index_dg = {
        "relative_path": "gold/quote/index_mins/freq={freq}/trade_date={trade_date}/part-000.parquet",
        "partitions": {"freq": _frequency},
    }
    if _frequency in (90, 120):
        DATASET_LOCATIONS[_stock_id] = {"dg": None, "prod_pg": None}
        DATASET_LOCATIONS[_index_id] = {"dg": _index_dg, "prod_pg": None}
        continue
    DATASET_LOCATIONS[_stock_id] = {
        "dg": {
            "relative_path": "silver/quote/stk_mins/freq={freq}/trade_date={trade_date}/part-000.parquet",
            "partitions": {"freq": _frequency},
        },
        "prod_pg": {"schema": "core_serving", "relation": "equity_minute_bar", "filters": {"freq": _frequency}},
    }
    DATASET_LOCATIONS[_index_id] = {
        "dg": _index_dg,
        "prod_pg": {
            "schema": "core_serving", "relation": "index_minute_bar", "filters": {"freq": f"{_frequency}min"},
        },
    }
