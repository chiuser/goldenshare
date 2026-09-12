"""Resume account stock aggregation from persisted stock-day candidates.

This stage does not seal a day or publish a generation. A final source coverage
audit is still required before either operation. Each call owns at most one
bounded stock page; the caller owns the short transaction.
"""
from dataclasses import asdict
from fractions import Fraction
from hashlib import sha256

from sqlalchemy import func, select

from src.biz.models.wealth.trading_assistant.accounts import FeeVersion
from src.biz.models.wealth.trading_assistant.calculation import DayResult, PositionState
from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch, ValuationBasis
from .calculation.account_day import AccountDayTotals, StockDayContribution, add_stock_day
from .calculation.daily import PositionState as KernelPosition
from .calculation.fees import FeeSnapshot
from .calculation.returns import value_round
from .calculation_inputs import CalculationInputMismatch
from .persistence_values import numeric_cents, numeric_integer
from .stock_day_batches import StockDayBatches, _scaled


def _state(row):
    return KernelPosition(numeric_integer(row.quantity), numeric_integer(row.quantity),
        numeric_cents(row.remaining_buy_cost), numeric_cents(row.cumulative_buy_input),
        numeric_cents(row.cumulative_sell_net))


def _totals_json(totals):
    return {key: str(value) if type(value) is int else value for key, value in asdict(totals).items()}


def _totals_value(value):
    fields = asdict(AccountDayTotals())
    if value.keys() != fields.keys():
        raise CalculationInputMismatch("Account accumulator fields changed")
    return AccountDayTotals(**{key: int(value[key]) if type(default) is int else value[key]
                              for key, default in fields.items()})


def _valuation_evidence(pair):
    if pair is None:
        return None
    basis, fee = pair
    return {"basis": str(basis.basis_id), "price": str(basis.price), "quality": basis.quality,
        "sourceVersion": basis.source_version, "feeVersion": str(fee.fee_version_id),
        "commissionRate": str(fee.commission_rate), "minimumCommission": str(fee.minimum_commission),
        "stampTaxRate": str(fee.stamp_tax_rate)}


class AccountDayBatches:
    def __init__(self, execution):
        self.execution = execution
        self.stocks = StockDayBatches(execution)
        self.inputs = self.stocks.inputs
        self.policy = execution.policy

    def _valuations(self, session, account_id, generation_id, trade_date, codes):
        rows = session.execute(select(ValuationBasis, FeeVersion).join(FeeVersion,
            (FeeVersion.fee_version_id == ValuationBasis.fee_version_id)
            & (FeeVersion.account_id == ValuationBasis.account_id)).where(
                ValuationBasis.account_id == account_id, ValuationBasis.generation_id == generation_id,
                ValuationBasis.trade_date == trade_date, ValuationBasis.ts_code.in_(codes))
            .limit(self.policy.page_rows + 1)).all()
        if len(rows) > self.policy.page_rows:
            raise CalculationInputMismatch("Valuation page exceeds the stock scope")
        return {basis.ts_code: (basis, fee) for basis, fee in rows}

    @staticmethod
    def _valuation(state, code, valuations):
        if state.quantity == 0:
            return None, FeeSnapshot(0, 0, 0)
        pair = valuations.get(code)
        if pair is None:
            raise CalculationInputMismatch("Held stock is missing its frozen valuation basis")
        basis, fee = pair
        return (Fraction(basis.price) if basis.quality == "READY" and basis.price is not None else None,
            FeeSnapshot(_scaled(fee.commission_rate, 1000000), numeric_cents(fee.minimum_commission),
                        _scaled(fee.stamp_tax_rate, 10000)))

    def reduce_page(self, session, lease, *, generation_id, day_result_id, previous_day_result_id, deadline):
        with self.execution.batch(session, lease, deadline=deadline) as account:
            day, generation = self.stocks._day(session, lease, account, generation_id, day_result_id)
            predecessor = session.get(DayResult, previous_day_result_id) if previous_day_result_id else None
            if previous_day_result_id is not None and (predecessor is None
                    or predecessor.account_id != lease.account_id or predecessor.status != "SEALED"
                    or predecessor.trade_date >= day.trade_date):
                raise CalculationInputMismatch("Previous account day must be an earlier sealed day")
            previous = self.stocks._latest(session, lease, generation_id, day.trade_date, "", "ACCOUNT_STOCKS")
            binding = {"dayResultId": str(day_result_id),
                       "previousDayResultId": str(previous_day_result_id) if previous_day_result_id else None,
                       "previousDayDigest": predecessor.input_digest.hex() if predecessor else None}
            if previous and previous.accumulator["binding"] != binding:
                raise CalculationInputMismatch("Account predecessor changed across pages")
            totals = _totals_value(previous.accumulator["totals"]) if previous else AccountDayTotals()
            if previous and previous.cursor["done"]:
                return True
            query = select(PositionState, func.count().over(partition_by=PositionState.ts_code)).where(PositionState.account_id == lease.account_id,
                                                PositionState.day_result_id == day_result_id)
            if totals.after_stock is not None:
                query = query.where(PositionState.ts_code > totals.after_stock)
            selected = session.execute(query.order_by(PositionState.ts_code, PositionState.round_id)
                                       .limit(self.policy.page_rows)).all()
            if any(count != 1 for _, count in selected):
                raise CalculationInputMismatch("Multiple rounds in one stock-day candidate")
            rows = [row for row, _ in selected]
            codes = [row.ts_code for row in rows]
            if len(codes) != len(set(codes)):
                raise CalculationInputMismatch("Multiple rounds in one stock-day candidate")
            checkpoints = session.scalars(select(CalculationBatch).where(
                CalculationBatch.account_id == lease.account_id, CalculationBatch.generation_id == generation_id,
                CalculationBatch.trade_date == day.trade_date, CalculationBatch.stock_key.in_(codes),
                CalculationBatch.stage.in_(("STOCK_SUMMARY", "STOCK_CLOSED")),
                CalculationBatch.cursor["done"].as_boolean().is_(True))
                .limit(self.policy.page_rows * 2 + 1)).all() if codes else []
            indexed = {(row.stock_key, row.stage): row for row in checkpoints}
            if len(checkpoints) != len(codes) * 2 or len(indexed) != len(checkpoints):
                raise CalculationInputMismatch("Stock pages are not completely reduced")
            valuations = self._valuations(session, lease.account_id, generation_id, day.trade_date, codes) if codes else {}
            prior_rows = session.scalars(select(PositionState).where(PositionState.account_id == lease.account_id,
                PositionState.day_result_id == previous_day_result_id, PositionState.ts_code.in_(codes))
                .limit(self.policy.page_rows + 1)).all() if predecessor and codes else []
            priors = {row.ts_code: row for row in prior_rows}
            if len(priors) != len(prior_rows) or len(prior_rows) > self.policy.page_rows:
                raise CalculationInputMismatch("Ambiguous previous stock-day state")
            prior_values = self._valuations(session, lease.account_id, predecessor.origin_generation_id,
                predecessor.trade_date, codes) if predecessor and codes else {}
            evidence = []
            for row in rows:
                deadline.remaining_ms()
                summary = indexed[row.ts_code, "STOCK_SUMMARY"]
                closed = indexed[row.ts_code, "STOCK_CLOSED"]
                opening_dict = summary.accumulator["opening"]
                opening = KernelPosition(**{key: int(value) for key, value in opening_dict.items()})
                if closed.accumulator["opening"] != opening_dict or closed.accumulator["binding"] != {
                        "roundId": str(row.round_id), "openedOn": row.opened_on.isoformat()}:
                    raise CalculationInputMismatch("Stock reduction source binding changed")
                prior = priors.get(row.ts_code)
                if prior is not None and prior.round_id == row.round_id:
                    prior_state = _state(prior)
                    if (prior_state.quantity, prior_state.pool_cents, prior_state.buy_investment_cents,
                        prior_state.sell_net_cents) != (opening.quantity, opening.pool_cents,
                            opening.buy_investment_cents, opening.sell_net_cents):
                        raise CalculationInputMismatch("Opening does not continue the sealed stock state")
                    price, fees = self._valuation(prior_state, row.ts_code, prior_values)
                    opening_profit = value_round(prior_state, price, fees).result.profit_cents
                elif row.opened_on == day.trade_date:
                    opening_profit = 0
                else:
                    raise CalculationInputMismatch("Existing round has no sealed opening valuation")
                ending = _state(row)
                if ending.quantity != (opening.quantity - int(summary.accumulator["sellQuantity"])
                                       + int(summary.accumulator["buyQuantity"])):
                    raise CalculationInputMismatch("Stock quantity does not match its complete trade summary")
                price, fees = self._valuation(ending, row.ts_code, valuations)
                buy, net = int(summary.accumulator["buyInput"]), int(summary.accumulator["sellNet"])
                if (int(closed.accumulator["net"]), int(closed.accumulator["count"])) != (
                        net, int(summary.accumulator["sellCount"])):
                    raise CalculationInputMismatch("Stock closed totals differ from its trade summary")
                totals = add_stock_day(totals, StockDayContribution(row.ts_code, opening, ending,
                    opening_profit, buy, net, int(closed.accumulator["count"]),
                    net - int(closed.accumulator["cost"]), price, fees))
                evidence.append({"stock": row.ts_code, "round": str(row.round_id),
                    "summary": summary.input_digest.hex(), "closed": closed.input_digest.hex(),
                    "openingProfit": str(opening_profit),
                    "valuation": _valuation_evidence(valuations.get(row.ts_code)),
                    "previousValuation": _valuation_evidence(prior_values.get(row.ts_code)),
                    "ending": {key: str(value) for key, value in asdict(ending).items()}})
            cursor = {"afterStock": totals.after_stock, "done": not rows}
            accumulator = {"binding": binding, "totals": _totals_json(totals)}
            digest = sha256(self.inputs._encoded({"previous": previous.input_digest.hex() if previous else None,
                "sources": evidence, "cursor": cursor, "accumulator": accumulator})).digest()
            key = f"{int(previous.page_key) + 1 if previous else 1:020d}"
            now = session.scalar(select(func.clock_timestamp()))
            checkpoint = CalculationBatch(account_id=lease.account_id, generation_id=generation_id,
                trade_date=day.trade_date, stage="ACCOUNT_STOCKS", stock_key="", page_key=key,
                cursor=cursor, accumulator=accumulator, input_digest=digest, row_count=len(rows),
                completed_at=now)
            session.add(checkpoint)
            session.flush()
            session.refresh(checkpoint)
            if (checkpoint.accumulator, checkpoint.cursor, checkpoint.input_digest) != (accumulator, cursor, digest):
                raise CalculationInputMismatch("Account stock checkpoint read-back mismatch")
            generation.last_business_updated_at = now
            return cursor["done"]
