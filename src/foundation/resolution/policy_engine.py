from __future__ import annotations

from datetime import date, datetime
from typing import Any

from src.foundation.resolution.types import ResolutionInput, ResolutionOutput, ResolutionPolicy, parse_freshness_value


class ResolutionPolicyEngine:
    def resolve(self, resolution_input: ResolutionInput, policy: ResolutionPolicy) -> ResolutionOutput:
        if not policy.enabled:
            return ResolutionOutput(
                dataset_key=resolution_input.dataset_key,
                business_key=resolution_input.business_key,
                resolved_record=None,
                resolved_source_key=None,
                policy_version=policy.version,
                mode=policy.mode,
                audit={"reason": "policy_disabled"},
            )

        active_sources = resolution_input.active_sources or set(resolution_input.candidates_by_source.keys())
        candidates = {
            source_key: row
            for source_key, row in resolution_input.candidates_by_source.items()
            if source_key in active_sources
        }

        if not candidates:
            return ResolutionOutput(
                dataset_key=resolution_input.dataset_key,
                business_key=resolution_input.business_key,
                resolved_record=None,
                resolved_source_key=None,
                policy_version=policy.version,
                mode=policy.mode,
                audit={"reason": "no_active_candidates"},
            )

        if policy.mode in {"primary", "fallback", "primary_fallback"}:
            resolved_source, resolved_record = self._resolve_by_priority(candidates, policy)
        elif policy.mode == "field_merge":
            resolved_source, resolved_record = self._resolve_field_merge(candidates, policy)
        elif policy.mode == "freshness_first":
            resolved_source, resolved_record = self._resolve_freshness_first(candidates, policy)
        else:
            raise ValueError(f"Unsupported resolution mode: {policy.mode}")

        return ResolutionOutput(
            dataset_key=resolution_input.dataset_key,
            business_key=resolution_input.business_key,
            resolved_record=resolved_record,
            resolved_source_key=resolved_source,
            policy_version=policy.version,
            mode=policy.mode,
            audit={
                "candidate_sources": sorted(candidates),
                "resolved_source": resolved_source,
            },
        )

    @staticmethod
    def _priority_chain(policy: ResolutionPolicy) -> list[str]:
        chain = [policy.primary_source_key, *policy.fallback_source_keys]
        dedup: list[str] = []
        seen: set[str] = set()
        for source_key in chain:
            if source_key and source_key not in seen:
                seen.add(source_key)
                dedup.append(source_key)
        return dedup

    def _resolve_by_priority(
        self,
        candidates: dict[str, dict[str, Any]],
        policy: ResolutionPolicy,
    ) -> tuple[str, dict[str, Any]]:
        chain = self._priority_chain(policy)
        for source_key in chain:
            row = candidates.get(source_key)
            if row is not None:
                return source_key, dict(row)
        first_key = next(iter(sorted(candidates)))
        return first_key, dict(candidates[first_key])

    def _resolve_field_merge(
        self,
        candidates: dict[str, dict[str, Any]],
        policy: ResolutionPolicy,
    ) -> tuple[str, dict[str, Any]]:
        base_source, base_record = self._resolve_by_priority(candidates, policy)
        merged = dict(base_record)
        for field, rule in policy.field_rules.items():
            preferred_sources = rule.get("preferred_sources") or []
            allow_empty_fallback = bool(rule.get("allow_empty_fallback", True))
            for source_key in preferred_sources:
                row = candidates.get(source_key)
                if row is None:
                    continue
                value = row.get(field)
                if value is None and not allow_empty_fallback:
                    continue
                merged[field] = value
                break
        return base_source, merged

    def _resolve_freshness_first(
        self,
        candidates: dict[str, dict[str, Any]],
        policy: ResolutionPolicy,
    ) -> tuple[str, dict[str, Any]]:
        freshness_field = str(policy.field_rules.get("__freshness__", {}).get("field", "updated_at"))

        scored: list[tuple[datetime | date | None, int, str, dict[str, Any]]] = []
        priority = {source_key: idx for idx, source_key in enumerate(self._priority_chain(policy))}
        for source_key, row in candidates.items():
            freshness_value = parse_freshness_value(row.get(freshness_field))
            scored.append((freshness_value, priority.get(source_key, 10_000), source_key, row))

        scored.sort(key=lambda item: ((item[0] is not None), item[0], -item[1]), reverse=True)
        _, _, resolved_source, resolved_row = scored[0]
        return resolved_source, dict(resolved_row)
