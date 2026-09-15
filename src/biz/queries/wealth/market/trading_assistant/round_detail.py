"""Complete round facts, never clipped to the parent review's date range."""
from uuid import UUID, uuid5

from sqlalchemy import and_, func, select

from src.biz.models.wealth.trading_assistant.accounts import Account, Initialization, InitialPosition
from src.biz.models.wealth.trading_assistant.calculation import PositionState
from src.biz.models.wealth.trading_assistant.publication import PublicationDay
from src.biz.schemas.wealth.market.trading_assistant.common import AccountCoverage, AccountRef, Coverage, StockRef
from src.biz.schemas.wealth.market.trading_assistant.records import RoundDetail, RoundDetailResponse
from src.biz.services.wealth.market.trading_assistant.calculation.precision import format_cents
from src.biz.services.wealth.market.trading_assistant.calculation.returns import profit_result
from src.biz.services.wealth.market.trading_assistant.market_facts import apply_sql_budget
from src.biz.services.wealth.market.trading_assistant.persistence_values import numeric_cents
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocolConflict
from .calculation_status import CalculationStatusQuery
from .record_scope import read_record_names
from .record_sources import record_facts, with_published_closed
from .round_sources import published_rounds


class RoundDetailQuery:
    def __init__(self, policy):
        self.policy = policy
        self.status = CalculationStatusQuery(policy)

    def read(self, session, *, owner_id, basis, account_id, round_id, cutoff, deadline):
        if len(basis.context.accounts) != 1 or basis.context.accounts[0].accountId != str(account_id):
            raise WriteProtocolConflict("TA_ACCOUNT_NOT_FOUND")
        apply_sql_budget(session, deadline, self.policy)
        account = session.scalar(select(Account).where(Account.owner_id == owner_id, Account.account_id == account_id))
        if account is None:
            raise WriteProtocolConflict("TA_ACCOUNT_NOT_FOUND")
        # An unavailable result is still an existing owned object. Only identity
        # may be checked in the older fixed publication, never its financials.
        ref = basis.context.accounts[0]
        apply_sql_budget(session, deadline, self.policy)
        exists = session.scalar(select(PositionState.round_id).join(PublicationDay, and_(
            PublicationDay.account_id == PositionState.account_id,
            PublicationDay.day_result_id == PositionState.day_result_id)).where(
            PublicationDay.account_id == account_id,
            PublicationDay.generation_id == (UUID(ref.publishedGenerationId) if ref.publishedGenerationId else None),
            PositionState.round_id == round_id).limit(1))
        if exists is None:
            raise WriteProtocolConflict("TA_OBJECT_NOT_FOUND")
        progress = self.status.read(session, owner_id=owner_id, account_id=account_id, deadline=deadline)
        if progress.stage != "PUBLISHED":
            state = "Error" if progress.stage == "FAILED" else "Delayed" if progress.stage == "WAITING_DATA" else "Recalculating"
            reason = progress.reason or "本轮结果尚未完成核算发布"
            cover = AccountCoverage(accountId=str(account_id), initializedOn=account.initialized_on.isoformat(),
                effectiveStartDate=None, targetThroughDate=None, calculatedThroughDate=None, valuationAt=None,
                dataStatus=state, reason=reason)
            return RoundDetailResponse(readContext=basis.context,
                coverage=Coverage(dataStatus=state, reason=reason, isFinal=False, accounts=[cover]), detail=None)
        rounds = published_rounds(basis)
        apply_sql_budget(session, deadline, self.policy)
        row = session.execute(select(rounds).where(rounds.c.account_id == account_id, rounds.c.round_id == round_id)).one_or_none()
        if row is None:
            raise WriteProtocolConflict("TA_OBJECT_NOT_FOUND")
        if row.closed_on is None and (cutoff.valuation_date is None or row.trade_date < cutoff.valuation_date):
            # A generation may validly publish only a priced prefix. PUBLISHED
            # alone does not mean this open round reaches the requested cutoff.
            reason = "本轮最新结果尚未计算到读取截止"
            cover = AccountCoverage(accountId=str(account_id), initializedOn=account.initialized_on.isoformat(),
                effectiveStartDate=row.opened_on.isoformat(),
                targetThroughDate=(cutoff.valuation_date or cutoff.today).isoformat(),
                calculatedThroughDate=row.trade_date.isoformat(), valuationAt=None, dataStatus="Delayed", reason=reason)
            return RoundDetailResponse(readContext=basis.context,
                coverage=Coverage(dataStatus="Delayed", reason=reason, isFinal=False, accounts=[cover]), detail=None)
        apply_sql_budget(session, deadline, self.policy)
        initial = session.execute(select(InitialPosition, Initialization.revision).join(Initialization, and_(
            Initialization.account_id == InitialPosition.account_id,
            Initialization.initialization_id == InitialPosition.initialization_id)).where(
            InitialPosition.account_id == account_id, InitialPosition.initialization_id == account.current_initialization_id,
            InitialPosition.ts_code == row.ts_code)).one_or_none()
        source = None
        initial_quantity, initial_cost = 0, 0
        if initial and round_id == uuid5(account_id, f"INITIAL:{account.current_initialization_id}:{row.ts_code}"):
            position, revision = initial
            initial_quantity = position.quantity
            initial_cost = numeric_cents(position.cost_price) * initial_quantity
            source = dict(initializedOn=account.initialized_on.isoformat(), openedOn=position.opened_on.isoformat(),
                initializationId=str(position.initialization_id), initializationRevision=str(revision),
                quantity=initial_quantity, costPrice=format_cents(numeric_cents(position.cost_price)),
                costAmount=format_cents(initial_cost))
        facts = record_facts(owner_id=owner_id, basis=basis)
        apply_sql_budget(session, deadline, self.policy)
        trades = session.execute(select(facts.c.direction, func.sum(facts.c.quantity), func.sum(facts.c.net_cash_change))
            .where(facts.c.kind == "TRADE", facts.c.ts_code == row.ts_code,
                facts.c.occurred_on >= row.opened_on, facts.c.occurred_on <= row.trade_date)
            .group_by(facts.c.direction)).all()
        quantities = {direction: int(quantity) for direction, quantity, _ in trades}
        cash = {direction: numeric_cents(amount) for direction, _, amount in trades}
        buys, sells = initial_quantity + quantities.get("BUY", 0), quantities.get("SELL", 0)
        investment, proceeds = initial_cost - cash.get("BUY", 0), cash.get("SELL", 0)
        if (buys - sells != int(row.quantity) or investment != numeric_cents(row.cumulative_buy_input)
                or proceeds != numeric_cents(row.cumulative_sell_net)):
            raise ValueError("Complete round does not reconcile with effective facts")
        closed = with_published_closed(facts)
        apply_sql_budget(session, deadline, self.policy)
        count, allocated, profit = session.execute(select(func.count(), func.sum(closed.c.allocated_cost),
            func.sum(closed.c.closed_profit_amount)).where(closed.c.round_id == round_id)).one()
        result = None
        if row.closed_on is not None:
            if (buys != sells or numeric_cents(allocated) != investment
                    or numeric_cents(profit) != proceeds - investment):
                raise ValueError("Closed round does not reconcile with its closed sales")
            result = profit_result(proceeds - investment, investment, participates=True)
        names = read_record_names(session, [row.ts_code], deadline=deadline, policy=self.policy)
        detail = RoundDetail(accountRef=AccountRef(accountId=str(account_id), name=account.name, brokerName=account.broker_name),
            stockRef=StockRef(tsCode=row.ts_code, name=names[row.ts_code]),
            roundRef=dict(accountId=str(account_id), roundId=str(round_id), roundNumber=row.round_number,
                status="CLOSED" if row.closed_on else "OPEN"),
            openedOn=row.opened_on.isoformat(), closedOn=row.closed_on.isoformat() if row.closed_on else None,
            openingSource="INITIALIZATION" if source else "TRADE", initializationSource=source,
            buyQuantity=str(buys), sellQuantity=str(sells), buyInvestmentAmount=format_cents(investment),
            sellNetProceedsAmount=format_cents(proceeds), roundProfitAmount=format_cents(result.profit_cents) if result else None,
            roundReturnPct=result.return_pct if result else None, closedTradeCount=count,
            recordsScope=dict(accountId=str(account_id), roundId=str(round_id)))
        cover = AccountCoverage(accountId=str(account_id), initializedOn=account.initialized_on.isoformat(),
            effectiveStartDate=row.opened_on.isoformat(), targetThroughDate=row.trade_date.isoformat(),
            calculatedThroughDate=row.trade_date.isoformat(), valuationAt=None, dataStatus="Ready", reason=None)
        deadline.remaining_ms()
        return RoundDetailResponse(readContext=basis.context,
            coverage=Coverage(dataStatus="Ready", reason=None, isFinal=True, accounts=[cover]), detail=detail)
