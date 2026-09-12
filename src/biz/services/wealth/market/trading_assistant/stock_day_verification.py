"""Read bounded stock checkpoints against their effective source, before sealing."""
from dataclasses import asdict
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from sqlalchemy import func, select

from src.biz.models.wealth.trading_assistant.calculation import ClosedTrade, PositionState
from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch
from src.biz.queries.wealth.market.trading_assistant.calculation_ledger import (
    trade_page, sell_source_page, allocated_sell_page,
)
from .calculation.fees import FeeSnapshot, calculate_trade_fees
from .calculation.precision import format_return_pct, round_ratio_half_up
from .calculation_inputs import CalculationInputMismatch
from .persistence_values import numeric_cents, numeric_integer, money_numeric, integer_numeric
from .stock_day_batches import StockDayBatches, _empty, _scaled


class StockDayVerification:
    def __init__(self, execution):
        self.execution = execution
        self.batches = StockDayBatches(execution)

    def verify_page(self, session, lease, *, generation_id, day_result_id, stock,
                    opening, stage, page_key, round_id, opened_on, deadline):
        if stage not in ("STOCK_SUMMARY", "STOCK_BASE", "STOCK_CLOSED"):
            raise ValueError("Unsupported stock verification stage")
        with self.execution.batch(session, lease, deadline=deadline) as account:
            day, generation = self.batches._day(session, lease, account, generation_id, day_result_id)
            scope = (CalculationBatch.account_id == lease.account_id,
                     CalculationBatch.generation_id == generation_id,
                     CalculationBatch.trade_date == day.trade_date,
                     CalculationBatch.stock_key == stock, CalculationBatch.stage == stage)
            current = session.get(CalculationBatch,
                (lease.account_id, generation_id, day.trade_date, stage, stock, page_key),
                populate_existing=True)
            previous = session.scalar(select(CalculationBatch).where(*scope,
                CalculationBatch.page_key < page_key).order_by(CalculationBatch.page_key.desc()).limit(1))
            if (current is None or not 0 <= current.row_count <= self.execution.policy.page_rows
                    or page_key != f"{int(previous.page_key) + 1 if previous else 1:020d}"
                    or (previous and previous.cursor["done"])):
                raise CalculationInputMismatch("Stock checkpoint chain is incomplete")
            after = UUID(previous.cursor["afterLedger"]) if previous and previous.cursor["afterLedger"] else None
            query_args = dict(owner_id=account.owner_id, account_id=lease.account_id,
                fact_version=generation.fact_version, trade_date=day.trade_date, stock=stock,
                limit=current.row_count or 1, policy=self.execution.policy, after=after)
            if stage == "STOCK_SUMMARY":
                query = trade_page(**query_args)
                empty = _empty()
            elif stage == "STOCK_BASE":
                query = sell_source_page(**query_args)
                empty = dict(count=0, quantity=0, net=0, base=0)
            else:
                query = (allocated_sell_page(**query_args, opening_quantity=opening.quantity,
                    opening_pool_cents=opening.pool_cents) if opening.quantity else sell_source_page(**query_args))
                empty = dict(cost=0, net=0, quantity=0, count=0)
            rows = session.execute(query).mappings().all()
            if len(rows) != current.row_count:
                raise CalculationInputMismatch("Stock checkpoint source count changed")
            totals = self.batches._totals(previous, opening, empty)
            candidates = []
            for row in rows:
                deadline.remaining_ms()
                if stage == "STOCK_SUMMARY":
                    fees = FeeSnapshot(_scaled(row["commission_rate"], 1000000),
                        numeric_cents(row["minimum_commission"]), _scaled(row["stamp_tax_rate"], 10000))
                    amount = calculate_trade_fees(row["quantity"] * numeric_cents(row["price"]), fees, row["direction"])
                    if (amount.gross_cents, amount.commission_cents, amount.stamp_tax_cents,
                        amount.net_cash_change_cents) != tuple(numeric_cents(row[key]) for key in (
                            "gross_amount", "commission_amount", "stamp_tax_amount", "net_cash_change")):
                        raise CalculationInputMismatch("Trade differs from its original fee basis")
                    totals["count"] += 1
                    totals["commission"] += amount.commission_cents
                    totals["stampTax"] += amount.stamp_tax_cents
                    if row["direction"] == "BUY":
                        totals["buyQuantity"] += row["quantity"]
                        totals["buyInput"] -= amount.net_cash_change_cents
                    else:
                        totals["sellCount"] += 1
                        totals["sellQuantity"] += row["quantity"]
                        totals["sellNet"] += amount.net_cash_change_cents
                elif stage == "STOCK_BASE":
                    if opening.quantity <= 0:
                        raise CalculationInputMismatch("Sale has no opening position")
                    base, remainder = divmod(opening.pool_cents * row["quantity"], opening.quantity)
                    candidates.append({**{key: str(value) for key, value in row.items()},
                                       "base_cost_cents": str(base), "remainder": str(remainder)})
                    totals["count"] += 1
                    totals["quantity"] += row["quantity"]
                    totals["net"] += numeric_cents(row["net_cash_change"])
                    totals["base"] += base
                else:
                    if opening.quantity <= 0:
                        raise CalculationInputMismatch("Sale has no opening position")
                    totals["cost"] += numeric_integer(row["allocated_cost_cents"])
                    totals["net"] += numeric_cents(row["net_cash_change"])
                    totals["quantity"] += row["quantity"]
                    totals["count"] += 1
            if stage == "STOCK_SUMMARY" and totals["sellQuantity"] > opening.available_quantity:
                raise CalculationInputMismatch("Sales exceed opening available quantity")
            cursor = {"afterLedger": str(rows[-1]["ledger_id"]) if rows else str(after) if after else None,
                      "done": not rows}
            accumulator = {key: str(value) for key, value in totals.items()}
            accumulator["opening"] = {key: str(value) for key, value in asdict(opening).items()}
            accumulator["binding"] = ({"roundId": str(round_id), "openedOn": opened_on.isoformat()}
                                      if stage == "STOCK_CLOSED" else None)
            if stage == "STOCK_BASE":
                accumulator["rows"] = candidates
            evidence = {"previous": previous.input_digest.hex() if previous else None,
                "rows": [{key: str(value) for key, value in row.items()} for row in rows],
                "cursor": cursor, "accumulator": accumulator}
            digest = sha256(self.batches.inputs._encoded(evidence)).digest()
            if (current.cursor, current.accumulator, current.input_digest) != (cursor, accumulator, digest):
                raise CalculationInputMismatch("Stock checkpoint differs from effective facts")
            if stage == "STOCK_CLOSED":
                self._closed_rows(session, lease.account_id, day_result_id, after, rows, round_id)
                if not rows:
                    self._ending(session, lease, generation_id, day, stock, opening, totals, round_id, opened_on)
            identity = (lease.account_id, generation_id, day.trade_date, stage + "_CHECK", stock, page_key)
            checked = session.get(CalculationBatch, identity, populate_existing=True)
            if checked is None:
                now = session.scalar(select(func.clock_timestamp()))
                session.add(CalculationBatch(account_id=lease.account_id, generation_id=generation_id,
                    trade_date=day.trade_date, stage=stage + "_CHECK", stock_key=stock, page_key=page_key,
                    cursor=cursor, accumulator={}, input_digest=digest, row_count=len(rows), completed_at=now))
                generation.last_business_updated_at = now
            elif (checked.cursor, checked.input_digest, checked.row_count) != (cursor, digest, len(rows)):
                raise CalculationInputMismatch("Stock verification marker differs from source")
            return cursor["done"]

    def _closed_rows(self, session, account_id, day_id, after, rows, round_id):
        # The round comes from the day-opening source, not from an untrusted saved row.
        query = select(ClosedTrade).where(ClosedTrade.account_id == account_id,
            ClosedTrade.day_result_id == day_id, ClosedTrade.round_id == round_id)
        if after:
            query = query.where(ClosedTrade.sell_ledger_id > after)
        saved = session.scalars(query.order_by(ClosedTrade.sell_ledger_id).limit(len(rows) or 1)
                                .execution_options(populate_existing=True)).all()
        expected = []
        for row in rows:
            cost, net = numeric_integer(row["allocated_cost_cents"]), numeric_cents(row["net_cash_change"])
            expected.append((row["ledger_id"], row["revision"], row["quantity"], cost, net,
                             net - cost, Decimal(format_return_pct(net - cost, cost))))
        actual = [(row.sell_ledger_id, row.sell_revision, row.quantity, numeric_cents(row.allocated_cost),
                   numeric_cents(row.net_proceeds), numeric_cents(row.profit_amount), row.return_pct) for row in saved]
        if actual != expected:
            raise CalculationInputMismatch("Stored closed sales differ from effective sell facts")

    def _ending(self, session, lease, generation_id, day, stock, opening, closed, round_id, opened_on):
        summary = self.batches._latest(session, lease, generation_id, day.trade_date, stock, "STOCK_SUMMARY")
        if summary is None or not summary.cursor["done"]:
            raise CalculationInputMismatch("Missing completed stock summary")
        totals = self.batches._totals(summary, opening, _empty())
        target = round_ratio_half_up(opening.pool_cents * totals["sellQuantity"], opening.quantity) if totals["sellQuantity"] else 0
        if closed != dict(cost=target, net=totals["sellNet"], quantity=totals["sellQuantity"], count=totals["sellCount"]):
            raise CalculationInputMismatch("Closed group does not conserve the full-day totals")
        quantity = opening.quantity - totals["sellQuantity"] + totals["buyQuantity"]
        investment = opening.buy_investment_cents + totals["buyInput"]
        saved = session.scalars(select(PositionState).where(PositionState.account_id == lease.account_id,
            PositionState.day_result_id == day.day_result_id, PositionState.ts_code == stock).limit(2)
            .execution_options(populate_existing=True)).all()
        expected = dict(round_id=round_id, opened_on=opened_on, closed_on=day.trade_date if quantity == 0 else None,
            quantity=integer_numeric(quantity), remaining_buy_cost=money_numeric(opening.pool_cents - target + totals["buyInput"]),
            cumulative_buy_input=money_numeric(investment), cumulative_sell_net=money_numeric(opening.sell_net_cents + totals["sellNet"]))
        if (investment and (len(saved) != 1 or any(getattr(saved[0], key) != value for key, value in expected.items()))) or (
                not investment and saved):
            raise CalculationInputMismatch("Stored ending position differs from source totals")
