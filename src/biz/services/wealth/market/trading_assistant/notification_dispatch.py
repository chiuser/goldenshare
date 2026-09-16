"""Freeze actual config/content before IO. No auto retry or trigger mutation."""
from datetime import timedelta
from hashlib import sha256
from uuid import uuid4
from zoneinfo import ZoneInfo
from sqlalchemy import select, func

from src.biz.models.wealth.trading_assistant.rules import RobotIdentity, RuleVersion
from src.biz.models.wealth.trading_assistant.robots import RobotConfig
from src.biz.models.wealth.trading_assistant.rule_checks import RuleResult
from src.biz.models.wealth.trading_assistant.rule_notifications import TriggerNotification
from src.biz.models.wealth.trading_assistant.notification_attempts import NotificationAttempt
from .message_dispatch import DurableMessageDispatcher
from .market_facts import apply_sql_budget
from .rule_values import condition_summary, version_conditions
from .feishu_protocol import FeishuInputError, SendOutcome, text_payload


def business_content(version, result, detail_base_url):
    direction = {"BUY": "买入计划", "SELL": "卖出计划"}.get(version.direction, "独立提醒")
    lines = ["财势乾坤 · 盘后验证", f"{version.stock_name_at_save}（{version.stock_code}） · {direction}",
        condition_summary(version_conditions(version)),
        "截止时间：" + version.deadline_at.astimezone(ZoneInfo("Asia/Shanghai")).isoformat(),
        "首次满足时间：" + result.first_match_at.astimezone(ZoneInfo("Asia/Shanghai")).isoformat()]
    if result.actual_price is not None:
        lines.append(f"实际前复权价格：{result.actual_price:.2f}")
    if result.cumulative_volume_shares is not None:
        lines.append(f"当日累计成交量：{result.cumulative_volume_shares / 100:.2f} 手")
    lines.append("条件成立不代表实际成交；持仓与交易记录不会自动改变。")
    lines.append("盘后检查时间：" + result.decided_at.astimezone(ZoneInfo("Asia/Shanghai")).isoformat())
    kind = "PLAN" if version.direction else "ALERT"
    if detail_base_url:
        lines.append(f"查看详情：{detail_base_url}/wealth/market/trading-assistant?ruleType={kind}&ruleId={version.rule_id}")
    return "\n".join(lines)


class NotificationDispatcher(DurableMessageDispatcher):
    def __init__(self, *args, detail_base_url="", **kwargs):
        super().__init__(*args, **kwargs)
        self.detail_base_url = detail_base_url

    def _sweep(self, session, deadline):
        apply_sql_budget(session, deadline, self.policy)
        now = self.now()
        stale = session.execute(select(NotificationAttempt.attempt_id, NotificationAttempt.dispatch_token).where(
            NotificationAttempt.outcome == "IN_FLIGHT", NotificationAttempt.started_at <=
            now - timedelta(milliseconds=self.notification_policy.total_timeout_ms))
            .order_by(NotificationAttempt.started_at, NotificationAttempt.attempt_id).limit(self.policy.page_rows)).all()
        for identity, token in stale:
            self._finish(session, identity, token, SendOutcome("UNKNOWN", "发送结果待核对，不会自动重发"), deadline)

    def _claim(self, session, deadline):
        apply_sql_budget(session, deadline, self.policy)
        now = self.now()
        pending = session.execute(select(TriggerNotification.notification_id, TriggerNotification.robot_id).where(
            TriggerNotification.state == "PENDING").order_by(TriggerNotification.created_at,
            TriggerNotification.notification_id).limit(self.policy.page_rows)).all()
        for identity, robot_id in pending:
            robot = session.scalar(select(RobotIdentity).where(RobotIdentity.robot_id == robot_id)
                .with_for_update(skip_locked=True).execution_options(populate_existing=True))
            if robot is None or robot.current_config_id is None or (robot.next_send_not_before and robot.next_send_not_before > now):
                continue
            notification = session.scalar(select(TriggerNotification).where(TriggerNotification.notification_id == identity,
                TriggerNotification.owner_user_id == robot.owner_user_id).with_for_update().execution_options(populate_existing=True))
            if notification is None or notification.state != "PENDING":
                continue
            config = session.scalar(select(RobotConfig).where(RobotConfig.config_id == robot.current_config_id,
                RobotConfig.owner_user_id == notification.owner_user_id, RobotConfig.robot_id == robot.robot_id))
            if config is None:
                continue
            version = session.scalar(select(RuleVersion).where(RuleVersion.rule_version_id == notification.rule_version_id,
                RuleVersion.owner_user_id == notification.owner_user_id))
            result = session.scalar(select(RuleResult).where(RuleResult.result_id == notification.trigger_id,
                RuleResult.owner_user_id == notification.owner_user_id, RuleResult.triggered.is_(True)))
            if version is None or result is None:
                raise RuntimeError("Notification lacks owned trigger evidence")
            content = business_content(version, result, self.detail_base_url)
            number = session.scalar(select(func.max(NotificationAttempt.attempt_no)).where(
                NotificationAttempt.notification_id == identity)) or 0
            row = NotificationAttempt(attempt_id=uuid4(), owner_user_id=notification.owner_user_id,
                notification_id=identity, robot_id=robot.robot_id, config_id=config.config_id,
                attempt_no=number + 1, dispatch_token=uuid4(), business_content=content,
                content_digest=sha256(content.encode()).hexdigest(), template_version="V1",
                started_at=now, outcome="IN_FLIGHT", result_history=[])
            session.add(row)
            session.flush()
            notification.latest_attempt_id = row.attempt_id
            notification.state, notification.state_version = "SENDING", notification.state_version + 1
            robot.next_send_not_before = now + timedelta(milliseconds=self.notification_policy.min_robot_interval_ms)
            session.flush()
            deadline.remaining_ms()
            return row.attempt_id, row.dispatch_token
        return None

    def _payload(self, session, identity, token, deadline):
        if not self.detail_base_url:
            raise FeishuInputError("Notification detail address unavailable")
        apply_sql_budget(session, deadline, self.policy)
        row = session.scalar(select(NotificationAttempt).where(NotificationAttempt.attempt_id == identity,
            NotificationAttempt.dispatch_token == token, NotificationAttempt.outcome == "IN_FLIGHT"))
        if row is None:
            return None
        config = session.scalar(select(RobotConfig).where(RobotConfig.owner_user_id == row.owner_user_id,
            RobotConfig.robot_id == row.robot_id, RobotConfig.config_id == row.config_id))
        secret = self.store._secret(session, row.owner_user_id, "CONFIG", row.config_id, config.credential_blob_id)
        return secret["webhook"], text_payload(row.business_content, keywords=tuple(config.keywords),
            signing_secret=secret["signingSecret"], timestamp=int(self.now().timestamp()))

    def _finish(self, session, identity, token, outcome, deadline):
        apply_sql_budget(session, deadline, self.policy)
        if outcome.state not in {"SUCCEEDED", "FAILED", "UNKNOWN"}:
            raise ValueError("Invalid send outcome")
        reference = session.scalar(select(NotificationAttempt).where(NotificationAttempt.attempt_id == identity,
            NotificationAttempt.dispatch_token == token))
        if reference is None:
            return
        # Finish does not select a config; acquire only notification then attempt.
        notification = session.scalar(select(TriggerNotification).where(
            TriggerNotification.notification_id == reference.notification_id,
            TriggerNotification.owner_user_id == reference.owner_user_id).with_for_update().execution_options(populate_existing=True))
        row = session.scalar(select(NotificationAttempt).where(NotificationAttempt.attempt_id == identity)
            .with_for_update().execution_options(populate_existing=True))
        if notification.latest_attempt_id != identity or row.outcome in {"SUCCEEDED", "FAILED"} or row.outcome == outcome.state:
            return
        now = self.now()
        row.outcome, row.completed_at, row.reason = outcome.state, now, outcome.reason
        row.response_code = outcome.response_code
        row.result_history = [*row.result_history, dict(state=outcome.state, at=now.isoformat(), responseCode=outcome.response_code)]
        notification.state, notification.state_version = outcome.state, notification.state_version + 1
        session.flush()
