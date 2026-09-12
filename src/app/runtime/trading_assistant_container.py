"""Composition of the approved M2 accounting services; no implicit connections."""
from src.biz.api.wealth.market.trading_assistant.dependencies import TradingAssistantDependencies
from src.biz.queries.wealth.market.trading_assistant.accounts import AccountQueries
from src.biz.queries.wealth.market.trading_assistant.entry_context import EntryContextQuery
from src.biz.queries.wealth.market.trading_assistant.write_recovery import WriteRecoveryQueries
from src.biz.queries.wealth.market.trading_assistant.record_detail import RecordDetailQuery
from src.biz.queries.wealth.market.trading_assistant.calculation_status import CalculationStatusQuery
from src.biz.services.wealth.market.trading_assistant.account_commands import AccountCommandService
from src.biz.services.wealth.market.trading_assistant.calculation_retries import CalculationRetryService
from src.biz.services.wealth.market.trading_assistant.ledger_commands import LedgerCommandService
from src.biz.services.wealth.market.trading_assistant.ledger_previews import LedgerPreviewService
from src.biz.services.wealth.market.trading_assistant.initialization_preview import InitializationPreviewService
from src.biz.services.wealth.market.trading_assistant.market_facts import MarketFactsReader
from .trading_assistant_transactions import TradingAssistantTransactions


def build_trading_assistant_dependencies(engine, *, policy, now, executor_id):
    transactions = TradingAssistantTransactions(engine)
    market = MarketFactsReader(policy)
    return TradingAssistantDependencies(transactions, policy, now,
        AccountCommandService(transactions, market, policy, now, executor_id=executor_id),
        LedgerCommandService(transactions, market, policy, now, executor_id=executor_id),
        AccountQueries(policy, market), EntryContextQuery(policy, market), WriteRecoveryQueries(policy),
        LedgerPreviewService(transactions, market, policy, now), InitializationPreviewService(transactions, market, policy, now),
        RecordDetailQuery(policy, market), CalculationStatusQuery(policy),
        CalculationRetryService(transactions, policy, now, executor_id=executor_id))
