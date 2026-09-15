"""Bounded pure scan over frozen minute facts; no result publication or IO."""

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from src.biz.schemas.wealth.market.trading_assistant.rules import Conditions

from .condition_evaluator import CheckpointEvaluation, evaluate_checkpoint
from .condition_intervals import ConditionInterval, require_aware
from .execution_policy import Deadline, TradingAssistantExecutionPolicyV1


@dataclass(frozen=True)
class RequiredMinute:
    at: datetime
    is_checkpoint: bool


@dataclass(frozen=True)
class MinuteFact:
    at: datetime
    price: Decimal | None
    volume_shares: int | None


@dataclass(frozen=True)
class MinuteScanProgress:
    basis_id: str
    trade_date: date
    last_at: datetime | None = None
    cumulative_shares: int | None = 0
    processed_rows: int = 0


@dataclass(frozen=True)
class MinuteMatch:
    at: datetime
    version_id: str
    price: Decimal | None
    cumulative_shares: int | None
    evaluation: CheckpointEvaluation


@dataclass(frozen=True)
class MinuteBatchResult:
    progress: MinuteScanProgress
    match: MinuteMatch | None = None
    waiting_at: datetime | None = None


def evaluate_minute_batch(
    *, basis_id: str, trade_date: date, condition: Conditions,
    interval: ConditionInterval, required: tuple[RequiredMinute, ...],
    facts: tuple[MinuteFact, ...], progress: MinuteScanProgress,
    policy: TradingAssistantExecutionPolicyV1, deadline: Deadline,
) -> MinuteBatchResult:
    """Scan one condition interval using a caller-verified opening/time schedule.

    Required times must continue the frozen schedule immediately after progress;
    the adapter owns that schedule and its auction/holiday/halt evidence. It must
    include opening contributors for volume conditions. A new day or changed
    basis requires fresh progress; a condition change alone does not reset volume.
    The frozen-material reader owns the byte budget before decoding. Returned
    progress is a candidate for fenced persistence, never a final result.
    """
    deadline.remaining_ms()
    require_aware(interval.after)
    require_aware(interval.through)
    if interval.after > interval.through:
        raise ValueError("Condition interval is inverted")
    if not basis_id or (progress.basis_id, progress.trade_date) != (basis_id, trade_date):
        raise ValueError("Minute progress belongs to another frozen basis/day")
    if len(required) > policy.page_rows or len(facts) > policy.page_rows:
        raise ValueError("Minute batch exceeds row budget")
    if (type(progress.processed_rows) is not int or progress.processed_rows < 0
            or (progress.cumulative_shares is not None and
                (type(progress.cumulative_shares) is not int or progress.cumulative_shares < 0))):
        raise ValueError("Invalid minute accumulator")
    previous = progress.last_at
    if previous is not None:
        require_aware(previous)
    expected = set()
    for minute in required:
        require_aware(minute.at)
        if (minute.at.astimezone(timezone(timedelta(hours=8))).date() != trade_date
                or (previous is not None and minute.at <= previous)
                or minute.at > interval.through
                or type(minute.is_checkpoint) is not bool):
            raise ValueError("Required minutes must advance within the business day")
        expected.add(minute.at)
        previous = minute.at
    by_time = {}
    for fact in facts:
        require_aware(fact.at)
        if fact.at not in expected or fact.at in by_time:
            raise ValueError("Duplicate or out-of-range frozen minute")
        by_time[fact.at] = fact
    current = progress
    for minute in required:
        deadline.remaining_ms()
        fact = by_time.get(minute.at)
        if fact is None:
            return MinuteBatchResult(current, waiting_at=minute.at)
        valid_volume = type(fact.volume_shares) is int and fact.volume_shares >= 0
        cumulative = (current.cumulative_shares + fact.volume_shares
                      if current.cumulative_shares is not None and valid_volume else None)
        if condition.volumeCondition is not None and cumulative is None:
            return MinuteBatchResult(current, waiting_at=minute.at)
        eligible = minute.is_checkpoint and interval.contains(minute.at)
        evaluation = None
        if eligible:
            if condition.priceCondition is not None and (
                not isinstance(fact.price, Decimal) or not fact.price.is_finite() or fact.price <= 0
            ):
                return MinuteBatchResult(current, waiting_at=minute.at)
            evaluation = evaluate_checkpoint(condition, fact.price, cumulative)
        current = replace(current, last_at=minute.at, cumulative_shares=cumulative,
                          processed_rows=current.processed_rows + 1)
        if evaluation is not None and evaluation.satisfied:
            return MinuteBatchResult(current, MinuteMatch(
                minute.at, interval.version_id,
                fact.price if condition.priceCondition is not None else None,
                cumulative if condition.volumeCondition is not None else None,
                evaluation,
            ))
    return MinuteBatchResult(current)
