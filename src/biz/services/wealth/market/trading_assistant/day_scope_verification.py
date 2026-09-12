"""Prove source stock coverage and each opening without loading the whole day."""
from dataclasses import asdict
from hashlib import sha256

from sqlalchemy import func, select

from src.biz.models.wealth.trading_assistant.calculation import DayResult, PositionState
from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch
from src.biz.queries.wealth.market.trading_assistant.calculation_stocks import stock_day_page
from .calculation_inputs import CalculationInputMismatch
from .stock_day_batches import StockDayBatches
from .stock_openings import read_stock_opening


class DayScopeVerification:
    def __init__(self, execution):
        self.execution = execution
        self.stocks = StockDayBatches(execution)

    def verify_next(self, session, lease, *, generation_id, day_result_id, previous_day_result_id, deadline):
        # One stock has several independent source reads; keep this unit to one
        # stock within the existing two-second budget, rather than 500 N+1 reads.
        with self.execution.batch(session, lease, deadline=deadline) as account:
            day, generation = self.stocks._day(session, lease, account, generation_id, day_result_id)
            previous = self.stocks._latest(session, lease, generation_id, day.trade_date, "", "DAY_SCOPE_CHECK")
            predecessor = session.get(DayResult, previous_day_result_id) if previous_day_result_id else None
            binding = {"previousDayId": str(previous_day_result_id) if previous_day_result_id else None,
                       "previousDigest": predecessor.input_digest.hex() if predecessor else None}
            if previous and previous.accumulator["binding"] != binding:
                raise CalculationInputMismatch("Stock scope predecessor changed")
            if previous and previous.cursor["done"]:
                return True
            after = previous.cursor["afterStock"] if previous else None
            source = session.scalars(stock_day_page(owner_id=account.owner_id, account_id=lease.account_id,
                initialization_id=generation.initialization_id, fact_version=generation.fact_version,
                trade_date=day.trade_date, previous_day_result_id=previous_day_result_id,
                limit=1, policy=self.execution.policy, after=after)).all()
            stored_query = select(PositionState).where(PositionState.account_id == lease.account_id,
                PositionState.day_result_id == day_result_id)
            if after:
                stored_query = stored_query.where(PositionState.ts_code > after)
            stored = session.scalars(stored_query.order_by(PositionState.ts_code, PositionState.round_id).limit(1)
                                     .execution_options(populate_existing=True)).all()
            if [row.ts_code for row in stored] != source:
                raise CalculationInputMismatch("Day positions omit or add a source stock")
            evidence = None
            if source:
                stock = source[0]
                opening = read_stock_opening(session, account=account, generation=generation,
                    trade_date=day.trade_date, stock=stock, previous_day_result_id=previous_day_result_id,
                    policy=self.execution.policy, deadline=deadline)
                summary = self.stocks._latest(session, lease, generation_id, day.trade_date, stock, "STOCK_SUMMARY")
                if (summary is None or not summary.cursor["done"] or summary.accumulator["opening"] != {
                    key: str(value) for key, value in asdict(opening.state).items()}
                        or (stored[0].round_id, stored[0].opened_on) != (opening.round_id, opening.opened_on)):
                    raise CalculationInputMismatch("Stock opening or round does not match actual source")
                evidence = {"stock": stock, "round": str(opening.round_id),
                            "summary": summary.input_digest.hex(), "opening": summary.accumulator["opening"]}
            cursor = {"afterStock": source[0] if source else after, "done": not source}
            accumulator = {"binding": binding, "count": str(int(previous.accumulator["count"]) + len(source) if previous else len(source))}
            digest = sha256(self.stocks.inputs._encoded({"previous": previous.input_digest.hex() if previous else None,
                "source": evidence, "cursor": cursor, "accumulator": accumulator})).digest()
            now = session.scalar(select(func.clock_timestamp()))
            row = CalculationBatch(account_id=lease.account_id, generation_id=generation_id,
                trade_date=day.trade_date, stage="DAY_SCOPE_CHECK", stock_key="",
                page_key=f"{int(previous.page_key) + 1 if previous else 1:020d}", cursor=cursor,
                accumulator=accumulator, input_digest=digest, row_count=len(source), completed_at=now)
            session.add(row)
            session.flush()
            session.refresh(row)
            if (row.cursor, row.accumulator, row.input_digest) != (cursor, accumulator, digest):
                raise CalculationInputMismatch("Day scope readback differs")
            generation.last_business_updated_at = now
            return cursor["done"]
