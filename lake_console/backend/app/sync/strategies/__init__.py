from lake_console.backend.app.sync.strategies.daily import DailyStrategy
from lake_console.backend.app.sync.strategies.index_basic import IndexBasicStrategy
from lake_console.backend.app.sync.strategies.moneyflow import MoneyflowStrategy
from lake_console.backend.app.sync.strategies.prod_raw_current_snapshots import (
    ETFBasicStrategy,
    ETFIndexStrategy,
    THSIndexStrategy,
    THSMemberStrategy,
)

STRATEGY_CLASSES = {
    DailyStrategy.dataset_key: DailyStrategy,
    ETFBasicStrategy.dataset_key: ETFBasicStrategy,
    ETFIndexStrategy.dataset_key: ETFIndexStrategy,
    IndexBasicStrategy.dataset_key: IndexBasicStrategy,
    MoneyflowStrategy.dataset_key: MoneyflowStrategy,
    THSIndexStrategy.dataset_key: THSIndexStrategy,
    THSMemberStrategy.dataset_key: THSMemberStrategy,
}

__all__ = [
    "STRATEGY_CLASSES",
    "DailyStrategy",
    "ETFBasicStrategy",
    "ETFIndexStrategy",
    "IndexBasicStrategy",
    "MoneyflowStrategy",
    "THSIndexStrategy",
    "THSMemberStrategy",
]
