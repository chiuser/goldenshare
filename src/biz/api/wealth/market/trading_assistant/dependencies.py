"""Application-injected accounting capabilities, without importing App."""
from dataclasses import dataclass
from typing import Callable
from datetime import datetime

from src.biz.queries.wealth.market.trading_assistant.accounts import AccountQueries
from src.biz.queries.wealth.market.trading_assistant.entry_context import EntryContextQuery
from src.biz.queries.wealth.market.trading_assistant.write_recovery import WriteRecoveryQueries
from src.biz.queries.wealth.market.trading_assistant.record_detail import RecordDetailQuery
from src.biz.services.wealth.market.trading_assistant.account_commands import AccountCommandService
from src.biz.services.wealth.market.trading_assistant.ledger_commands import LedgerCommandService
from src.biz.services.wealth.market.trading_assistant.ledger_previews import LedgerPreviewService
from src.biz.services.wealth.market.trading_assistant.initialization_preview import InitializationPreviewService
from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1, Deadline
from src.biz.services.wealth.market.trading_assistant.transaction_boundary import TransactionRunner


@dataclass(frozen=True)
class TradingAssistantDependencies:
    transactions: TransactionRunner
    policy: TradingAssistantExecutionPolicyV1
    now: Callable[[], datetime]
    accounts: AccountCommandService
    ledger: LedgerCommandService
    account_queries: AccountQueries
    entry_context: EntryContextQuery
    recovery: WriteRecoveryQueries
    previews: LedgerPreviewService
    initialization_preview: InitializationPreviewService
    record_detail: RecordDetailQuery

    async def read(self, query):
        deadline = Deadline.after_ms(self.policy.read_request_budget_ms)
        return await self.transactions.run(lambda session:query(session, deadline), deadline=deadline, write=False)
