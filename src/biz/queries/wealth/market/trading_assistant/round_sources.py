"""Fixed-publication round identities and endpoints; number before range filtering."""
from uuid import UUID

from sqlalchemy import and_, false, func, or_, select

from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration, DayResult, PositionState
from src.biz.models.wealth.trading_assistant.publication import PublicationDay


def published_rounds(basis):
    pub, position, generation = PublicationDay, PositionState, CalculationGeneration
    references = [and_(generation.account_id == UUID(ref.accountId),
        generation.generation_id == UUID(ref.publishedGenerationId),
        generation.fact_version == int(ref.factVersion),
        generation.target_version == int(ref.calculationTargetVersion))
        for ref in basis.context.accounts if ref.publishedGenerationId]
    days = select(pub.account_id, pub.generation_id, pub.trade_date, pub.day_result_id,
        position.ts_code, position.round_id, position.opened_on, position.closed_on,
        position.quantity, position.cumulative_buy_input, position.cumulative_sell_net,
        func.row_number().over(partition_by=(pub.account_id, position.round_id),
            order_by=pub.trade_date.desc()).label("ending_rank")
    ).select_from(pub).join(generation, and_(generation.account_id == pub.account_id,
        generation.generation_id == pub.generation_id, generation.stage == "PUBLISHED")
    ).join(DayResult, and_(DayResult.account_id == pub.account_id,
        DayResult.day_result_id == pub.day_result_id, DayResult.trade_date == pub.trade_date,
        DayResult.status == "SEALED")
    ).join(position, and_(position.account_id == pub.account_id,
        position.day_result_id == pub.day_result_id)
    ).where(or_(*references) if references else false()).subquery("round_days")
    # The final day contains the cumulative amounts, including a zero-quantity
    # closing row. Never SUM repeated daily cumulative amounts.
    return select(days, func.row_number().over(
        partition_by=(days.c.account_id, days.c.ts_code),
        order_by=(days.c.opened_on, days.c.round_id)).label("round_number")
    ).where(days.c.ending_rank == 1).subquery("published_rounds")
