"""Owner-bound test evidence reads; never decrypt, resend or advance state."""
from sqlalchemy import select

from src.biz.models.wealth.trading_assistant.robots import RobotTest
from src.biz.schemas.wealth.market.trading_assistant.robot import TestResult
from src.biz.services.wealth.market.trading_assistant.market_facts import apply_sql_budget
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocolConflict
from .rule_projection import instant


class RobotTestQuery:
    def __init__(self, policy):
        self.policy = policy

    def read(self, session, *, owner_id, candidate_id, test_id, deadline):
        apply_sql_budget(session, deadline, self.policy)
        row = session.scalar(select(RobotTest).where(
            RobotTest.owner_user_id == owner_id,
            RobotTest.candidate_id == candidate_id,
            RobotTest.test_id == test_id))
        if row is None:
            raise WriteProtocolConflict("TA_OBJECT_NOT_FOUND")
        deadline.remaining_ms()
        # reason is application-owned sanitized evidence, never an HTTP body.
        return TestResult(testId=str(row.test_id), state=row.state,
            startedAt=instant(row.started_at), completedAt=instant(row.completed_at), reason=row.reason)
