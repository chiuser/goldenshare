from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class NormalizationError:
    index: int
    reason: str
    row: dict[str, Any]


def normalize_rows_with_isolation(
    rows: list[dict[str, Any]],
    normalize_row: Callable[[dict[str, Any], str], dict[str, Any]],
    source_key: str,
) -> tuple[list[dict[str, Any]], list[NormalizationError]]:
    normalized_rows: list[dict[str, Any]] = []
    errors: list[NormalizationError] = []
    for index, row in enumerate(rows):
        try:
            normalized_rows.append(normalize_row(row, source_key))
        except ValueError as exc:
            errors.append(NormalizationError(index=index, reason=str(exc), row=row))
    return normalized_rows, errors
