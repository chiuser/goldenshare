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
from src.biz.queries.wealth.market.trading_assistant.record_lists import RecordListsQuery
from src.biz.queries.wealth.market.trading_assistant.record_summary import RecordSummaryQuery
from src.biz.queries.wealth.market.trading_assistant.closed_records import ClosedRecordsQuery
from src.biz.queries.wealth.market.trading_assistant.return_day_detail import ReturnDayDetailQuery
from src.biz.queries.wealth.market.trading_assistant.return_curve import ReturnCurveQuery
from src.biz.queries.wealth.market.trading_assistant.return_calendar import ReturnCalendarQuery
from src.biz.schemas.wealth.market.trading_assistant.scopes import AccountReadQuery, RoundRecordsQuery
from src.biz.queries.wealth.market.trading_assistant.calculation_status import CalculationStatusQuery
from src.biz.queries.wealth.market.trading_assistant.read_context import CurrentReadContextQuery, OwnedReadContext
from src.biz.queries.wealth.market.trading_assistant.positions import PositionsQuery
from src.biz.queries.wealth.market.trading_assistant.positions_analysis import PositionsAnalysisQuery
from src.biz.queries.wealth.market.trading_assistant.positions_cutoff import resolve_positions_cutoff
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
    positions: PositionsQuery
    positions_analysis: PositionsAnalysisQuery
    record_lists: RecordListsQuery
    record_summary: RecordSummaryQuery
    closed_records: ClosedRecordsQuery
    return_day_detail: ReturnDayDetailQuery
    return_curve: ReturnCurveQuery
    return_calendar: ReturnCalendarQuery

    async def read_return_calendar(self, *, owner_id, query):
        def execute(session, *, basis, cutoff, deadline, **unused):
            return self.return_calendar.read(session, owner_id=owner_id, basis=basis,
                query=query, cutoff=cutoff, deadline=deadline)
        return await self._read_holdings(owner_id=owner_id, query=query, read=execute)

    async def read_return_curve(self, *, owner_id, query):
        def execute(session, *, basis, cutoff, deadline, **unused):
            return self.return_curve.read(session, owner_id=owner_id, basis=basis,
                query=query, cutoff=cutoff, deadline=deadline)
        return await self._read_holdings(owner_id=owner_id, query=query, read=execute)

    async def read_return_day(self, *, owner_id, query, day):
        return await self._read_holdings(owner_id=owner_id, query=query,
            read=lambda session, **kwargs: self.return_day_detail.read(session, **kwargs, day=day))

    async def read_closed_records(self, *, owner_id, query):
        selection = AccountReadQuery(accountMode="SINGLE", accountId=query.accountId, readContext=query.readContext) if isinstance(query, RoundRecordsQuery) else query
        def execute(session, *, basis, deadline, **unused):
            return self.closed_records.read(session, owner_id=owner_id, basis=basis, query=query, deadline=deadline)
        return await self._read_holdings(owner_id=owner_id, query=selection, read=execute)

    async def read_record_detail(self, *, owner_id, record_id, kind, cursor=None, limit=20, context_token=None):
        def work(session, deadline):
            account = self.record_detail.owned_account(session, owner_id=owner_id,
                record_id=record_id, kind=kind, deadline=deadline)
            cutoff = resolve_positions_cutoff(session, market=self.entry_context.market, deadline=deadline)
            basis = self.read_context.capture(session, owner_id=owner_id, account_mode="SINGLE",
                account_id=account.account_id, target_through=cutoff.through, deadline=deadline, context_token=context_token)
            return self.record_detail.read(session, owner_id=owner_id, account=account, basis=basis,
                record_id=record_id, kind=kind, deadline=deadline, cursor=cursor, limit=limit)
        return await self.read(work)

    async def read_records_summary(self, *, owner_id, query):
        def execute(session, *, basis, deadline, **unused):
            return self.record_summary.read(session, owner_id=owner_id, basis=basis, query=query, deadline=deadline)
        return await self._read_holdings(owner_id=owner_id, query=query, read=execute)

    async def read_records(self, *, owner_id, query, kind, grouped=False):
        def execute(session, *, basis, deadline, **unused):
            return self.record_lists.read(session, owner_id=owner_id, basis=basis,
                query=query, kind=kind, grouped=grouped, deadline=deadline)
        return await self._read_holdings(owner_id=owner_id, query=query, read=execute)

    async def read_positions(self, *, owner_id, query, stock_code=None):
        return await self._read_holdings(owner_id=owner_id, query=query,
            read=lambda session, **kwargs: self.positions.read(session, **kwargs, stock_code=stock_code))

    async def read_positions_analysis(self, *, owner_id, query):
        return await self._read_holdings(owner_id=owner_id, query=query, read=self.positions_analysis.read)

    async def _read_holdings(self, *, owner_id, query, read):
        cutoff = None

        def resolve(session, deadline):
            nonlocal cutoff
            cutoff = resolve_positions_cutoff(session, market=self.entry_context.market, deadline=deadline)
            return cutoff.through

        def execute(session, deadline, basis):
            return read(session, owner_id=owner_id, account_mode=query.accountMode,
                basis=basis, cutoff=cutoff, deadline=deadline)

        return await self.read_current(execute, owner_id=owner_id, account_mode=query.accountMode,
            account_id=UUID(query.accountId) if query.accountId else None,
            resolve_target_through=resolve, context_token=query.readContext)

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
