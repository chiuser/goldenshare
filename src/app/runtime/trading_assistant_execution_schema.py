"""Read-only readiness of the private tables consumed by M3 execution."""
from sqlalchemy import select, text

from src.biz.models.wealth.trading_assistant.accounts import Account, FeeVersion, Initialization, InitialPosition
from src.biz.models.wealth.trading_assistant.ledger import Ledger, LedgerRevision
from src.biz.models.wealth.trading_assistant.calculation import Recalculation, CalculationGeneration, DayResult, PositionState, ClosedTrade
from src.biz.models.wealth.trading_assistant.calculation_inputs import ValuationBasis, CalculationBatch, CutoffPreparation, CutoffDiscoveryCursor
from src.biz.models.wealth.trading_assistant.publication import AccountSnapshot, PublicationDay, PublicationReceipt
from src.biz.services.wealth.market.trading_assistant.execution_policy import Deadline
from src.biz.services.wealth.market.trading_assistant.market_facts import apply_sql_budget


def verify_execution_schema(sessions, policy):
    deadline = Deadline.after_ms(policy.batch_budget_ms)
    models = (Account, FeeVersion, Initialization, InitialPosition, Ledger, LedgerRevision,
        Recalculation, CalculationGeneration, DayResult, PositionState, ClosedTrade,
        ValuationBasis, CalculationBatch, CutoffPreparation, CutoffDiscoveryCursor,
        AccountSnapshot, PublicationDay, PublicationReceipt)
    with sessions() as session, session.begin():
        session.execute(text("SET TRANSACTION READ ONLY"))
        apply_sql_budget(session, deadline, policy)
        for model in models:
            deadline.remaining_ms()
            session.execute(select(model).limit(0)).close()
        if tuple(session.scalars(select(CutoffDiscoveryCursor.singleton_id)
                .order_by(CutoffDiscoveryCursor.singleton_id))) != (1, 2):
            raise RuntimeError("Trading-assistant discovery cursors require the matching migration")
        deadline.remaining_ms()
    return "READY"
