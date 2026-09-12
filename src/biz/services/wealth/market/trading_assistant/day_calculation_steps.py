"""Advance an already prepared trading day by one durable unit (§4.6.2).

Caller supplies a frozen generation/day/valuation cutoff and owns the short
transaction. No market fetching, generation creation, publication or loop here.
"""
from sqlalchemy import select
from sqlalchemy.orm import aliased

from src.biz.models.wealth.trading_assistant.calculation import DayResult
from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch
from src.biz.models.wealth.trading_assistant.publication import AccountSnapshot
from src.biz.queries.wealth.market.trading_assistant.calculation_stocks import stock_day_page
from .account_day_batches import AccountDayBatches
from .calculation_inputs import CalculationInputMismatch
from .cash_balances import CashBalances
from .cash_day_batches import CashDayBatches
from .day_scope_verification import DayScopeVerification
from .day_sealing import DaySealing
from .snapshot_candidates import SnapshotCandidates
from .stock_day_batches import StockDayBatches
from .stock_day_verification import StockDayVerification
from .stock_openings import read_stock_opening
from .market_facts import MarketFactsReader


class DayCalculationSteps:
    def __init__(self, execution):
        self.execution = execution
        self.stocks = StockDayBatches(execution)
        self.account = AccountDayBatches(execution)
        self.cash = CashDayBatches(execution)

    def _unchecked(self, session, lease, generation_id, day, stages):
        source, checked = aliased(CalculationBatch), aliased(CalculationBatch)
        verified = select(checked.page_key).where(
            checked.account_id == source.account_id, checked.generation_id == source.generation_id,
            checked.trade_date == source.trade_date, checked.stock_key == source.stock_key,
            checked.stage == source.stage + "_CHECK", checked.page_key == source.page_key,
            checked.input_digest == source.input_digest, checked.row_count == source.row_count,
            checked.cursor == source.cursor).exists()
        return session.scalar(select(source).where(source.account_id == lease.account_id,
            source.generation_id == generation_id, source.trade_date == day,
            source.stage.in_(stages), ~verified).order_by(
                source.stock_key, source.stage, source.page_key).limit(1))

    def step(self, session, lease, *, generation_id, day_result_id,
             previous_day_result_id, valuation_at, deadline):
        with self.execution.batch(session, lease, deadline=deadline) as account:
            day = session.get(DayResult, day_result_id, populate_existing=True)
            if day is None or day.account_id != lease.account_id or day.origin_generation_id != generation_id:
                raise CalculationInputMismatch("Day is outside the fixed generation")
            generation = self.stocks.inputs._generation(session, lease, account, generation_id,
                day.trade_date, stages=("PREPARING", "CALCULATING"))
            if day.status == "SEALED":
                return "SEALED"
            calendar = MarketFactsReader(self.execution.policy).read_calendar(
                session, "SSE", day.trade_date, day.trade_date, deadline).days[0]
            if not calendar.is_open:
                raise CalculationInputMismatch("Stock day requires a trading date")
            predecessor = session.get(DayResult, previous_day_result_id,
                populate_existing=True) if previous_day_result_id else None
            if previous_day_result_id is not None:
                if (predecessor is None or predecessor.account_id != lease.account_id
                        or predecessor.status != "SEALED"
                        or predecessor.trade_date != calendar.previous_trade_date):
                    raise CalculationInputMismatch("Previous trading day must be sealed before reading stock scope")
            elif calendar.previous_trade_date is not None and calendar.previous_trade_date >= generation.from_date:
                raise CalculationInputMismatch("Missing preceding trading day in the fixed window")
            args = dict(generation_id=generation_id, day_result_id=day_result_id, deadline=deadline)
            opening_args = dict(account=account, generation=generation, trade_date=day.trade_date,
                previous_day_result_id=previous_day_result_id, policy=self.execution.policy, deadline=deadline)
            # A STOCK_CLOSED terminal page and its position are committed together.
            after = session.scalar(select(CalculationBatch.stock_key).where(
                CalculationBatch.account_id == lease.account_id, CalculationBatch.generation_id == generation_id,
                CalculationBatch.trade_date == day.trade_date, CalculationBatch.stage == "STOCK_CLOSED",
                CalculationBatch.cursor["done"].as_boolean().is_(True))
                .order_by(CalculationBatch.stock_key.desc()).limit(1))
            stock = session.scalar(stock_day_page(owner_id=account.owner_id, account_id=lease.account_id,
                initialization_id=generation.initialization_id, fact_version=generation.fact_version,
                trade_date=day.trade_date, previous_day_result_id=previous_day_result_id,
                limit=1, policy=self.execution.policy, after=after))
            if stock is not None:
                opening = read_stock_opening(session, stock=stock, **opening_args)
                stock_args = args | dict(stock=stock, opening=opening.state)
                for stage, run in (("STOCK_SUMMARY", self.stocks.summarize_page),
                                   ("STOCK_BASE", self.stocks.prepare_sell_page)):
                    last = self.stocks._latest(session, lease, generation_id, day.trade_date, stock, stage)
                    if last is None or not last.cursor["done"]:
                        run(session, lease, **stock_args)
                        return stage
                self.stocks.close_page(session, lease, **stock_args,
                    round_id=opening.round_id, opened_on=opening.opened_on)
                return "STOCK_CLOSED"
            unchecked = self._unchecked(session, lease, generation_id, day.trade_date,
                ("STOCK_SUMMARY", "STOCK_BASE", "STOCK_CLOSED"))
            if unchecked is not None:
                opening = read_stock_opening(session, stock=unchecked.stock_key, **opening_args)
                StockDayVerification(self.execution).verify_page(session, lease, **args,
                    stock=unchecked.stock_key, opening=opening.state, round_id=opening.round_id,
                    opened_on=opening.opened_on, stage=unchecked.stage, page_key=unchecked.page_key)
                return unchecked.stage + "_CHECK"
            scope = self.stocks._latest(session, lease, generation_id, day.trade_date, "", "DAY_SCOPE_CHECK")
            if scope is None or not scope.cursor["done"]:
                DayScopeVerification(self.execution).verify_next(session, lease, **args,
                    previous_day_result_id=previous_day_result_id)
                return "DAY_SCOPE_CHECK"
            if scope.accumulator["binding"]["previousDayId"] != (
                    str(previous_day_result_id) if previous_day_result_id else None):
                raise CalculationInputMismatch("Prepared day predecessor changed")
            totals = self.stocks._latest(session, lease, generation_id, day.trade_date, "", "ACCOUNT_STOCKS")
            if totals is None or not totals.cursor["done"]:
                self.account.reduce_page(session, lease, **args, previous_day_result_id=previous_day_result_id)
                return "ACCOUNT_STOCKS"
            unchecked = self._unchecked(session, lease, generation_id, day.trade_date, ("ACCOUNT_STOCKS",))
            if unchecked is not None:
                self.account.verify_page(session, lease, **args, previous_day_result_id=previous_day_result_id,
                    page_key=unchecked.page_key)
                return "ACCOUNT_STOCKS_CHECK"
            cash_args = dict(generation_id=generation_id, business_date=day.trade_date, deadline=deadline)
            cash = self.cash._latest(session, lease, generation_id, day.trade_date)
            if cash is None or not cash.cursor["done"]:
                self.cash.reduce_page(session, lease, **cash_args)
                return "ACCOUNT_CASH"
            unchecked = self._unchecked(session, lease, generation_id, day.trade_date, ("ACCOUNT_CASH",))
            if unchecked is not None:
                self.cash.verify_page(session, lease, **cash_args, page_key=unchecked.page_key)
                return "ACCOUNT_CASH_CHECK"
            if session.get(CalculationBatch,(lease.account_id,generation_id,day.trade_date,"CASH_BALANCE","","1")) is None:
                CashBalances(self.execution).close_date(session, lease, **cash_args)
                return "CASH_BALANCE"
            snapshot = session.get(AccountSnapshot,(lease.account_id,day_result_id))
            if snapshot is None:
                SnapshotCandidates(self.execution).save(session, lease, **args, valuation_at=valuation_at)
                return "ACCOUNT_SNAPSHOT"
            if snapshot.valuation_at != valuation_at:
                raise CalculationInputMismatch("Frozen snapshot cutoff changed")
            DaySealing(self.execution).seal(session, lease, **args)
            return "SEALED"
