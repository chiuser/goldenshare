"""Pure bounded source-unit planning. Never opens DB, Lake or Dagster instance."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import date, timedelta

from orchestrator.defs.run_contracts.stock_weekly import (
    ProdWeeklyScope,
    ProdWeeklyUnit,
    StockWeeklySource,
    WeeklyAvailability,
    WeeklyHistoryScope,
    WeeklyPlanManifest,
    WeeklySourceUnit,
    stable_weekly_hash,
    weekly_schema_hash,
)


def source_date_week_key(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 8
        or not value.isascii()
        or not value.isdigit()
    ):
        raise ValueError("source_date_must_be_yyyymmdd")
    parsed = date(int(value[:4]), int(value[4:6]), int(value[6:]))
    return (parsed + timedelta(days=4 - parsed.weekday())).isoformat()


def plan_weekly_source_units(scope: WeeklyHistoryScope) -> tuple[WeeklySourceUnit, ...]:
    groups: dict[tuple[str, int], list[str]] = defaultdict(list)
    evidence: dict[tuple[str, int], set[tuple[str, str]]] = defaultdict(set)
    excluded = set(scope.excluded_week_keys)
    for candidate in scope.candidates:
        if (
            candidate.availability is WeeklyAvailability.AVAILABLE
            and candidate.week_key not in excluded
        ):
            groups[(candidate.ts_code, int(candidate.week_key[:4]))].append(
                candidate.week_key
            )
            evidence[(candidate.ts_code, int(candidate.week_key[:4]))].add(
                (candidate.source_evidence_ref, candidate.source_evidence_hash)
            )
    units = []
    for (code, year), keys in sorted(groups.items()):
        first, last = keys[0], keys[-1]
        start, end = date.fromisoformat(first), date.fromisoformat(last)
        max_rows = (end - start).days // 7 + 1
        if max_rows > 54:
            raise ValueError("annual_week_unit_exceeds_54")
        body = {
            "source": StockWeeklySource.ALTERNATE_WEEKLY.value,
            "ts_code": code,
            "anchor_start": first,
            "anchor_end": last,
            "schema_hash": weekly_schema_hash(StockWeeklySource.ALTERNATE_WEEKLY),
            "expected_key_hash": stable_weekly_hash(keys),
            "excluded_week_keys": tuple(
                k for k in scope.excluded_week_keys if first <= k <= last
            ),
            "source_evidence": tuple(sorted(evidence[(code, year)])),
        }
        units.append(
            WeeklySourceUnit(
                unit_id=stable_weekly_hash(body),
                source=StockWeeklySource.ALTERNATE_WEEKLY,
                ts_code=code,
                anchor_start=first,
                anchor_end=last,
                request_start=start - timedelta(days=4),
                request_end=end + timedelta(days=2),
                expected_key_ref=scope.expected_key_ref,
                expected_key_hash=body["expected_key_hash"],
                expected_key_count=len(keys),
                max_rows=max_rows,
                excluded_week_keys=body["excluded_week_keys"],
                source_evidence=body["source_evidence"],
            )
        )
    if sum(u.max_rows for u in units) > scope.budget.max_phase_rows:
        raise ValueError("phase_row_budget_exceeded")
    if (
        len(
            {
                c.week_key
                for c in scope.candidates
                if c.availability is WeeklyAvailability.AVAILABLE
            }
            - excluded
        )
        > scope.budget.max_phase_files
    ):
        raise ValueError("phase_file_budget_exceeded")
    return tuple(units)


def plan_prod_source_units(scope: ProdWeeklyScope) -> tuple[ProdWeeklyUnit, ...]:
    units = []
    schema_hash = weekly_schema_hash(scope.source)
    # Each code contributes at most 54 weekly rows in a calendar-year capture.
    batch_size = min(
        scope.budget.prod_code_batch, scope.budget.max_source_rows_per_prod_unit // 54
    )
    if batch_size < 1:
        raise ValueError("prod_unit_budget_cannot_fit_one_code")
    if len(scope.inventories) * 54 > scope.budget.max_phase_files:
        raise ValueError("phase_file_budget_exceeded")
    for inventory in scope.inventories:
        start, end = date(inventory.year, 1, 1), date(inventory.year + 1, 1, 1)
        for offset in range(0, len(inventory.codes), batch_size):
            codes = inventory.codes[offset : offset + batch_size]
            body = {
                "source": scope.source.value,
                "codes": codes,
                "start": start,
                "end": end,
                "schema_hash": schema_hash,
            }
            units.append(
                ProdWeeklyUnit(
                    unit_id=stable_weekly_hash(body),
                    source=scope.source,
                    sorted_codes=codes,
                    source_date_start=start,
                    source_date_end=end,
                    schema_hash=schema_hash,
                    max_rows=scope.budget.max_source_rows_per_prod_unit,
                )
            )
    return tuple(units)


def freeze_weekly_history_plan(scope: WeeklyHistoryScope) -> WeeklyPlanManifest:
    units = plan_weekly_source_units(scope)
    reasons: Counter[str] = Counter()
    for candidate in scope.candidates:
        if candidate.week_key in scope.excluded_week_keys:
            reasons["excluded_week"] += 1
        elif candidate.availability is not WeeklyAvailability.AVAILABLE:
            reasons[candidate.availability.value] += 1
    planned = sum(u.expected_key_count for u in units)
    body = {
        "scope": (scope.anchor_start, scope.anchor_end, scope.excluded_week_keys),
        "evidence": (scope.expected_key_ref, scope.expected_key_hash),
        "candidate_hash": stable_weekly_hash([asdict(c) for c in scope.candidates]),
        "units": [asdict(u) for u in units],
        "budget": asdict(scope.budget),
        "skipped": sorted(reasons.items()),
    }
    return WeeklyPlanManifest(
        plan_hash=stable_weekly_hash(body),
        source=StockWeeklySource.ALTERNATE_WEEKLY,
        evidence_ref=scope.expected_key_ref,
        evidence_hash=scope.expected_key_hash,
        units=units,
        budget=scope.budget,
        request_cap=len(units) * (scope.budget.max_retries + 1),
        planned_key_count=planned,
        skipped_key_count=sum(reasons.values()),
        skipped_reason_counts=tuple(sorted(reasons.items())),
    )


def freeze_prod_weekly_plan(scope: ProdWeeklyScope) -> WeeklyPlanManifest:
    units = plan_prod_source_units(scope)
    body = {
        "source": scope.source.value,
        "evidence": (scope.inventory_ref, scope.inventory_hash),
        "inventories": [asdict(x) for x in scope.inventories],
        "units": [asdict(x) for x in units],
        "budget": asdict(scope.budget),
    }
    return WeeklyPlanManifest(
        plan_hash=stable_weekly_hash(body),
        source=scope.source,
        evidence_ref=scope.inventory_ref,
        evidence_hash=scope.inventory_hash,
        units=units,
        budget=scope.budget,
        request_cap=0,
        planned_key_count=sum(x.source_rows for x in scope.inventories),
        skipped_key_count=0,
        skipped_reason_counts=(),
    )
