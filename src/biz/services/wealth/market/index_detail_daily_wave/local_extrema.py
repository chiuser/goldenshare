"""Raw, causal local turns only; XXM research plan 12.92 / LLD 70.

This module has no knowledge of DULL/STRUCTURE, histogram colours, prices,
thresholds or production calculators. Equal-valued samples form one plateau.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation


def number(value: str | int | Decimal) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("Use an original decimal string, integer or Decimal")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid numeric input") from exc
    if not result.is_finite():
        raise ValueError("Nonfinite input")
    return result


@dataclass(frozen=True)
class TurningPoint:
    kind: str
    value: Decimal
    first_at: str
    last_at: str
    first_index: int
    last_index: int
    confirmed_at: str
    confirmed_index: int

    def record(self) -> dict:
        result = asdict(self)
        result["value"] = str(self.value)
        return result


class LocalExtremaScanner:
    """One completed sample at a time, O(1) retained state and O(n) work."""

    def __init__(self) -> None:
        self.count = 0
        self.last_key: str | None = None
        self.value: Decimal | None = None
        self.first_at: str | None = None
        self.last_at: str | None = None
        self.first_index = self.last_index = -1
        self.trend = 0

    def step(self, key: str, value: str | int | Decimal,
             *, completed: bool = True) -> TurningPoint | None:
        # Reject before mutation, including provisional invalid samples.
        if not isinstance(key, str) or not key:
            raise ValueError("A nonempty ordered key is required")
        if self.last_key is not None and key <= self.last_key:
            raise ValueError("Duplicate or unordered completed key")
        if not isinstance(completed, bool):
            raise ValueError("completed must be a boolean")
        current = number(value)
        if not completed:
            return None

        index = self.count
        point = None
        if self.value is None:
            self.first_at = self.last_at = key
            self.first_index = self.last_index = index
        elif current == self.value:
            self.last_at, self.last_index = key, index
        else:
            direction = 1 if current > self.value else -1
            if self.trend and direction != self.trend:
                assert self.first_at is not None and self.last_at is not None
                point = TurningPoint(
                    "MAX" if self.trend == 1 else "MIN", self.value,
                    self.first_at, self.last_at, self.first_index, self.last_index,
                    key, index,
                )
            self.trend = direction
            self.first_at = self.last_at = key
            self.first_index = self.last_index = index
        self.value, self.last_key = current, key
        self.count += 1
        return point

    def pending(self) -> dict | None:
        if self.value is None:
            return None
        return dict(
            value=str(self.value), first_at=self.first_at, last_at=self.last_at,
            first_index=self.first_index, last_index=self.last_index,
            possible_kind="MAX" if self.trend > 0 else "MIN" if self.trend < 0 else None,
            confirmed=False,
        )


def scan_values(values: list[str | int | Decimal]) -> list[TurningPoint]:
    scanner = LocalExtremaScanner()
    result = []
    for index, value in enumerate(values):
        point = scanner.step(f"{index:09d}", value)
        if point is not None:
            result.append(point)
    return result
