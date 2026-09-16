"""Owner-bound notification detail; immutable config name per attempt."""
from sqlalchemy import select, func
from src.biz.models.wealth.trading_assistant.rule_notifications import TriggerNotification
from src.biz.models.wealth.trading_assistant.notification_attempts import NotificationAttempt
from src.biz.models.wealth.trading_assistant.rules import RobotIdentity
from src.biz.models.wealth.trading_assistant.robots import RobotConfig
from src.biz.schemas.wealth.market.trading_assistant.robot import NotificationDetail
from src.biz.services.wealth.market.trading_assistant.market_facts import apply_sql_budget
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocolConflict
from .rule_cursor import RuleCursor
from .rule_projection import instant


class NotificationQuery:
    def __init__(self, policy):
        self.policy = policy

    def read(self, session, *, owner_id, notification_id, query, now, deadline):
        apply_sql_budget(session, deadline, self.policy)
        row = session.scalar(select(TriggerNotification).where(TriggerNotification.owner_user_id == owner_id,
            TriggerNotification.notification_id == notification_id))
        if row is None:
            raise WriteProtocolConflict("TA_OBJECT_NOT_FOUND")
        current = session.scalar(select(RobotConfig).join(RobotIdentity,
            (RobotIdentity.robot_id == RobotConfig.robot_id) & (RobotIdentity.owner_user_id == RobotConfig.owner_user_id) &
            (RobotIdentity.current_config_id == RobotConfig.config_id)).where(RobotIdentity.owner_user_id == owner_id,
                RobotIdentity.robot_id == row.robot_id))
        if current is None:
            raise RuntimeError("Notification robot has no confirmed configuration")
        cursor = RuleCursor(owner_id=owner_id, kind="NOTIFICATION", filters=dict(notificationId=str(notification_id)))
        after = cursor.decode(query.cursor, history=True)
        ceiling = after[1] if after else (session.scalar(select(func.max(NotificationAttempt.attempt_no)).where(
            NotificationAttempt.owner_user_id == owner_id, NotificationAttempt.notification_id == notification_id)) or 0)
        statement = select(NotificationAttempt, RobotConfig.name).join(RobotConfig,
            (RobotConfig.owner_user_id == NotificationAttempt.owner_user_id) &
            (RobotConfig.robot_id == NotificationAttempt.robot_id) & (RobotConfig.config_id == NotificationAttempt.config_id))
        statement = statement.where(NotificationAttempt.owner_user_id == owner_id,
            NotificationAttempt.notification_id == notification_id, NotificationAttempt.attempt_no <= ceiling)
        if after:
            statement = statement.where(NotificationAttempt.attempt_no < after[0])
        items = session.execute(statement.order_by(NotificationAttempt.attempt_no.desc()).limit(query.limit + 1)).all()
        more, items = len(items) > query.limit, items[:query.limit]
        latest = session.scalar(select(NotificationAttempt).where(NotificationAttempt.owner_user_id == owner_id,
            NotificationAttempt.notification_id == notification_id, NotificationAttempt.attempt_id == row.latest_attempt_id))
        retry = row.state == "FAILED" and latest is not None and latest.outcome == "FAILED"
        reason = latest.reason if latest else None
        deadline.remaining_ms()
        return NotificationDetail(notificationId=str(row.notification_id), triggerId=str(row.trigger_id),
            ruleVersionId=str(row.rule_version_id), state=row.state, stateVersion=str(row.state_version),
            robotId=str(row.robot_id), robotName=current.name, canRetry=retry, reason=reason, observedAt=instant(now),
            nextCursor=cursor.encode([items[-1][0].attempt_no, ceiling]) if more else None,
            items=[dict(attemptId=str(a.attempt_id), attemptNo=a.attempt_no, robotConfigVersionId=str(a.config_id),
                robotName=name, startedAt=instant(a.started_at), completedAt=instant(a.completed_at),
                outcome=a.outcome, reason=a.reason) for a, name in items])
