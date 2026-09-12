"""Durable cash-day summaries, one bounded page per transaction (§4.6.2).

No DayResult is created: cash dates include weekends. The later cash continuation
and snapshot stages consume the completed totals, not a partly reduced page.
"""
from dataclasses import asdict
from datetime import date
from hashlib import sha256
from uuid import UUID

from sqlalchemy import func, select

from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch
from src.biz.queries.wealth.market.trading_assistant.calculation_cash import cash_day_page
from .calculation.cash_day import CashDayTotals, add_cash_movement
from .calculation_inputs import CalculationInputs, CalculationInputMismatch
from .persistence_values import numeric_cents


class CashDayBatches:
    def __init__(self, execution):
        self.execution = execution
        self.inputs = CalculationInputs(execution)
        self.policy = execution.policy

    @staticmethod
    def _restore(checkpoint):
        if checkpoint is None:
            return CashDayTotals()
        values = checkpoint.accumulator
        if values.keys() != asdict(CashDayTotals()).keys():
            raise CalculationInputMismatch("Cash accumulator fields changed")
        return CashDayTotals(**{key: int(value) for key, value in values.items()})

    def _latest(self, session, lease, generation_id, business_date):
        return session.scalar(select(CalculationBatch).where(
            CalculationBatch.account_id == lease.account_id, CalculationBatch.generation_id == generation_id,
            CalculationBatch.trade_date == business_date, CalculationBatch.stage == "ACCOUNT_CASH",
            CalculationBatch.stock_key == "").order_by(CalculationBatch.page_key.desc()).limit(1))

    def reduce_page(self, session, lease, *, generation_id, business_date, deadline):
        if type(business_date) is not date:
            raise ValueError("Invalid cash business date")
        with self.execution.batch(session, lease, deadline=deadline) as account:
            generation = self.inputs._generation(session, lease, account, generation_id, business_date,
                                                  stages=("PREPARING", "CALCULATING"))
            previous = self._latest(session, lease, generation_id, business_date)
            totals = self._restore(previous)
            if previous and previous.cursor["done"]:
                return True
            after = UUID(previous.cursor["afterLedger"]) if previous and previous.cursor["afterLedger"] else None
            rows = session.execute(cash_day_page(owner_id=account.owner_id, account_id=lease.account_id,
                fact_version=generation.fact_version, business_date=business_date,
                limit=self.policy.page_rows, policy=self.policy, after=after)).mappings().all()
            if rows and business_date < account.initialized_on:
                raise CalculationInputMismatch("Recorded movements predate the account cash baseline")
            evidence = [{key: str(value) for key, value in row.items()} for row in rows]
            self.inputs._encoded(evidence)
            for row in rows:
                deadline.remaining_ms()
                totals = add_cash_movement(totals, kind=row["kind"], direction=row["direction"],
                                           net_cents=numeric_cents(row["net_cash_change"]))
            cursor = {"afterLedger": str(rows[-1]["ledger_id"]) if rows else str(after) if after else None,
                      "done": not rows}
            accumulator = {key: str(value) for key, value in asdict(totals).items()}
            digest = sha256(self.inputs._encoded({"previous": previous.input_digest.hex() if previous else None,
                "rows": evidence, "cursor": cursor, "accumulator": accumulator})).digest()
            now = session.scalar(select(func.clock_timestamp()))
            checkpoint = CalculationBatch(account_id=lease.account_id, generation_id=generation_id,
                trade_date=business_date, stage="ACCOUNT_CASH", stock_key="",
                page_key=f"{int(previous.page_key) + 1 if previous else 1:020d}", cursor=cursor,
                accumulator=accumulator, input_digest=digest, row_count=len(rows), completed_at=now)
            session.add(checkpoint)
            session.flush()
            session.refresh(checkpoint)
            if (checkpoint.cursor, checkpoint.accumulator, checkpoint.input_digest) != (cursor, accumulator, digest):
                raise CalculationInputMismatch("Cash checkpoint read-back mismatch")
            generation.last_business_updated_at = now
            return cursor["done"]

    def completed_totals(self, session, lease, *, generation_id, business_date, deadline):
        with self.execution.batch(session, lease, deadline=deadline) as account:
            self.inputs._generation(session, lease, account, generation_id, business_date,
                                    stages=("PREPARING", "CALCULATING"))
            checkpoint = self._latest(session, lease, generation_id, business_date)
            if checkpoint is None or not checkpoint.cursor["done"]:
                raise CalculationInputMismatch("Cash day still has unprocessed source pages")
            return self._restore(checkpoint)

    def verify_page(self, session, lease, *, generation_id, business_date, page_key, deadline):
        """Read back one page against actual effective facts before final sealing.

        The caller must visit every page, including the final empty page; checking
        only the last accumulator does not prove that the earlier pages match.
        """
        with self.execution.batch(session, lease, deadline=deadline) as account:
            generation = self.inputs._generation(session, lease, account, generation_id, business_date,
                                                  stages=("PREPARING", "CALCULATING"))
            checkpoint = session.get(CalculationBatch,
                (lease.account_id, generation_id, business_date, "ACCOUNT_CASH", "", page_key))
            if checkpoint is None or not 0 <= checkpoint.row_count <= self.policy.page_rows:
                raise CalculationInputMismatch("Missing or oversized cash page")
            previous = session.scalar(select(CalculationBatch).where(
                CalculationBatch.account_id == lease.account_id, CalculationBatch.generation_id == generation_id,
                CalculationBatch.trade_date == business_date, CalculationBatch.stage == "ACCOUNT_CASH",
                CalculationBatch.stock_key == "", CalculationBatch.page_key < page_key)
                .order_by(CalculationBatch.page_key.desc()).limit(1))
            if page_key != f"{int(previous.page_key) + 1 if previous else 1:020d}" or (
                    previous and previous.cursor["done"]):
                raise CalculationInputMismatch("Cash checkpoint chain is not contiguous")
            after = UUID(previous.cursor["afterLedger"]) if previous and previous.cursor["afterLedger"] else None
            rows = session.execute(cash_day_page(owner_id=account.owner_id, account_id=lease.account_id,
                fact_version=generation.fact_version, business_date=business_date,
                limit=checkpoint.row_count or 1, policy=self.policy, after=after)).mappings().all()
            if len(rows) != checkpoint.row_count or (rows and business_date < account.initialized_on):
                raise CalculationInputMismatch("Cash source page count or baseline changed")
            totals = self._restore(previous)
            evidence = [{key: str(value) for key, value in row.items()} for row in rows]
            for row in rows:
                deadline.remaining_ms()
                totals = add_cash_movement(totals, kind=row["kind"], direction=row["direction"],
                                           net_cents=numeric_cents(row["net_cash_change"]))
            cursor = {"afterLedger": str(rows[-1]["ledger_id"]) if rows else str(after) if after else None,
                      "done": not rows}
            accumulator = {key: str(value) for key, value in asdict(totals).items()}
            digest = sha256(self.inputs._encoded({"previous": previous.input_digest.hex() if previous else None,
                "rows": evidence, "cursor": cursor, "accumulator": accumulator})).digest()
            if (checkpoint.cursor, checkpoint.accumulator, checkpoint.input_digest) != (cursor, accumulator, digest):
                raise CalculationInputMismatch("Cash page no longer matches its actual source facts")
            identity = (lease.account_id, generation_id, business_date, "ACCOUNT_CASH_CHECK", "", page_key)
            checked = session.get(CalculationBatch, identity)
            if checked is None:
                now = session.scalar(select(func.clock_timestamp()))
                session.add(CalculationBatch(account_id=lease.account_id, generation_id=generation_id,
                    trade_date=business_date, stage="ACCOUNT_CASH_CHECK", stock_key="", page_key=page_key,
                    cursor=cursor, accumulator={}, input_digest=digest, row_count=len(rows), completed_at=now))
                generation.last_business_updated_at = now
            elif (checked.input_digest, checked.row_count, checked.cursor) != (digest, len(rows), cursor):
                raise CalculationInputMismatch("Persisted cash verification differs from the source page")
            return totals
