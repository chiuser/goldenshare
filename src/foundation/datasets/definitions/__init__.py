from __future__ import annotations

from src.foundation.datasets.definitions._builder import build_definitions
from src.foundation.datasets.definitions.market_equity import DATASET_ROWS as MARKET_EQUITY_ROWS
from src.foundation.datasets.definitions.market_fund import DATASET_ROWS as MARKET_FUND_ROWS
from src.foundation.datasets.definitions.index_series import DATASET_ROWS as INDEX_SERIES_ROWS
from src.foundation.datasets.definitions.board_hotspot import DATASET_ROWS as BOARD_HOTSPOT_ROWS
from src.foundation.datasets.definitions.moneyflow import DATASET_ROWS as MONEYFLOW_ROWS
from src.foundation.datasets.definitions.reference_master import DATASET_ROWS as REFERENCE_MASTER_ROWS
from src.foundation.datasets.definitions.low_frequency import DATASET_ROWS as LOW_FREQUENCY_ROWS
from src.foundation.datasets.definitions.news import DATASET_ROWS as NEWS_ROWS

ALL_DATASET_ROWS = (
    *MARKET_EQUITY_ROWS,
    *MARKET_FUND_ROWS,
    *INDEX_SERIES_ROWS,
    *BOARD_HOTSPOT_ROWS,
    *MONEYFLOW_ROWS,
    *REFERENCE_MASTER_ROWS,
    *LOW_FREQUENCY_ROWS,
    *NEWS_ROWS,
)


def list_defined_datasets():
    return tuple(sorted(build_definitions(ALL_DATASET_ROWS), key=lambda item: item.dataset_key))
