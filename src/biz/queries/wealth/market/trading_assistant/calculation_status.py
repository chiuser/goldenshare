"""Read committed progress for the current target only; never claim work."""
from sqlalchemy import and_, select

from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration, DayResult, Recalculation
from src.biz.models.wealth.trading_assistant.publication import PublicationReceipt
from src.biz.schemas.wealth.market.trading_assistant.calculation_status import CalculationProgress, CalculationStatus
from src.biz.services.wealth.market.trading_assistant.account_acceptance import accepted_time
from src.biz.services.wealth.market.trading_assistant.market_facts import apply_sql_budget
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocolConflict


class CalculationStatusQuery:
    def __init__(self, policy):
        self.policy = policy

    def read(self, session, *, owner_id, account_id, deadline):
        apply_sql_budget(session, deadline, self.policy)
        found = session.execute(select(Account, Recalculation, CalculationGeneration).outerjoin(Recalculation,
            Recalculation.account_id == Account.account_id).outerjoin(CalculationGeneration,
            and_(CalculationGeneration.account_id == Account.account_id,
                 CalculationGeneration.target_version == Account.calculation_target_version)).where(
            Account.owner_id == owner_id, Account.account_id == account_id)).one_or_none()
        if found is None:
            raise WriteProtocolConflict("TA_ACCOUNT_NOT_FOUND")
        account, pending, generation = found
        if pending and pending.target_version != account.calculation_target_version:
            raise ValueError("Pending calculation target differs from account")
        progress = CalculationProgress(completedTradeDateCount=0,totalTradeDateCount=None,
            currentTradeDate=None,lastCompletedTradeDate=None,lastBusinessUpdatedAt=None)
        stage, reason = "PENDING", None
        if generation:
            if generation.fact_version != account.fact_version:
                raise ValueError("Current generation does not match accepted facts")
            stage, reason = generation.stage, generation.reason
            current = session.scalars(select(DayResult.trade_date).where(
                DayResult.account_id == account_id, DayResult.origin_generation_id == generation.generation_id,
                DayResult.status == "BUILDING").order_by(DayResult.trade_date).limit(2)).all()
            if len(current) > 1:
                raise ValueError("More than one unfinished day in a sequential generation")
            progress = CalculationProgress(completedTradeDateCount=generation.completed_trade_date_count,
                totalTradeDateCount=generation.total_trade_date_count,
                currentTradeDate=current[0].isoformat() if current else None,
                lastCompletedTradeDate=generation.last_completed_trade_date.isoformat() if generation.last_completed_trade_date else None,
                lastBusinessUpdatedAt=accepted_time(generation.last_business_updated_at))
            if stage == "PUBLISHED":
                receipt = session.get(PublicationReceipt,(account_id,generation.generation_id))
                if (account.published_generation_id != generation.generation_id or receipt is None
                        or receipt.target_version != account.calculation_target_version or pending is not None):
                    raise ValueError("Published state lacks current atomic publication evidence")
        deadline.remaining_ms()
        return CalculationStatus(accountId=str(account_id),
            calculationTargetVersion=str(account.calculation_target_version),
            publishedGenerationId=str(account.published_generation_id) if account.published_generation_id else None,
            affectedFromDate=pending.affected_from_date.isoformat() if pending else None,
            stage=stage,progress=progress,reason=reason)
