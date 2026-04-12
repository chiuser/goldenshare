from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.foundation.resolution.policy_engine import ResolutionPolicyEngine
from src.foundation.resolution.types import ResolutionInput, ResolutionPolicy
from src.foundation.serving.builders.base import ServingBuildResult


@dataclass(frozen=True)
class SecurityServingBuildResult(ServingBuildResult):
    pass


class SecurityServingBuilder:
    dataset_key = "stock_basic"

    def __init__(self, policy_engine: ResolutionPolicyEngine | None = None) -> None:
        self._policy_engine = policy_engine or ResolutionPolicyEngine()

    def build_rows(
        self,
        *,
        std_rows_by_source: dict[str, list[dict[str, Any]]],
        policy: ResolutionPolicy,
        active_sources: set[str] | None,
        target_columns: set[str],
    ) -> SecurityServingBuildResult:
        candidates_by_code: dict[str, dict[str, dict[str, Any]]] = {}
        for source_key, rows in std_rows_by_source.items():
            for row in rows:
                ts_code = str(row.get("ts_code", "")).strip()
                if not ts_code:
                    continue
                by_source = candidates_by_code.setdefault(ts_code, {})
                by_source[source_key] = dict(row)

        serving_rows: list[dict[str, Any]] = []
        resolved_count = 0
        for ts_code, candidates in candidates_by_code.items():
            output = self._policy_engine.resolve(
                ResolutionInput(
                    dataset_key="stock_basic",
                    business_key=ts_code,
                    candidates_by_source=candidates,
                    active_sources=active_sources,
                ),
                policy,
            )
            if output.resolved_record is None:
                continue
            resolved_count += 1
            serving_row = {key: value for key, value in output.resolved_record.items() if key != "source_key"}
            if output.resolved_source_key:
                serving_row["source"] = output.resolved_source_key
            if "resolution_mode" in target_columns:
                serving_row["resolution_mode"] = output.mode
            if "resolution_policy_version" in target_columns:
                serving_row["resolution_policy_version"] = output.policy_version
            if "candidate_sources" in target_columns:
                serving_row["candidate_sources"] = ",".join(sorted(candidates.keys()))
            if "resolution_audit" in target_columns:
                serving_row["resolution_audit"] = output.audit
            normalized_row = {key: serving_row.get(key) for key in target_columns}
            serving_rows.append(normalized_row)
        return SecurityServingBuildResult(rows=serving_rows, resolved_count=resolved_count)
