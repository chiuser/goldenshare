from __future__ import annotations

from sqlalchemy.orm import Session

from src.services.sync.sync_adj_factor_service import SyncAdjFactorService
from src.services.sync.sync_block_trade_service import SyncBlockTradeService
from src.services.sync.sync_daily_basic_service import SyncDailyBasicService
from src.services.sync.sync_dividend_service import SyncDividendService
from src.services.sync.sync_equity_daily_service import SyncEquityDailyService
from src.services.sync.sync_fund_daily_service import SyncFundDailyService
from src.services.sync.sync_holdernumber_service import SyncHolderNumberService
from src.services.sync.sync_index_daily_service import SyncIndexDailyService
from src.services.sync.sync_limit_list_service import SyncLimitListService
from src.services.sync.sync_moneyflow_service import SyncMoneyflowService
from src.services.sync.sync_stock_basic_service import SyncStockBasicService
from src.services.sync.sync_top_list_service import SyncTopListService
from src.services.sync.sync_trade_calendar_service import SyncTradeCalendarService


SYNC_SERVICE_REGISTRY = {
    "stock_basic": SyncStockBasicService,
    "trade_cal": SyncTradeCalendarService,
    "daily": SyncEquityDailyService,
    "adj_factor": SyncAdjFactorService,
    "daily_basic": SyncDailyBasicService,
    "moneyflow": SyncMoneyflowService,
    "top_list": SyncTopListService,
    "block_trade": SyncBlockTradeService,
    "dividend": SyncDividendService,
    "fund_daily": SyncFundDailyService,
    "index_daily": SyncIndexDailyService,
    "stk_holdernumber": SyncHolderNumberService,
    "limit_list_d": SyncLimitListService,
}


def build_sync_service(resource: str, session: Session):
    service_cls = SYNC_SERVICE_REGISTRY[resource]
    return service_cls(session)
