"""Bounded scan orchestration; a complete scan still requires final acceptance checks."""
import asyncio
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Callable, Protocol
from uuid import UUID

from sqlalchemy import select

from src.biz.models.wealth.trading_assistant.recovery import ValidationCandidate, ValidationCheckpoint

from .execution_policy import Deadline, TradingAssistantExecutionPolicyV1
from src.biz.queries.wealth.market.trading_assistant.effective_ledger import ReplacementFact
from .transaction_boundary import TransactionRunner
from .validation import CashValidation, QuantityValidation, InvalidLedger
from .validation_checkpoints import ValidationCheckpoints
from .validation_completion import read_completion
from .validation_pages import ValidationPageReader
from .write_protocol import AttemptState
from .market_facts import apply_sql_budget


@dataclass(frozen=True, slots=True)
class StockOpening:
    stock: str
    exchange: str
    state: QuantityValidation


class ValidationChange(Protocol):
    account_id: UUID
    affected_stocks: tuple[str, ...]
    replacement: ReplacementFact | None
    replaced_ledger_id: UUID | None


@dataclass(frozen=True, slots=True)
class LedgerValidationInput:
    owner_id: int
    candidate_id: UUID
    run_id: UUID
    fact_version: int
    basis_digest: bytes
    change: ValidationChange
    cash: CashValidation
    stocks: tuple[StockOpening, ...]

    def __post_init__(self):
        if tuple(s.stock for s in self.stocks) != self.change.affected_stocks:
            raise ValueError("Validation must cover exactly the affected stocks")
        if self.cash.checked_rows or self.cash.current_day is not None or self.cash.day_delta_cents:
            raise ValueError("Fresh validation requires the initialization cash state")
        if any(s.state.current_day is not None or s.state.checked_rows or s.state.bought or s.state.sold
               for s in self.stocks):
            raise ValueError("Fresh validation requires initial stock states")
        if type(self.fact_version) is not int or self.fact_version < 1 or len(self.basis_digest) != 32:
            raise ValueError("Invalid fixed validation basis")


class LedgerValidator:
    def __init__(self, transactions: TransactionRunner, reader: ValidationPageReader,
                 checkpoints: ValidationCheckpoints, policy: TradingAssistantExecutionPolicyV1,
                 now: Callable[[], datetime]):
        self.transactions, self.reader, self.checkpoints, self.policy, self.now = (
            transactions, reader, checkpoints, policy, now)

    async def validate(self, job: LedgerValidationInput, *, deadline: Deadline,
                       cancelled: Callable[[], bool], execution: AttemptState | None = None,
                       executor_id: str | None = None):
        # Ledger edits cover old/new stock; initialization covers all affected stocks.
        stages = [(None, None, job.cash)] + [(s.stock, s.exchange, s.state) for s in job.stocks]
        for stock, exchange, initial in stages:
            state, after = initial, None
            if cancelled():
                raise asyncio.CancelledError()

            def restore(session):
                apply_sql_budget(session, deadline, self.policy)
                previous = session.scalar(select(ValidationCheckpoint).join(ValidationCandidate,
                    ValidationCandidate.candidate_id == ValidationCheckpoint.candidate_id).where(
                        ValidationCandidate.owner_id == job.owner_id,
                        ValidationCandidate.account_id == job.change.account_id,
                        ValidationCheckpoint.candidate_id == job.candidate_id,
                        ValidationCheckpoint.validation_run_id == job.run_id,
                        ValidationCheckpoint.stage == ("CASH" if stock is None else "QUANTITY"),
                        ValidationCheckpoint.stock_key == (stock or ""))
                    .order_by(ValidationCheckpoint.checked_row_count.desc(),
                        ValidationCheckpoint.completed_range["complete"].as_boolean().desc()).limit(1))
                return self.checkpoints.restore(previous,basis_digest=job.basis_digest) if previous else None

            previous = await self.transactions.run(restore,deadline=deadline,write=False)
            if previous is not None:
                if previous.complete:
                    continue
                state, after = previous.state, previous.after
            while True:
                if cancelled():
                    raise asyncio.CancelledError()
                batch = Deadline.after_ms(deadline.bounded_ms(self.policy.batch_budget_ms), deadline.clock)

                def read(session):
                    return self.reader.read(session, owner_id=job.owner_id, account_id=job.change.account_id,
                        fact_version=job.fact_version, state=state, after=after, stock=stock, exchange=exchange,
                        replaced_ledger_id=job.change.replaced_ledger_id, replacement=job.change.replacement,
                        deadline=batch)

                try:
                    page = await self.transactions.run(read, deadline=batch, write=False)
                except InvalidLedger as error:
                    raise replace(error, ts_code=stock) from error
                if cancelled():
                    raise asyncio.CancelledError()

                def store(session):
                    checkpoint = self.checkpoints.store(session, owner_id=job.owner_id,
                        candidate_id=job.candidate_id, run_id=job.run_id, stock=stock,
                        basis_digest=job.basis_digest, before=after, page=page, now=self.now(),
                        deadline=batch, execution=execution, executor_id=executor_id)
                    return checkpoint.checkpoint_id

                await self.transactions.run(store, deadline=batch, write=True)
                state, after = page.state, page.after
                if page.complete:
                    break
        if cancelled():
            raise asyncio.CancelledError()
        return await self.transactions.run(lambda session: read_completion(session,
            owner_id=job.owner_id, account_id=job.change.account_id, candidate_id=job.candidate_id,
            run_id=job.run_id, basis_digest=job.basis_digest, affected_stocks=job.change.affected_stocks,
            checkpoints=self.checkpoints, policy=self.policy, deadline=deadline), deadline=deadline, write=False)
