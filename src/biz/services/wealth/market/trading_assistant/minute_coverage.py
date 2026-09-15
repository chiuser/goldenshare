"""Bounded time-identity coverage audit, not a trading-session calendar."""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from .condition_intervals import require_aware


@dataclass(frozen=True)
class MinuteCoverage:
    missing: tuple[datetime, ...]
    duplicates: tuple[datetime, ...]
    unexpected: tuple[datetime, ...]
    complete_prefix_through: datetime | None

    @property
    def complete(self) -> bool:
        return not (self.missing or self.duplicates or self.unexpected)


def audit_minute_coverage(
    expected: tuple[datetime, ...], observed: Iterable[datetime],
) -> MinuteCoverage:
    """Audit one bounded day/page against adapter-supplied authoritative times.

    The caller supplies the required time range, including opening-volume
    contributors when needed. This does not infer sessions, holidays or halts.
    It checks identities only; required prices/volumes need separate validation.
    """
    for index, checkpoint in enumerate(expected):
        require_aware(checkpoint)
        if index and checkpoint <= expected[index - 1]:
            raise ValueError("Expected checkpoints must be strictly ascending")
    counts = Counter()
    for checkpoint in observed:
        require_aware(checkpoint)
        counts[checkpoint] += 1
    expected_set = set(expected)
    missing = tuple(point for point in expected if counts[point] == 0)
    duplicates = tuple(sorted(point for point, count in counts.items() if count > 1))
    unexpected = tuple(sorted(set(counts) - expected_set))
    prefix = None
    # Unexpected identities invalidate the source range, not just its row count.
    if not unexpected:
        for point in expected:
            if counts[point] != 1:
                break
            prefix = point
    return MinuteCoverage(missing, duplicates, unexpected, prefix)
