"""Saved-time intervals from design §4.9.7; no market calendar inference."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime

from src.biz.schemas.wealth.market.trading_assistant.rules import ConditionVersion


@dataclass(frozen=True)
class ConditionInterval:
    version_id: str
    after: datetime
    through: datetime

    def contains(self, checkpoint: datetime) -> bool:
        require_aware(checkpoint)
        return self.after < checkpoint <= self.through


def require_aware(value: datetime) -> None:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("Rule time requires an explicit timezone")


def iter_condition_intervals(
    versions: Iterable[ConditionVersion],
) -> Iterator[ConditionInterval]:
    """Consume ordered persisted versions with one-version lookahead.

    Storage supplies the complete ordered sequence (possibly paged). Never sort
    by ID or input time: out-of-order versions are an invalid frozen input.
    Equal saved times have empty intervals, not overlapping minute ownership.
    This function does not grant execution permission to closed/ended rules.
    """
    previous = None
    previous_start = None
    deadline = None
    for version in versions:
        start = datetime.fromisoformat(version.effectiveAt)
        current_deadline = datetime.fromisoformat(version.deadlineAt)
        require_aware(start)
        require_aware(current_deadline)
        if start >= current_deadline:
            raise ValueError("Version must take effect before the fixed deadline")
        if previous is None:
            if int(version.versionNo) != 1:
                raise ValueError("Complete version history must start at one")
            deadline = current_deadline
        else:
            if (int(version.versionNo) != int(previous.versionNo) + 1
                    or start < previous_start or current_deadline != deadline
                    or version.ruleVersionId == previous.ruleVersionId):
                raise ValueError("Invalid ordered condition version history")
            yield ConditionInterval(previous.ruleVersionId, previous_start, start)
        previous, previous_start = version, start
    if previous is None:
        raise ValueError("Condition version history is empty")
    yield ConditionInterval(previous.ruleVersionId, previous_start, deadline)
