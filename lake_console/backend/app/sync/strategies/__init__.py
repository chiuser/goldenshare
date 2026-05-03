from lake_console.backend.app.sync.strategies.daily import DailyStrategy
from lake_console.backend.app.sync.strategies.index_basic import IndexBasicStrategy
from lake_console.backend.app.sync.strategies.moneyflow import MoneyflowStrategy

STRATEGY_CLASSES = {
    DailyStrategy.dataset_key: DailyStrategy,
    IndexBasicStrategy.dataset_key: IndexBasicStrategy,
    MoneyflowStrategy.dataset_key: MoneyflowStrategy,
}

__all__ = ["STRATEGY_CLASSES", "DailyStrategy", "IndexBasicStrategy", "MoneyflowStrategy"]
