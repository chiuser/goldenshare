from __future__ import annotations

from typing import Any

from src.foundation.resolution.policy_engine import ResolutionPolicyEngine
from src.foundation.resolution.types import ResolutionInput, ResolutionPolicy
from src.foundation.serving.builders.base import ServingBuildResult


class ResolutionServingBuilder:
    dataset_key: str = ""
    business_key_fields: tuple[str, ...] = ()

    def __init__(self, policy_engine: ResolutionPolicyEngine | None = None) -> None:
        self._policy_engine = policy_engine or ResolutionPolicyEngine()

    def build_rows(
        self,
        *,
        std_rows_by_source: dict[str, list[dict[str, Any]]],
        policy: ResolutionPolicy,
        active_sources: set[str] | None,
        target_columns: set[str],
    ) -> ServingBuildResult:
        candidates_by_business_key: dict[str, dict[str, dict[str, Any]]] = {}
        for source_key, rows in std_rows_by_source.items():
            for row in rows:
                business_key = self._compose_business_key(row)
                if business_key is None:
                    continue
                by_source = candidates_by_business_key.setdefault(business_key, {})
                by_source[source_key] = dict(row)

        serving_rows: list[dict[str, Any]] = []
        resolved_count = 0
        for business_key, candidates in candidates_by_business_key.items():
            output = self._policy_engine.resolve(
                ResolutionInput(
                    dataset_key=self.dataset_key,
                    business_key=business_key,
                    candidates_by_source=candidates,
                    active_sources=active_sources,
                ),
                policy,
            )
            if output.resolved_record is None:
                continue
            resolved_count += 1
            serving_row = self._build_serving_row(output.resolved_record, output.resolved_source_key)
            self._apply_provenance_fields(
                serving_row,
                target_columns=target_columns,
                resolved_mode=output.mode,
                policy_version=output.policy_version,
                candidate_sources=tuple(candidates.keys()),
                audit=output.audit,
            )
            normalized_row = {key: serving_row.get(key) for key in target_columns}
            serving_rows.append(normalized_row)
        return ServingBuildResult(rows=serving_rows, resolved_count=resolved_count)

    def _compose_business_key(self, row: dict[str, Any]) -> str | None:
        parts: list[str] = []
        for field in self.business_key_fields:
            value = row.get(field)
            if value is None:
                return None
            text = str(value).strip()
            if not text:
                return None
            parts.append(text)
        return "|".join(parts)

    @staticmethod
    def _build_serving_row(resolved_record: dict[str, Any], resolved_source_key: str | None) -> dict[str, Any]:
        serving_row = {key: value for key, value in resolved_record.items() if key != "source_key"}
        if resolved_source_key:
            serving_row["source"] = resolved_source_key
        return serving_row

    @staticmethod
    def _apply_provenance_fields(
        serving_row: dict[str, Any],
        *,
        target_columns: set[str],
        resolved_mode: str,
        policy_version: int,
        candidate_sources: tuple[str, ...],
        audit: dict[str, Any],
    ) -> None:
        if "resolution_mode" in target_columns:
            serving_row["resolution_mode"] = resolved_mode
        if "resolution_policy_version" in target_columns:
            serving_row["resolution_policy_version"] = policy_version
        if "candidate_sources" in target_columns:
            serving_row["candidate_sources"] = ",".join(sorted(candidate_sources))
        if "resolution_audit" in target_columns:
            serving_row["resolution_audit"] = audit
