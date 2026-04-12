from __future__ import annotations

from collections import defaultdict
from typing import Any

from src.foundation.resolution.types import FieldConflict


class ConflictScorer:
    def collect_conflicts(
        self,
        candidates_by_source: dict[str, dict[str, Any]],
        *,
        comparable_fields: tuple[str, ...],
    ) -> list[FieldConflict]:
        conflicts: list[FieldConflict] = []
        for field in comparable_fields:
            values_by_source: dict[str, Any] = {}
            for source_key, row in candidates_by_source.items():
                if field in row:
                    values_by_source[source_key] = row.get(field)
            if len(values_by_source) < 2:
                continue
            grouped: dict[Any, list[str]] = defaultdict(list)
            for source_key, value in values_by_source.items():
                grouped[value].append(source_key)
            if len(grouped) <= 1:
                continue
            conflicts.append(
                FieldConflict(
                    field=field,
                    values_by_source=values_by_source,
                    comparable_sources=tuple(sorted(values_by_source)),
                )
            )
        return conflicts
