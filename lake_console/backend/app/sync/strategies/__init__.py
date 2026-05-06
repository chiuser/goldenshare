from lake_console.backend.app.sync.strategies.daily import DailyStrategy
from lake_console.backend.app.sync.strategies.index_basic import IndexBasicStrategy
from lake_console.backend.app.sync.strategies.moneyflow import MoneyflowStrategy
from lake_console.backend.app.sync.strategies.prod_db_trade_date import (
    AdjFactorStrategy,
    DailyBasicStrategy,
    IndexDailyBasicStrategy,
    IndexDailyStrategy,
)
from lake_console.backend.app.sync.strategies.prod_raw_current_snapshots import (
    ETFBasicStrategy,
    ETFIndexStrategy,
    THSIndexStrategy,
    THSMemberStrategy,
)

STRATEGY_CLASSES = {
    AdjFactorStrategy.dataset_key: AdjFactorStrategy,
    DailyBasicStrategy.dataset_key: DailyBasicStrategy,
    DailyStrategy.dataset_key: DailyStrategy,
    ETFBasicStrategy.dataset_key: ETFBasicStrategy,
    ETFIndexStrategy.dataset_key: ETFIndexStrategy,
    IndexBasicStrategy.dataset_key: IndexBasicStrategy,
    IndexDailyBasicStrategy.dataset_key: IndexDailyBasicStrategy,
    IndexDailyStrategy.dataset_key: IndexDailyStrategy,
    MoneyflowStrategy.dataset_key: MoneyflowStrategy,
    THSIndexStrategy.dataset_key: THSIndexStrategy,
    THSMemberStrategy.dataset_key: THSMemberStrategy,
}

__all__ = [
    "STRATEGY_CLASSES",
    "AdjFactorStrategy",
    "DailyBasicStrategy",
    "DailyStrategy",
    "ETFBasicStrategy",
    "ETFIndexStrategy",
    "IndexBasicStrategy",
    "IndexDailyBasicStrategy",
    "IndexDailyStrategy",
    "MoneyflowStrategy",
    "THSIndexStrategy",
    "THSMemberStrategy",
]
