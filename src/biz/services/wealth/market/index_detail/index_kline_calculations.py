"""Calculation lists for the existing index K-line requests."""

INDEX_MA_PERIODS = (5, 10, 20, 30, 60, 90, 250)
INDEX_BOLL_PERIOD = 20
_BOLL_PARAMETERS = {"period": INDEX_BOLL_PERIOD, "multiplier": 2}
_MACD_PARAMETERS = {"fast": 12, "slow": 26, "signal": 9}
_KDJ_PARAMETERS = {"window": 9, "k_period": 3, "d_period": 3}
INDEX_BOLL_KEY = ("boll", tuple(sorted(_BOLL_PARAMETERS.items())))
INDEX_MACD_KEY = ("macd", tuple(sorted(_MACD_PARAMETERS.items())))
INDEX_KDJ_KEY = ("kdj", tuple(sorted(_KDJ_PARAMETERS.items())))
INDEX_COMMON_CALCULATIONS = (
    *({"calculation_id": "ma", "parameters": {"period": period}} for period in INDEX_MA_PERIODS),
    {"calculation_id": "boll", "parameters": _BOLL_PARAMETERS},
    {"calculation_id": "macd", "parameters": _MACD_PARAMETERS},
    {"calculation_id": "kdj", "parameters": _KDJ_PARAMETERS},
)


def index_daily_calculations(ts_code: str, *, include_price_and_nine_turn: bool):
    return (
        *INDEX_COMMON_CALCULATIONS,
        *(({"calculation_id": "price", "parameters": {}}, {"calculation_id": "nineturn", "parameters": {}})
          if include_price_and_nine_turn else ()),
        *(({"calculation_id": "trend_channel", "parameters": {}},) if ts_code == "000001.SH" else ()),
    )


def index_period_calculations():
    return ({"calculation_id": "price", "parameters": {}}, *INDEX_COMMON_CALCULATIONS)
