"""Read one published calendar/valuation page against current source facts.

No scheduler, target changes, fee reselection or trading-rule evaluation.
The internal discovery caller owns this short transaction and its cursor.
"""
from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256

from sqlalchemy import select

from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration, DayResult, Recalculation
from src.biz.models.wealth.trading_assistant.calculation_inputs import CalculationBatch
from src.biz.models.wealth.trading_assistant.publication import PublicationDay, PublicationReceipt
from .calendar_inputs import CalendarInputs
from .calculation_inputs import CalculationInputs, CalculationInputMismatch, CalculationDataUnavailable
from .cutoff_preparation import AccountCutoffPreparation
from .market_facts import MarketFactsReader, apply_sql_budget
from .valuation_facts import DailyCloseFactsReader


@dataclass(frozen=True, slots=True)
class SourcePageCheck:
    calendar_before: dict
    calendar_after: dict
    prices_before: tuple
    prices_after: tuple
    next_page: str | None
    done: bool

    @property
    def changed(self):
        return (self.calendar_before != self.calendar_after
                or self.prices_before != self.prices_after)


class PublishedSourceCheck:
    def __init__(self, execution):
        self.execution = execution
        self.inputs = CalculationInputs(execution)

    def page(self, session, *, account_id, generation_id, business_date, after_page=None, deadline):
        if type(business_date) is not date:
            raise ValueError("Expected a business date")
        policy = self.execution.policy
        apply_sql_budget(session, deadline, policy)
        account = session.scalar(select(Account).where(Account.account_id == account_id)
            .with_for_update().execution_options(populate_existing=True))
        generation = session.get(CalculationGeneration, generation_id)
        receipt = session.get(PublicationReceipt, (account_id, generation_id))
        if (account is None or account.published_generation_id != generation_id
                or generation is None or generation.account_id != account_id
                or generation.stage != "PUBLISHED" or receipt is None
                or receipt.target_version != generation.target_version
                or generation.target_version != account.calculation_target_version
                or generation.fact_version != account.fact_version
                or generation.initialization_id != account.current_initialization_id
                or not generation.from_date <= business_date <= generation.through_date
                or session.get(Recalculation, account_id) is not None):
            raise CalculationInputMismatch("Source check requires the fixed current publication")
        old = CalendarInputs(self.execution)._read_saved_date(session, account_id, generation_id, business_date)
        current = MarketFactsReader(policy).read_calendar(session, "SSE", business_date, business_date, deadline).days[0]
        new = {key: value.isoformat() if isinstance(value, date) else value for key, value in asdict(current).items()}
        deadline.remaining_ms()
        if old != new or not old["is_open"]:
            return SourcePageCheck(old, new, (), (), None, True)
        manifest = session.get(PublicationDay, (account_id, generation_id, business_date))
        day = session.get(DayResult, manifest.day_result_id) if manifest else None
        if day is None or day.account_id != account_id or day.trade_date != business_date or day.status != "SEALED":
            raise CalculationInputMismatch("Published source date lacks a sealed direct result")
        return self._price_page(session, account_id=account_id, source_id=day.origin_generation_id,
            business_date=business_date, after_page=after_page, old=old, new=new, deadline=deadline)

    def _price_page(self, session, *, account_id, source_id, business_date, after_page, old, new, deadline):
        """Caller verifies the direct sealed source and owns its account fence."""
        policy = self.execution.policy
        query = select(CalculationBatch).where(CalculationBatch.account_id == account_id,
            CalculationBatch.generation_id == source_id, CalculationBatch.trade_date == business_date,
            CalculationBatch.stage == "VALUATION", CalculationBatch.stock_key == "")
        if after_page is not None:
            prior = self.inputs._read_saved_page(session, account_id, source_id, business_date, after_page)
            if prior is None:
                raise CalculationInputMismatch("Source check cursor does not identify a saved page")
            query = query.where(CalculationBatch.page_key > after_page)
        batch = session.scalar(query.order_by(CalculationBatch.page_key).limit(1))
        if batch is None:
            terminal = session.get(CalculationBatch, (account_id, source_id, business_date, "VALUATION_END", "", "1"))
            previous = session.get(CalculationBatch, (account_id, source_id, business_date, "VALUATION", "", after_page)) if after_page else None
            if (terminal is None or terminal.row_count != 0
                    or terminal.cursor != {"afterStock": after_page, "done": True}
                    or terminal.accumulator.get("lastPageDigest") != (previous.input_digest.hex() if previous else None)
                    or terminal.input_digest != sha256(self.inputs._encoded(terminal.accumulator)).digest()):
                raise CalculationInputMismatch("Published valuation scope is incomplete")
            return SourcePageCheck(old, new, (), (), None, True)
        frozen = self.inputs._read_saved_page(session, account_id, source_id, business_date, batch.page_key)
        if frozen is None or frozen.after_stock != after_page or any(f.price is None for f in frozen.facts):
            raise CalculationInputMismatch("Source check skipped a saved valuation page")
        facts = DailyCloseFactsReader(policy).read(session, tuple(f.ts_code for f in frozen.facts), business_date, deadline)
        if any(f.price is None for f in facts):
            raise CalculationDataUnavailable("历史估值所需的行情暂未就绪")
        AccountCutoffPreparation(policy)._check_bytes([asdict(f) for f in facts])
        deadline.remaining_ms()
        return SourcePageCheck(old, new, frozen.facts, facts, batch.page_key, False)
