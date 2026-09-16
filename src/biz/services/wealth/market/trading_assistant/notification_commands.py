"""Accept an explicit retry atomically; never perform network IO."""
import asyncio
from uuid import UUID
from sqlalchemy import select
from src.biz.models.wealth.trading_assistant.rules import RobotIdentity
from src.biz.models.wealth.trading_assistant.robots import RobotConfig
from src.biz.models.wealth.trading_assistant.rule_notifications import TriggerNotification
from src.biz.models.wealth.trading_assistant.notification_attempts import NotificationAttempt
from src.biz.schemas.wealth.market.trading_assistant.scopes import NotificationScope
from src.biz.schemas.wealth.market.trading_assistant.recovery import RecoveryRejection
from .write_protocol import WriteProtocol, WriteProtocolConflict
from .execution_policy import Deadline
from .transaction_boundary import CommitOutcomeUnknown


class NotificationCommands:
    def __init__(self, transactions, policy, now, executor_id):
        self.transactions, self.policy, self.now, self.executor_id = transactions, policy, now, executor_id
        self.protocol = WriteProtocol(policy)

    async def retry(self, *, owner_id, notification_id, command):
        deadline = Deadline.after_ms(self.policy.write_request_budget_ms)
        state = await self.transactions.run(lambda s: self.protocol.register(s, owner_id=owner_id,
            request_id=UUID(command.requestId), attempt_id=UUID(command.attemptId),
            scope=NotificationScope(scopeType="NOTIFICATION", notificationId=str(notification_id)),
            operation="NOTIFICATION_RETRY", payload=dict(expectedStateVersion=command.expectedStateVersion),
            now=self.now(), executor_id=self.executor_id, deadline=deadline,
            expected_state_version=int(command.expectedRequestStateVersion) if command.expectedRequestStateVersion else None),
            deadline=deadline, write=True)
        if not state.execute:
            return state
        try:
            def accept(session):
                now = self.now()
                locked = self.protocol.lock_execution(session, state, now=now, executor_id=self.executor_id, deadline=deadline)
                reference = session.scalar(select(TriggerNotification).where(TriggerNotification.owner_user_id == owner_id,
                    TriggerNotification.notification_id == notification_id))
                if reference is None:
                    raise WriteProtocolConflict("TA_OBJECT_NOT_FOUND")
                robot = session.scalar(select(RobotIdentity).where(RobotIdentity.owner_user_id == owner_id,
                    RobotIdentity.robot_id == reference.robot_id).with_for_update().execution_options(populate_existing=True))
                row = session.scalar(select(TriggerNotification).where(TriggerNotification.notification_id == notification_id)
                    .with_for_update().execution_options(populate_existing=True))
                latest = session.scalar(select(NotificationAttempt).where(NotificationAttempt.owner_user_id == owner_id,
                    NotificationAttempt.notification_id == notification_id, NotificationAttempt.attempt_id == row.latest_attempt_id))
                if (robot is None or robot.current_config_id is None or row.state != "FAILED"
                        or row.state_version != int(command.expectedStateVersion) or latest is None or latest.outcome != "FAILED"):
                    raise WriteProtocolConflict("TA_STATE_CONFLICT")
                if session.scalar(select(RobotConfig.config_id).where(RobotConfig.owner_user_id == owner_id,
                        RobotConfig.robot_id == robot.robot_id, RobotConfig.config_id == robot.current_config_id)) is None:
                    raise WriteProtocolConflict("TA_STATE_CONFLICT")
                row.state, row.state_version = "PENDING", row.state_version + 1
                row.accepted_retry_request_id = UUID(command.requestId)
                session.flush()
                self.protocol.lock_execution(session, state, now=self.now(), executor_id=self.executor_id, deadline=deadline)
                return self.protocol.saved(session, locked, dict(requestId=command.requestId, attemptId=command.attemptId,
                    operationType="NOTIFICATION_RETRY", acceptedAt=now.isoformat(), result=dict(
                        notificationId=str(notification_id), stateVersion=str(row.state_version), state="PENDING")), now)
            return await self.transactions.run(accept, deadline=deadline, write=True)
        except (CommitOutcomeUnknown, asyncio.CancelledError):
            raise
        except Exception as error:
            rejection = RecoveryRejection(code=error.code if isinstance(error, WriteProtocolConflict) else "TA_WRITE_FAILED",
                message="通知状态已变化或接纳未完成，请重新核对", field=None)
            def stop(session):
                now = self.now()
                locked = self.protocol.lock_execution(session, state, now=now, executor_id=self.executor_id, deadline=deadline)
                return self.protocol.stop(session, locked, rejection, now)
            return await self.transactions.run(stop, deadline=deadline, write=True)
