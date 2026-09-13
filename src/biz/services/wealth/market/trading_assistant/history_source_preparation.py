"""Persist one historical source-check page and atomically accept a change."""
from dataclasses import asdict
from datetime import date, timedelta
import json

from sqlalchemy import func, select

from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration, Recalculation
from src.biz.models.wealth.trading_assistant.calculation_inputs import CutoffPreparation
from .calculation_inputs import CalculationInputs, CalculationInputMismatch, CalculationDataUnavailable
from .market_facts import MarketFactsUnavailable
from .published_source_check import PublishedSourceCheck


class HistorySourcePreparation:
    def __init__(self, execution):
        self.execution = execution

    def step(self, session, *, account_id, deadline):
        """Discovery owns the account lock, transaction and account cursor."""
        account = session.scalar(select(Account).where(Account.account_id == account_id)
            .with_for_update().execution_options(populate_existing=True))
        if account is None or session.get(Recalculation, account_id) is not None:
            raise CalculationInputMismatch("Historical discovery requires an idle account")
        generation = session.get(CalculationGeneration, account.published_generation_id) if account.published_generation_id else None
        if (generation is None or generation.account_id != account_id or generation.stage != "PUBLISHED"
                or generation.target_version != account.calculation_target_version
                or generation.fact_version != account.fact_version
                or generation.initialization_id != account.current_initialization_id):
            raise CalculationInputMismatch("Historical discovery requires the current publication")
        now = session.scalar(select(func.clock_timestamp()))
        row = session.get(CutoffPreparation, (account_id, generation.target_version, "HISTORY"))
        if row is None:
            row = CutoffPreparation(account_id=account_id, target_version=generation.target_version, purpose="HISTORY",
                fact_version=generation.fact_version, initialization_id=generation.initialization_id,
                from_date=generation.from_date, scan_through_date=generation.through_date,
                current_date=generation.from_date, state="SCANNING", updated_at=now)
            session.add(row)
            session.flush()
        if (row.fact_version, row.initialization_id, row.from_date, row.scan_through_date) != (
                generation.fact_version, generation.initialization_id, generation.from_date, generation.through_date):
            raise CalculationInputMismatch("Historical source cursor differs from its publication")
        if row.state == "CHANGED":
            raise CalculationInputMismatch("Historical source cursor cannot resume automatically")
        if row.state == "FAILED":
            if row.next_attempt_at is None or row.next_attempt_at > now:
                return "IDLE"
            row.state, row.reason = "SCANNING", None
            if row.current_date > row.scan_through_date:
                row.current_date, row.complete_through, row.after_stock = row.from_date, None, None
        if row.state in ("READY", "WAITING_DATA"):
            if now < row.updated_at+timedelta(seconds=self.execution.policy.data_probe_seconds):
                return "IDLE"
            if row.state == "READY":
                row.current_date, row.complete_through, row.after_stock = row.from_date, None, None
        try:
            result = PublishedSourceCheck(self.execution).page(session, account_id=account_id,
                generation_id=generation.generation_id, business_date=row.current_date,
                after_page=row.after_stock, deadline=deadline)
        except (CalculationDataUnavailable, MarketFactsUnavailable):
            # This timestamp controls the next probe, not completed calculation
            # progress; it is never projected as a day-result update.
            row.state, row.reason, row.updated_at = "WAITING_DATA", "历史行情或日历暂未就绪", now
            return "WAITING_DATA"
        row.updated_at, row.reason = now, None
        if result.changed:
            evidence = {"generationId": str(generation.generation_id), "businessDate": row.current_date.isoformat(),
                "afterPage": row.after_stock, "nextPage": result.next_page,
                "calendarBefore": result.calendar_before, "calendarAfter": result.calendar_after,
                "pricesBefore": [asdict(f) for f in result.prices_before],
                "pricesAfter": [asdict(f) for f in result.prices_after]}
            # Normalize only dates; price strings keep all source decimals.
            evidence = json.loads(json.dumps(evidence, default=lambda v: v.isoformat() if isinstance(v, date) else str(v)))
            CalculationInputs(self.execution)._encoded(evidence)
            row.state, row.evidence = "CHANGED", evidence
            account.calculation_target_version += 1
            session.add(Recalculation(account_id=account_id, target_version=account.calculation_target_version,
                affected_from_date=row.current_date, next_attempt_at=now, fence=0,
                transient_failure_count=0, updated_at=now))
            stage = "ENQUEUED"
        elif result.done:
            row.complete_through = row.current_date
            row.current_date += timedelta(days=1)
            row.after_stock = None
            row.state = "READY" if row.current_date > row.scan_through_date else "SCANNING"
            stage = "VERIFIED" if row.state == "READY" else "PREPARING"
        else:
            row.state, row.after_stock = "SCANNING", result.next_page
            stage = "PREPARING"
        deadline.remaining_ms()
        session.flush()
        return stage
