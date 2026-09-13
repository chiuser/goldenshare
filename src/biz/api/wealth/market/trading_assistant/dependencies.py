"""Application-injected accounting capabilities, without importing App."""
from dataclasses import dataclass
from typing import Callable
from datetime import datetime
from uuid import UUID
from typing import Literal, TypeVar
from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.trading_assistant.accounts import AccountQueries
from src.biz.queries.wealth.market.trading_assistant.entry_context import EntryContextQuery
from src.biz.queries.wealth.market.trading_assistant.write_recovery import WriteRecoveryQueries
from src.biz.queries.wealth.market.trading_assistant.record_detail import RecordDetailQuery
from src.biz.queries.wealth.market.trading_assistant.calculation_status import CalculationStatusQuery
from src.biz.queries.wealth.market.trading_assistant.read_context import CurrentReadContextQuery, OwnedReadContext
from src.biz.services.wealth.market.trading_assistant.account_commands import AccountCommandService
from src.biz.services.wealth.market.trading_assistant.calculation_retries import CalculationRetryService
from src.biz.services.wealth.market.trading_assistant.ledger_commands import LedgerCommandService
from src.biz.services.wealth.market.trading_assistant.ledger_previews import LedgerPreviewService
from src.biz.services.wealth.market.trading_assistant.initialization_preview import InitializationPreviewService
from src.biz.services.wealth.market.trading_assistant.execution_policy import TradingAssistantExecutionPolicyV1, Deadline
from src.biz.services.wealth.market.trading_assistant.transaction_boundary import TransactionRunner
from src.biz.services.wealth.market.trading_assistant.market_facts import apply_sql_budget

T = TypeVar("T")


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
    calculation_status: CalculationStatusQuery
    calculation_retries: CalculationRetryService
    read_context: CurrentReadContextQuery

    async def read(self, query):
        deadline = Deadline.after_ms(self.policy.read_request_budget_ms)
        return await self.transactions.run(lambda session:query(session, deadline), deadline=deadline, write=False)

    async def read_current(self, query: Callable[[Session, Deadline, OwnedReadContext], T], *,
                           owner_id: int, account_mode: Literal["ALL", "SINGLE"], account_id: UUID | None,
                           resolve_target_through: Callable[[Session, Deadline], datetime],
                           context_token: str | None = None) -> T:
        """Internal only: resolve trusted cutoff and query in one read snapshot.

        The resolver is server code, never a timestamp deserialized from a token.
        Neither callback may open a second session or enqueue calculation work.
        """
        def work(session, deadline):
            apply_sql_budget(session, deadline, self.policy)
            through = resolve_target_through(session, deadline)
            basis = self.read_context.capture(session, owner_id=owner_id, account_mode=account_mode,
                account_id=account_id, target_through=through, deadline=deadline, context_token=context_token)
            return query(session, deadline, basis)
        return await self.read(work)
