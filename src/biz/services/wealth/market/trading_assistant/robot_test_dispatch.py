"""Durable test dispatch; commit claim before IO and never reclaim a send."""
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select

from src.biz.models.wealth.trading_assistant.robots import RobotTest, RobotCandidate
from src.biz.models.wealth.trading_assistant.rules import RobotIdentity
from .market_facts import apply_sql_budget
from .feishu_protocol import text_payload
from .message_dispatch import DurableMessageDispatcher


class RobotTestDispatcher(DurableMessageDispatcher):
    def _sweep(self, session, deadline):
        apply_sql_budget(session, deadline, self.policy)
        now = self.now()
        stale = session.scalars(select(RobotTest).where(RobotTest.state == "IN_FLIGHT",
            RobotTest.dispatched_at <= now - timedelta(milliseconds=self.notification_policy.total_timeout_ms))
            .order_by(RobotTest.dispatched_at, RobotTest.test_id).limit(self.policy.page_rows)
            .with_for_update(skip_locked=True)).all()
        for row in stale:
            row.state, row.completed_at, row.reason = "UNKNOWN", now, "发送结果待核对，不会自动重发"
        session.flush()

    def _claim(self, session, deadline):
        apply_sql_budget(session, deadline, self.policy)
        now = self.now()
        candidates = session.execute(select(RobotTest.test_id, RobotTest.robot_id).where(
            RobotTest.state == "IN_FLIGHT", RobotTest.dispatched_at.is_(None))
            .order_by(RobotTest.started_at, RobotTest.test_id).limit(self.policy.page_rows)).all()
        for test_id, robot_id in candidates:
            robot = session.scalar(select(RobotIdentity).where(RobotIdentity.robot_id == robot_id)
                .with_for_update(skip_locked=True).execution_options(populate_existing=True))
            if robot is None or (robot.next_send_not_before is not None and robot.next_send_not_before > now):
                continue
            row = session.scalar(select(RobotTest).where(RobotTest.test_id == test_id)
                .with_for_update().execution_options(populate_existing=True))
            if row.state != "IN_FLIGHT" or row.dispatched_at is not None:
                continue
            row.dispatched_at, row.dispatch_token = now, uuid4()
            robot.next_send_not_before = now + timedelta(milliseconds=self.notification_policy.min_robot_interval_ms)
            session.flush()
            deadline.remaining_ms()
            return row.test_id, row.dispatch_token
        return None

    def _payload(self, session, test_id, token, deadline):
        apply_sql_budget(session, deadline, self.policy)
        row = session.scalar(select(RobotTest).where(RobotTest.test_id == test_id, RobotTest.dispatch_token == token))
        if row is None or row.state != "IN_FLIGHT":
            return None
        candidate = session.scalar(select(RobotCandidate).where(RobotCandidate.owner_user_id == row.owner_user_id,
            RobotCandidate.robot_id == row.robot_id, RobotCandidate.candidate_id == row.candidate_id))
        secret = self.store._secret(session, row.owner_user_id, "CANDIDATE", candidate.candidate_id, candidate.credential_blob_id)
        payload = text_payload("财势乾坤机器人测试通知。请返回配置页面确认收到。", keywords=tuple(candidate.keywords),
            signing_secret=secret["signingSecret"], timestamp=int(self.now().timestamp()))
        deadline.remaining_ms()
        return secret["webhook"], payload

    def _finish(self, session, test_id, token, outcome, deadline):
        apply_sql_budget(session, deadline, self.policy)
        if outcome.state not in {"SUCCEEDED", "FAILED", "UNKNOWN"}:
            raise ValueError("Invalid send outcome")
        row = session.scalar(select(RobotTest).where(RobotTest.test_id == test_id, RobotTest.dispatch_token == token)
            .with_for_update().execution_options(populate_existing=True))
        if row is None or row.state in {"SUCCEEDED", "FAILED"}:
            return
        # A late result may resolve this exact original attempt, never create one.
        row.state, row.completed_at, row.reason = outcome.state, self.now(), outcome.reason
        session.flush()
