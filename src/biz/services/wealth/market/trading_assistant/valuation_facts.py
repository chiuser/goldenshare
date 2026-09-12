"""Bounded daily-close facts for M3, design §4.34.

This reader does not publish results or silently carry yesterday's price. The
suspension path requires separate positive evidence before it may supply a price.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from fractions import Fraction

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from .execution_policy import Deadline, TradingAssistantExecutionPolicyV1
from .market_facts import apply_sql_budget, facts_digest


@dataclass(frozen=True, slots=True)
class DailyCloseFact:
    ts_code: str
    valuation_date: date
    price_date: date | None
    price_text: str | None
    source: str | None
    source_version: str
    reason: str | None
    suspension_evidence: str | None = None

    @property
    def price(self) -> Fraction | None:
        return Fraction(self.price_text) if self.price_text is not None else None


class DailyCloseFactsReader:
    def __init__(self, policy: TradingAssistantExecutionPolicyV1):
        self.policy = policy

    def read(self, session: Session, ts_codes: tuple[str, ...], trade_date: date,
             deadline: Deadline) -> tuple[DailyCloseFact, ...]:
        if (type(trade_date) is not date or len(ts_codes) > self.policy.page_rows
                or any(type(code) is not str or not code or len(code) > 16 for code in ts_codes)
                or len(set(ts_codes)) != len(ts_codes)):
            raise ValueError("Expected a unique, bounded stock page and business date")
        deadline.remaining_ms()
        if not ts_codes:
            return ()
        apply_sql_budget(session, deadline, self.policy)
        rows = session.execute(select(EquityDailyBar.ts_code, EquityDailyBar.close, EquityDailyBar.source)
            .where(EquityDailyBar.ts_code.in_(ts_codes), EquityDailyBar.trade_date == trade_date)
            .order_by(EquityDailyBar.ts_code).limit(len(ts_codes))).all()
        deadline.remaining_ms()
        by_code = {row.ts_code: row for row in rows}
        from .suspension_facts import read_suspension_carries
        carries = read_suspension_carries(session, tuple(code for code in ts_codes if code not in by_code),
                                         trade_date, self.policy, deadline)
        facts = []
        for code in sorted(ts_codes):
            if code in carries:
                price_date, price_text, evidence, version = carries[code]
                facts.append(DailyCloseFact(code, trade_date, price_date, price_text,
                    "tushare", version, None, evidence))
                continue
            row = by_code.get(code)
            close = row.close if row is not None else None
            source = row.source if row is not None else None
            valid = (isinstance(close, Decimal) and close.is_finite() and close > 0
                     and source == "tushare")
            # Retain the actual decimal source precision; never format to cents.
            price_text = format(close, "f") if valid else None
            snapshot = {"table": "core_serving.equity_daily_bar", "tsCode": code,
                        "valuationDate": trade_date.isoformat(), "source": source,
                        "observedClose": str(close) if close is not None else None,
                        "price": price_text}
            facts.append(DailyCloseFact(code, trade_date, trade_date if valid else None,
                price_text, source, facts_digest(snapshot),
                None if valid else "当日有效收盘价未就绪"))
        deadline.remaining_ms()
        return tuple(facts)
