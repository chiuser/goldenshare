"""Bounded account-day facts from a fixed publication, not a coverage verdict."""
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import and_, select

from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration, DayResult
from src.biz.models.wealth.trading_assistant.publication import AccountSnapshot, PublicationDay
from src.biz.services.wealth.market.trading_assistant.calculation.returns import profit_result
from src.biz.services.wealth.market.trading_assistant.market_facts import apply_sql_budget
from src.biz.services.wealth.market.trading_assistant.persistence_values import numeric_cents
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocolConflict
from .read_context import OwnedReadContext
from .return_statistics import DailyReturnFact


class PublishedReturnsUnavailable(RuntimeError):
    """The fixed account basis has no compatible published return facts."""


@dataclass(frozen=True, slots=True)
class PublishedReturnDay:
    fact: DailyReturnFact
    day_result_id: UUID
    valuation_at: datetime
    cash_cents: int | None
    closed_count: int
    closed_profit_cents: int


@dataclass(frozen=True, slots=True)
class PublishedReturnPage:
    items: tuple[PublishedReturnDay, ...]
    next_date: date | None


class PublishedReturnDaysQuery:
    def __init__(self, policy):
        self.policy = policy

    def page(self, session, *, basis: OwnedReadContext, account_id: UUID, start: date, end: date,
             deadline, after: date | None = None) -> PublishedReturnPage:
        if (type(start) is not date or type(end) is not date or start > end
                or (after is not None and (type(after) is not date or not start <= after <= end))):
            raise ValueError("Invalid published return date window")
        ref = next((ref for ref in basis.context.accounts if ref.accountId == str(account_id)), None)
        if ref is None:
            raise WriteProtocolConflict("TA_ACCOUNT_NOT_FOUND")
        if ref.publishedGenerationId is None:
            raise PublishedReturnsUnavailable("账户收益尚未发布")
        generation_id = UUID(ref.publishedGenerationId)
        apply_sql_budget(session, deadline, self.policy)
        generation = session.execute(select(CalculationGeneration.fact_version,
            CalculationGeneration.target_version, CalculationGeneration.stage).where(
            CalculationGeneration.account_id == account_id,
            CalculationGeneration.generation_id == generation_id)).one_or_none()
        if generation is None or tuple(generation) != (int(ref.factVersion), int(ref.calculationTargetVersion), "PUBLISHED"):
            raise PublishedReturnsUnavailable("当前事实尚未完成核算发布")
        # Outer joins deliberately expose broken manifests; they must not silently
        # disappear as if the account had no expected result for that date.
        query = select(PublicationDay.trade_date, DayResult.status, AccountSnapshot).select_from(
            PublicationDay).outerjoin(DayResult, and_(
                DayResult.account_id == PublicationDay.account_id,
                DayResult.day_result_id == PublicationDay.day_result_id,
                DayResult.trade_date == PublicationDay.trade_date)).outerjoin(AccountSnapshot, and_(
                AccountSnapshot.account_id == PublicationDay.account_id,
                AccountSnapshot.day_result_id == PublicationDay.day_result_id,
                AccountSnapshot.trade_date == PublicationDay.trade_date)).where(
            PublicationDay.account_id == account_id, PublicationDay.generation_id == generation_id,
            PublicationDay.trade_date >= start, PublicationDay.trade_date <= end)
        if after is not None:
            query = query.where(PublicationDay.trade_date > after)
        apply_sql_budget(session, deadline, self.policy)
        rows = session.execute(query.order_by(PublicationDay.trade_date).limit(self.policy.page_rows + 1)).all()
        through = datetime.fromisoformat(basis.context.targetThrough.replace("Z", "+00:00"))
        items = []
        for day, status, snapshot in rows[:self.policy.page_rows]:
            if status != "SEALED" or snapshot is None:
                raise ValueError("Published manifest lacks a sealed account snapshot")
            if snapshot.valuation_at > through:
                raise PublishedReturnsUnavailable("日收益估值晚于读取截止")
            triple = (snapshot.day_profit_amount, snapshot.day_capital_amount, snapshot.day_return_pct)
            if any(v is None for v in triple) and not all(v is None for v in triple):
                raise ValueError("Published day has an incomplete return triple")
            participates = snapshot.day_capital_amount is not None
            result = profit_result(numeric_cents(snapshot.day_profit_amount) if participates else 0,
                numeric_cents(snapshot.day_capital_amount) if participates else 0, participates=participates)
            items.append(PublishedReturnDay(DailyReturnFact(day, result), snapshot.day_result_id,
                snapshot.valuation_at, numeric_cents(snapshot.cash_amount) if snapshot.cash_amount is not None else None,
                snapshot.closed_trade_count, numeric_cents(snapshot.closed_profit_amount)))
        deadline.remaining_ms()
        return PublishedReturnPage(tuple(items), items[-1].fact.day if len(rows) > self.policy.page_rows else None)
