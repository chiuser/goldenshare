"""Confirm a continuous account range one persisted date/stock page at a time."""
from datetime import timedelta, date
from dataclasses import asdict
import json
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from src.biz.models.wealth.trading_assistant.accounts import Account, InitialPosition
from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration, Recalculation
from src.biz.models.wealth.trading_assistant.calculation_inputs import CutoffPreparation
from src.biz.queries.wealth.market.trading_assistant.cutoff_stocks import cutoff_stock_page
from .calculation_inputs import CalculationDataUnavailable, CalculationInputMismatch
from .market_facts import MarketFactsReader, MarketFactsUnavailable, apply_sql_budget
from .valuation_clock import valuation_cutoff
from .valuation_facts import DailyCloseFactsReader


class CutoffPreparationInProgress(Exception):
    """One scan unit committed; yield fairly without a missing-data delay."""


class AccountCutoffPreparation:
    def __init__(self, policy):
        self.policy = policy

    def resolve(self, session, *, account_id, target_version, deadline, purpose="INITIAL"):
        # The work owner commits this evidence and verifies its lease in the
        # same short transaction. Exceptions below are handled inside it.
        if purpose not in ("INITIAL", "DISCOVERY"):
            raise ValueError("Invalid cutoff preparation purpose")
        apply_sql_budget(session, deadline, self.policy)
        account = session.scalar(select(Account).where(Account.account_id == account_id)
            .with_for_update().execution_options(populate_existing=True))
        if account is None or account.calculation_target_version != target_version:
            raise CalculationInputMismatch("Cutoff scan target no longer matches")
        now = session.scalar(select(func.clock_timestamp()))
        previous = None
        if purpose == "DISCOVERY":
            previous = session.get(CalculationGeneration, account.published_generation_id) if account.published_generation_id else None
            if (previous is None or previous.account_id != account_id or previous.stage != "PUBLISHED"
                    or previous.target_version != target_version or previous.fact_version != account.fact_version
                    or session.get(Recalculation, account_id) is not None):
                raise CalculationInputMismatch("Daily discovery requires an idle published account")
        row = session.get(CutoffPreparation, (account_id, target_version, purpose))
        if row is None:
            first = session.scalar(select(func.min(InitialPosition.opened_on)).where(
                InitialPosition.account_id == account_id,
                InitialPosition.initialization_id == account.current_initialization_id))
            start = previous.through_date+timedelta(days=1) if previous else (
                min(first, account.initialized_on) if first else account.initialized_on)
            scan_through = now.astimezone(ZoneInfo("Asia/Shanghai")).date()
            if start > scan_through:
                raise CalculationDataUnavailable("No later business date to inspect")
            row = CutoffPreparation(account_id=account_id, target_version=target_version, purpose=purpose,
                fact_version=account.fact_version, initialization_id=account.current_initialization_id,
                from_date=start, scan_through_date=scan_through,
                current_date=start, state="SCANNING", updated_at=now)
            session.add(row)
            session.flush()
        if (row.fact_version != account.fact_version or row.initialization_id != account.current_initialization_id):
            raise CalculationInputMismatch("Cutoff scan facts changed")
        if row.state == "READY":
            return row.complete_through
        if row.current_date > row.scan_through_date:
            return self._finish_or_wait(row, "尚无已就绪的账户日期", now)
        day = row.current_date
        try:
            calendar = MarketFactsReader(self.policy).read_calendar(session, "SSE", day, day, deadline).days[0]
            self._check_bytes(asdict(calendar))
            valuation_cutoff(day, is_open=calendar.is_open, observed_at=now)
            if calendar.is_open:
                codes = tuple(session.scalars(cutoff_stock_page(account=account, business_date=day,
                    after=row.after_stock, policy=self.policy)))
                if codes:
                    facts = DailyCloseFactsReader(self.policy).read(session, codes, day, deadline)
                    self._check_bytes([asdict(f) for f in facts])
                    if any(f.price is None for f in facts):
                        raise CalculationDataUnavailable("当日账户相关收盘价未就绪")
                    row.after_stock = codes[-1]
                    row.state, row.reason, row.updated_at = "SCANNING", None, now
                    deadline.remaining_ms()
                    raise CutoffPreparationInProgress()
        except (MarketFactsUnavailable, CalculationDataUnavailable):
            return self._finish_or_wait(row, "账户日期所需行情或交易日历未就绪", now)
        row.complete_through, row.current_date = day, day+timedelta(days=1)
        row.after_stock, row.reason, row.updated_at = None, None, now
        if day == row.scan_through_date:
            row.state = "READY"
            return day
        row.state = "SCANNING"
        deadline.remaining_ms()
        raise CutoffPreparationInProgress()

    @staticmethod
    def _finish_or_wait(row, reason, now):
        next_state = "READY" if row.complete_through is not None else "WAITING_DATA"
        if (row.state, row.reason) != (next_state, reason):
            row.updated_at = now
        row.reason, row.state = reason, next_state
        if row.complete_through is not None:
            return row.complete_through
        raise CalculationDataUnavailable(reason)

    def _check_bytes(self, value):
        size = 0
        encoder = json.JSONEncoder(ensure_ascii=False, separators=(",", ":"),
            default=lambda v: v.isoformat() if isinstance(v, date) else str(v))
        for part in encoder.iterencode(value):
            size += len(part.encode("utf-8"))
            if size > self.policy.page_bytes:
                raise CalculationInputMismatch("Cutoff source page exceeds the execution byte budget")
