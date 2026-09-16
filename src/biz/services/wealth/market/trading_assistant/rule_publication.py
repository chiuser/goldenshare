"""Atomic terminal transition on the same lock/fence as close and maintenance."""
from uuid import uuid4
from sqlalchemy import func, insert, literal, select, text

from src.biz.models.wealth.trading_assistant.rule_checks import RuleCheck, RuleResult, RuleResultCheck, RuleCheckProgress
from src.biz.models.wealth.trading_assistant.rule_notifications import TriggerNotification
from src.biz.models.wealth.trading_assistant.rules import RuleVersion
from .rule_calendar import BEIJING
from .rule_execution import RuleExecutionLost


def publish_rule_result(session, store, lease, *, deadline, check=None, match=None):
    rule, execution = store._lock(session, lease, deadline)
    now = session.scalar(select(func.clock_timestamp()))
    current = session.get(RuleVersion, rule.current_version_id)
    if match is None:
        if now < current.deadline_at or execution.next_trade_date <= current.deadline_at.astimezone(BEIJING).date():
            raise ValueError("A false result requires completed coverage through the deadline")
    elif (check is None or check.rule_id != rule.rule_id or check.status != "COMPLETED"
          or str(check.rule_version_id) != match.version_id
          or not check.requested_from < match.at <= check.requested_through):
        raise ValueError("Trigger must reference the completed owning segment")
    if match is not None:
        progress = session.get(RuleCheckProgress, check.check_id)
        if progress is None or (progress.first_match_at, progress.first_match_price,
                progress.first_match_cumulative_shares, progress.price_satisfied, progress.volume_satisfied) != (
                match.at, match.price, match.cumulative_shares, match.evaluation.price_satisfied, match.evaluation.volume_satisfied):
            raise ValueError("Trigger differs from retained progress")
    # Prove every version/day segment of the prefix has a completed check.
    # This is a bounded SQL operation, not a Python history load or an assertion
    # based only on the last day/cursor. Holidays have explicit empty checks.
    through = match.at if match else current.deadline_at
    gap = session.scalar(text("""
        WITH versions AS (
          SELECT rule_version_id, effective_at, deadline_at,
                 lead(effective_at) OVER (ORDER BY version_no) AS next_at
          FROM app.wealth_ta_rule_version WHERE owner_user_id=:owner AND rule_id=:rule
        ), days AS (
          SELECT d AT TIME ZONE 'Asia/Shanghai' AS day_start,
                 (d + interval '1 day' - interval '1 microsecond') AT TIME ZONE 'Asia/Shanghai' AS day_end,
                 d::date AS trade_date
          FROM generate_series(CAST(:start AS date)::timestamp, CAST(:end AS date)::timestamp, interval '1 day') d
        ), segments AS (
          SELECT rule_version_id, trade_date, greatest(effective_at, day_start) AS lo,
                 least(deadline_at, coalesce(next_at, deadline_at), day_end, CAST(:through AS timestamptz)) AS hi
          FROM versions CROSS JOIN days
        )
        SELECT EXISTS (
          SELECT 1 FROM segments s WHERE s.lo < s.hi AND NOT EXISTS (
            SELECT 1 FROM app.wealth_ta_rule_check c
            WHERE c.owner_user_id=:owner AND c.rule_id=:rule
              AND c.rule_version_id=s.rule_version_id AND c.trade_date=s.trade_date
              AND c.status='COMPLETED' AND c.requested_from=s.lo AND c.requested_through>=s.hi
          )
        )
    """), dict(owner=rule.owner_user_id, rule=rule.rule_id,
        start=rule.created_at.astimezone(BEIJING).date(), end=through.astimezone(BEIJING).date(), through=through))
    if gap:
        raise ValueError("Rule prefix still contains an uncompleted segment")
    if rule.result_id is not None:
        raise RuleExecutionLost("Rule already has a result")
    result_id = uuid4()
    result = RuleResult(result_id=result_id, owner_user_id=rule.owner_user_id, rule_id=rule.rule_id,
        triggered=match is not None, decided_at=now, trigger_version_id=check.rule_version_id if match else None,
        first_match_at=match.at if match else None, actual_price=match.price if match else None,
        cumulative_volume_shares=match.cumulative_shares if match else None,
        price_satisfied=match.evaluation.price_satisfied if match else None,
        volume_satisfied=match.evaluation.volume_satisfied if match else None)
    session.add(result)
    session.flush()
    # Set-based linking retains all completed prefix segments without loading
    # a multi-year check list into memory. Waiting/failed attempts are not proof.
    session.execute(insert(RuleResultCheck).from_select(
        ["result_id", "check_id", "owner_user_id", "rule_id"], select(
            literal(result_id), RuleCheck.check_id, RuleCheck.owner_user_id, RuleCheck.rule_id).where(
                RuleCheck.owner_user_id == rule.owner_user_id, RuleCheck.rule_id == rule.rule_id,
                RuleCheck.status == "COMPLETED")))
    if match:
        version = session.get(RuleVersion, check.rule_version_id)
        if version.notify_enabled:
            session.add(TriggerNotification(notification_id=uuid4(), owner_user_id=rule.owner_user_id,
                rule_id=rule.rule_id, trigger_id=result_id, rule_version_id=version.rule_version_id,
                robot_id=version.robot_id, purpose="TRIGGER_NOTIFICATION", created_at=now, state="PENDING", state_version=1))
    # Validate while ACTIVE, then invalidate execution and publish together.
    store._verify(session, lease, rule, execution, deadline)
    rule.state, rule.result_id, rule.ended_at = "ENDED", result_id, now
    rule.state_version += 1
    execution.fence += 1
    execution.executor_id = execution.lease_until = execution.next_attempt_at = None
    execution.observed_state_version = rule.state_version
    execution.last_business_updated_at = now
    session.flush()
    deadline.remaining_ms()
    return result_id
