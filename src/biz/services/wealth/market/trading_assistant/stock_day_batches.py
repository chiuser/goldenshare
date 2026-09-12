"""Bounded M3 stock/day reduction and per-sale persistence (§4.6.2).

The orchestrator supplies a proven opening state and BUILDING day. A transaction
contains one page, its read-back checks and checkpoint; no method commits.
"""
from dataclasses import asdict
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select

from src.biz.models.wealth.trading_assistant.calculation import DayResult, ClosedTrade, PositionState
from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch
from src.biz.queries.wealth.market.trading_assistant.calculation_ledger import trade_page, allocated_sell_page
from .calculation.daily import PositionState as OpeningState
from .calculation.fees import FeeSnapshot, calculate_trade_fees
from .calculation.precision import CalculationInvariantError, format_return_pct, round_ratio_half_up
from .calculation_inputs import CalculationInputs, CalculationInputMismatch
from .persistence_values import numeric_cents, numeric_integer, money_numeric, integer_numeric


def _scaled(value, scale):
    numerator, denominator = value.as_integer_ratio()
    result, remainder = divmod(numerator * scale, denominator)
    if remainder:
        raise CalculationInvariantError("Stored fee has unsupported precision")
    return result


def _empty():
    return dict(buyQuantity=0, sellQuantity=0, buyInput=0, sellNet=0,
                commission=0, stampTax=0, count=0, sellCount=0)


class StockDayBatches:
    def __init__(self, execution):
        self.execution = execution
        self.inputs = CalculationInputs(execution)
        self.policy = execution.policy

    def _day(self, session, lease, account, generation_id, day_result_id):
        day = session.get(DayResult, day_result_id)
        if day is None or day.account_id != lease.account_id or day.origin_generation_id != generation_id:
            raise CalculationInputMismatch("Day is outside this generation")
        generation = self.inputs._generation(session, lease, account, generation_id, day.trade_date,
                                              stages=("PREPARING", "CALCULATING"))
        if day.status != "BUILDING":
            raise CalculationInputMismatch("Cannot write a sealed day")
        return day, generation

    def _latest(self, session, lease, generation_id, day, stock, stage):
        return session.scalar(select(CalculationBatch).where(
            CalculationBatch.account_id == lease.account_id,
            CalculationBatch.generation_id == generation_id,
            CalculationBatch.trade_date == day, CalculationBatch.stock_key == stock,
            CalculationBatch.stage == stage).order_by(CalculationBatch.page_key.desc()).limit(1))

    def _checkpoint(self, session, lease, generation, day, stock, stage, page, previous, opening, totals, binding=None):
        from hashlib import sha256
        # All numbers use strings in JSON to remain exact for any future reader.
        cursor = {"afterLedger": str(page[-1]["ledger_id"]) if page else
                  (previous.cursor["afterLedger"] if previous else None), "done": not page}
        accumulator = {key: str(value) for key, value in totals.items()}
        accumulator["opening"] = {key: str(value) for key, value in asdict(opening).items()}
        accumulator["binding"] = binding
        evidence = {"previous": previous.input_digest.hex() if previous else None,
                    "rows": [{key: str(value) for key, value in row.items()} for row in page],
                    "cursor": cursor, "accumulator": accumulator}
        digest = sha256(self.inputs._encoded(evidence)).digest()
        key = f"{(int(previous.page_key) + 1) if previous else 1:020d}"
        now = session.scalar(select(func.clock_timestamp()))
        row = CalculationBatch(account_id=lease.account_id, generation_id=generation.generation_id,
            trade_date=day, stage=stage, stock_key=stock, page_key=key, cursor=cursor,
            accumulator=accumulator, input_digest=digest, row_count=len(page), completed_at=now)
        session.add(row)
        session.flush()
        session.refresh(row)
        if row.cursor != cursor or row.accumulator != accumulator or row.input_digest != digest:
            raise CalculationInputMismatch("Stock checkpoint read-back mismatch")
        generation.last_business_updated_at = now
        return cursor["done"]

    @staticmethod
    def _totals(previous, opening, empty):
        if previous is None:
            return empty
        if previous.accumulator["opening"] != {key: str(value) for key, value in asdict(opening).items()}:
            raise CalculationInputMismatch("Opening state changed across pages")
        return {key: int(previous.accumulator[key]) for key in empty}

    def summarize_page(self, session, lease, *, generation_id, day_result_id, stock, opening, deadline):
        with self.execution.batch(session, lease, deadline=deadline) as account:
            day, generation = self._day(session, lease, account, generation_id, day_result_id)
            previous = self._latest(session, lease, generation_id, day.trade_date, stock, "STOCK_SUMMARY")
            totals = self._totals(previous, opening, _empty())
            if previous and previous.cursor["done"]:
                return True
            page = session.execute(trade_page(owner_id=account.owner_id, account_id=lease.account_id,
                fact_version=generation.fact_version, trade_date=day.trade_date, stock=stock,
                limit=self.policy.page_rows, policy=self.policy,
                after=UUID(previous.cursor["afterLedger"]) if previous and previous.cursor["afterLedger"] else None)
            ).mappings().all()
            for row in page:
                deadline.remaining_ms()
                fees = FeeSnapshot(_scaled(row["commission_rate"], 1000000),
                    numeric_cents(row["minimum_commission"]), _scaled(row["stamp_tax_rate"], 10000))
                amount = calculate_trade_fees(row["quantity"] * numeric_cents(row["price"]), fees, row["direction"])
                if (amount.gross_cents, amount.commission_cents, amount.stamp_tax_cents,
                    amount.net_cash_change_cents) != tuple(numeric_cents(row[key]) for key in (
                        "gross_amount", "commission_amount", "stamp_tax_amount", "net_cash_change")):
                    raise CalculationInvariantError("Accepted trade does not match its original fee snapshot")
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
            if totals["sellQuantity"] > opening.available_quantity:
                raise CalculationInvariantError("Sell exceeds opening available quantity (T+1)")
            return self._checkpoint(session, lease, generation, day.trade_date, stock,
                                    "STOCK_SUMMARY", page, previous, opening, totals)

    def close_page(self, session, lease, *, generation_id, day_result_id, stock, opening,
                   round_id, opened_on, deadline):
        with self.execution.batch(session, lease, deadline=deadline) as account:
            day, generation = self._day(session, lease, account, generation_id, day_result_id)
            summary = self._latest(session, lease, generation_id, day.trade_date, stock, "STOCK_SUMMARY")
            if summary is None or not summary.cursor["done"]:
                raise CalculationInputMismatch("Complete stock/day summary required before allocation")
            totals = self._totals(summary, opening, _empty())
            previous = self._latest(session, lease, generation_id, day.trade_date, stock, "STOCK_CLOSED")
            binding = {"roundId": str(round_id), "openedOn": opened_on.isoformat()}
            if previous and previous.accumulator.get("binding") != binding:
                raise CalculationInputMismatch("Round identity changed across pages")
            closed = self._totals(previous, opening, dict(cost=0, net=0, quantity=0, count=0))
            if previous and previous.cursor["done"]:
                return True
            page = (session.execute(allocated_sell_page(owner_id=account.owner_id,
                account_id=lease.account_id, fact_version=generation.fact_version,
                trade_date=day.trade_date, stock=stock, opening_quantity=opening.quantity,
                opening_pool_cents=opening.pool_cents, limit=self.policy.page_rows, policy=self.policy,
                after=UUID(previous.cursor["afterLedger"]) if previous and previous.cursor["afterLedger"] else None)
                ).mappings().all() if totals["sellCount"] else [])
            target = (round_ratio_half_up(opening.pool_cents * totals["sellQuantity"], opening.quantity)
                      if totals["sellCount"] else 0)
            for row in page:
                deadline.remaining_ms()
                if (numeric_integer(row["allocation_target_cents"]), numeric_integer(row["total_sold"]),
                    row["sell_count"]) != (target, totals["sellQuantity"], totals["sellCount"]):
                    raise CalculationInputMismatch("Sell group differs from the complete summary")
                cost, net = numeric_integer(row["allocated_cost_cents"]), numeric_cents(row["net_cash_change"])
                result = ClosedTrade(account_id=lease.account_id, day_result_id=day_result_id,
                    sell_ledger_id=row["ledger_id"], sell_revision=row["revision"], round_id=round_id,
                    quantity=row["quantity"], allocated_cost=money_numeric(cost), net_proceeds=money_numeric(net),
                    profit_amount=money_numeric(net-cost), return_pct=Decimal(format_return_pct(net-cost, cost)))
                session.add(result)
                closed["cost"] += cost
                closed["net"] += net
                closed["quantity"] += row["quantity"]
                closed["count"] += 1
            session.flush()
            if page:
                saved = session.scalars(select(ClosedTrade).where(ClosedTrade.account_id == lease.account_id,
                    ClosedTrade.day_result_id == day_result_id, ClosedTrade.sell_ledger_id.in_(
                        [row["ledger_id"] for row in page])).order_by(ClosedTrade.sell_ledger_id)
                    .execution_options(populate_existing=True)).all()
                if len(saved) != len(page) or any((actual.sell_ledger_id, actual.sell_revision, actual.quantity,
                    numeric_cents(actual.allocated_cost), numeric_cents(actual.net_proceeds), actual.round_id) !=
                    (row["ledger_id"], row["revision"], row["quantity"], int(row["allocated_cost_cents"]),
                     numeric_cents(row["net_cash_change"]), round_id) for actual, row in zip(saved, page, strict=True)):
                    raise CalculationInputMismatch("Closed sale read-back mismatch")
            else:
                if closed != dict(cost=target, net=totals["sellNet"], quantity=totals["sellQuantity"], count=totals["sellCount"]):
                    raise CalculationInvariantError("Whole-day closed cost/cash/quantity conservation failed")
                ending = OpeningState(opening.quantity - totals["sellQuantity"] + totals["buyQuantity"],
                    opening.available_quantity - totals["sellQuantity"],
                    opening.pool_cents - target + totals["buyInput"],
                    opening.buy_investment_cents + totals["buyInput"], opening.sell_net_cents + totals["sellNet"])
                if ending.buy_investment_cents:
                    session.add(PositionState(account_id=lease.account_id, day_result_id=day_result_id,
                        ts_code=stock, round_id=round_id, opened_on=opened_on,
                        closed_on=day.trade_date if ending.quantity == 0 else None,
                        quantity=integer_numeric(ending.quantity), remaining_buy_cost=money_numeric(ending.pool_cents),
                        cumulative_buy_input=money_numeric(ending.buy_investment_cents),
                        cumulative_sell_net=money_numeric(ending.sell_net_cents)))
            return self._checkpoint(session, lease, generation, day.trade_date, stock,
                                    "STOCK_CLOSED", page, previous, opening, closed, binding)
