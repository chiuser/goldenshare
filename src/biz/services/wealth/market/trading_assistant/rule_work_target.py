"""One earliest uncompleted day/version segment, never the whole rule history."""
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from uuid import UUID

from sqlalchemy import exists, func, select
from src.biz.models.wealth.trading_assistant.rules import Rule, RuleVersion, RuleExecution
from src.biz.models.wealth.trading_assistant.rule_checks import RuleCheck
from src.biz.schemas.wealth.market.trading_assistant.rules import Conditions
from .rule_values import version_conditions
from .rule_calendar import BEIJING, session_minutes
from .condition_intervals import ConditionInterval
from .market_facts import apply_sql_budget


@dataclass(frozen=True, slots=True)
class RuleWorkTarget:
    owner_id: int
    rule_id: UUID
    version_id: UUID
    stock_code: str
    day: object
    interval: ConditionInterval
    conditions: Conditions
    deadline_at: datetime
    notify_enabled: bool
    robot_id: UUID | None


def next_target(session, rule, execution, *, deadline, policy):
    apply_sql_budget(session, deadline, policy)
    current = session.get(RuleVersion, rule.current_version_id)
    day = execution.next_trade_date
    if day is None or day > current.deadline_at.astimezone(BEIJING).date():
        return None
    start = datetime.combine(day, time.min, tzinfo=BEIJING)
    end = start + timedelta(days=1) - timedelta(microseconds=1)
    sequence = select(RuleVersion.rule_version_id, RuleVersion.effective_at, RuleVersion.deadline_at,
        func.lead(RuleVersion.effective_at).over(order_by=RuleVersion.version_no).label("next_at")).where(
        RuleVersion.owner_user_id == rule.owner_user_id, RuleVersion.rule_id == rule.rule_id).subquery()
    lower = func.greatest(sequence.c.effective_at, start)
    upper = func.least(sequence.c.deadline_at, func.coalesce(sequence.c.next_at, sequence.c.deadline_at), end)
    completed = exists(select(RuleCheck.check_id).where(RuleCheck.rule_id == rule.rule_id,
        RuleCheck.rule_version_id == sequence.c.rule_version_id, RuleCheck.trade_date == day,
        RuleCheck.requested_from == lower, RuleCheck.requested_through == upper,
        RuleCheck.status == "COMPLETED"))
    row = session.execute(select(RuleVersion, lower.label("lower"), upper.label("upper"))
        .join(sequence, RuleVersion.rule_version_id == sequence.c.rule_version_id)
        .where(lower <= upper, ~completed).order_by(RuleVersion.version_no).limit(1)).first()
    if row is None:
        return None
    version, after, through = row
    return RuleWorkTarget(rule.owner_user_id, rule.rule_id, version.rule_version_id,
        version.stock_code, day, ConditionInterval(str(version.rule_version_id), after, through),
        version_conditions(version), version.deadline_at, version.notify_enabled, version.robot_id)


def required_minutes(target, *, is_open, full_day_suspended):
    if not is_open or full_day_suspended:
        return ()
    minutes = session_minutes(target.day)
    eligible = tuple(m for m in minutes if m.is_checkpoint and target.interval.contains(m.at))
    if not eligible:
        return ()
    if target.conditions.volumeCondition is not None:
        # Reconstruct the same opening cumulative amount for a later version;
        # never reset its meaning to volume since that version was saved.
        return tuple(m for m in minutes if m.at <= eligible[-1].at)
    return eligible
