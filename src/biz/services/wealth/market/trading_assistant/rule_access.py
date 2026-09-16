"""Rule maintenance and the explicit M6/M7 robot capability boundary."""
from sqlalchemy import select

from src.biz.models.wealth.trading_assistant.rule_notifications import TriggerNotification
from .rule_calendar import has_future_checkpoint
from .market_facts import MarketFactsUnavailable, apply_sql_budget


class RuleRobotAccess:
    """No credential/config qualification exists before M7.

    A bare robot identity is not a tested, confirmed configuration. Isolated
    integration fixtures may inject a qualified source; production must not
    accept a client-provided ID as proof. No send or credential I/O here.
    """
    def resolve(self, session, owner_id, robot_id, deadline):
        deadline.remaining_ms()
        return None

    def names(self, session, *, owner_id, robot_ids, deadline):
        deadline.remaining_ms()
        return {}


class RuleAccess:
    def __init__(self, market, policy, robots):
        self.market, self.policy, self.robots = market, policy, robots

    def has_future_checkpoint(self, session, security, after, through, deadline):
        return has_future_checkpoint(self.market, session, security, after, through, deadline)

    def maintenance(self, session, *, rule, version, now, deadline):
        if rule.state != "ACTIVE":
            return dict(canEditConditions=False, canClose=False,
                editUnavailableReason="规则已结束", closeUnavailableReason="规则已结束")
        can_edit, reason = False, "没有未来可检查的时间范围"
        if now < version.deadline_at:
            try:
                security = self.market.resolve_security(session, version.stock_code, deadline)
                can_edit = self.has_future_checkpoint(session, security, now, version.deadline_at, deadline)
            except MarketFactsUnavailable:
                reason = "交易日历尚不完整，暂不能确认可修改范围"
        return dict(canEditConditions=can_edit, canClose=True,
            editUnavailableReason=None if can_edit else reason, closeUnavailableReason=None)

    def notification_summaries(self, session, *, owner_id, rules, versions, deadline):
        apply_sql_budget(session, deadline, self.policy)
        records = {n.rule_id: n for n in session.scalars(select(TriggerNotification).where(
            TriggerNotification.owner_user_id == owner_id,
            TriggerNotification.rule_id.in_([r.rule_id for r in rules])))}
        robot_ids = {versions[r.current_version_id].robot_id for r in rules} - {None}
        names = self.robots.names(session, owner_id=owner_id, robot_ids=robot_ids, deadline=deadline)
        output = {}
        for rule in rules:
            version, record = versions[rule.current_version_id], records.get(rule.rule_id)
            output[rule.rule_id] = dict(notificationId=str(record.notification_id) if record else None,
                state=record.state if record else "NOT_CREATED" if version.notify_enabled else "NOT_ENABLED",
                stateVersion=str(record.state_version) if record else None,
                robotId=str(version.robot_id) if version.robot_id else None,
                robotName=names.get(version.robot_id), canRetry=False,
                reason="通知发送能力尚未接入" if record else None)
        return output
