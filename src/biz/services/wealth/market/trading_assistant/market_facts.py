"""Bounded source facts consumed by pre-acceptance validation, design §4.34.

These are read facts, not a new data producer or cached ownership/valuation state.
The content digest identifies the actual facts that must be retained in a candidate.
"""
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import json

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from src.foundation.models.core_serving.security_serving import Security
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.biz.services.wealth.market.stock_search.stock_search_policy import A_SHARE_EXCHANGES
from .execution_policy import Deadline, TradingAssistantExecutionPolicyV1


class MarketFactsUnavailable(RuntimeError):
    """Missing source evidence must not be interpreted as closed/open by guessing."""


class SecurityNotEligible(ValueError):
    def __init__(self, message: str, *, ts_code: str | None = None):
        super().__init__(message)
        self.ts_code = ts_code


@dataclass(frozen=True, slots=True)
class SecurityFact:
    ts_code: str
    name: str
    exchange: str
    source: str
    source_version: str


@dataclass(frozen=True, slots=True)
class CalendarFact:
    trade_date: date
    is_open: bool
    previous_trade_date: date | None


@dataclass(frozen=True, slots=True)
class CalendarBasis:
    exchange: str
    calendar_exchange: str
    from_date: date
    through_date: date
    days: tuple[CalendarFact, ...]
    source_version: str


def facts_digest(value) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()).hexdigest()


def apply_sql_budget(session: Session, deadline: Deadline, policy: TradingAssistantExecutionPolicyV1):
    # Transaction-local only. Connection acquisition must already obey the same deadline.
    session.execute(text("SELECT set_config('statement_timeout', :timeout, true), "
                         "set_config('lock_timeout', :lock_timeout, true)"),
                    {"timeout":str(deadline.bounded_ms(policy.sql_timeout_ms)),
                     "lock_timeout":str(deadline.bounded_ms(policy.lock_timeout_ms))})


class MarketFactsReader:
    def __init__(self, policy: TradingAssistantExecutionPolicyV1):
        self.policy = policy

    def resolve_security(self, session: Session, ts_code: str, deadline: Deadline) -> SecurityFact:
        apply_sql_budget(session, deadline, self.policy)
        row = session.execute(select(Security.ts_code, Security.name, Security.exchange,
                                     Security.security_type, Security.curr_type, Security.source).where(Security.ts_code == ts_code)).one_or_none()
        deadline.remaining_ms()
        if row is None or row.exchange not in A_SHARE_EXCHANGES or row.security_type != "EQUITY":
            raise SecurityNotEligible("股票代码必须对应唯一的 A 股股票", ts_code=ts_code)
        if row.curr_type is None:
            raise MarketFactsUnavailable("证券币种资料不完整")
        if row.curr_type != "CNY":
            raise SecurityNotEligible("仅支持人民币 A 股股票", ts_code=ts_code)
        if not row.name or not row.source:
            raise MarketFactsUnavailable("证券身份资料不完整")
        snapshot = dict(row._mapping)
        return SecurityFact(row.ts_code, row.name, row.exchange, row.source, facts_digest(snapshot))

    def read_calendar(self, session: Session, exchange: str, from_date: date,
                      through_date: date, deadline: Deadline) -> CalendarBasis:
        if exchange not in A_SHARE_EXCHANGES or from_date > through_date:
            raise ValueError("Invalid calendar request")
        expected = (through_date - from_date).days + 1
        if expected > self.policy.page_rows:
            raise ValueError("Caller must page calendar windows within the execution budget")
        apply_sql_budget(session, deadline, self.policy)
        rows = session.execute(select(TradeCalendar.trade_date, TradeCalendar.is_open, TradeCalendar.pretrade_date)
            .where(TradeCalendar.exchange == "SSE", TradeCalendar.trade_date >= from_date,
                   TradeCalendar.trade_date <= through_date).order_by(TradeCalendar.trade_date)
            .limit(expected + 1)).all()
        deadline.remaining_ms()
        # The PK prevents duplicates; count + bounds prove every civil day is represented.
        if len(rows) != expected:
            raise MarketFactsUnavailable("交易日历日期覆盖不完整，不能确认可卖数量")
        facts = tuple(CalendarFact(r.trade_date, r.is_open, r.pretrade_date) for r in rows)
        for fact in facts:
            if type(fact.is_open) is not bool or (fact.previous_trade_date is not None
                                                and fact.previous_trade_date >= fact.trade_date):
                raise MarketFactsUnavailable("交易日历事实不一致")
        snapshot = [[f.trade_date.isoformat(), f.is_open,
                     f.previous_trade_date.isoformat() if f.previous_trade_date else None] for f in facts]
        return CalendarBasis(exchange, "SSE", from_date, through_date, facts,
                             facts_digest({"calendar_exchange":"SSE","days":snapshot}))
