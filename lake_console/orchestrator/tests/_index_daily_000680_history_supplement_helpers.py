from __future__ import annotations

import json
from pathlib import Path

import dagster as dg

from orchestrator.defs.bootstrap.index_daily_000680_history_supplement_plan import (
    DEFAULT_STAGING_ROOT,
    TARGET_CODE,
    compute_frozen_plan_hash,
    hash_payload,
)
from orchestrator.defs.partitions import cn_a_index_trade_days, cn_a_index_ts_codes

FORMAL_LAKE_ROOT = Path("/Volumes/datasource/data_lake")


def frozen_plan_payload(
    *,
    dates: tuple[str, ...] = ("2020-01-02",),
    gold_dates: tuple[str, ...] | None = None,
    run_id: str = "test-run",
) -> dict[str, object]:
    resolved_gold_dates = gold_dates or dates
    payload: dict[str, object] = {
        "schema_version": 1,
        "generated_at": "2026-08-08T00:00:00+00:00",
        "code_commit": "test-commit",
        "lake_root": str(FORMAL_LAKE_ROOT),
        "staging_root": str(DEFAULT_STAGING_ROOT),
        "run_id": run_id,
        "target_code": TARGET_CODE,
        "source_audit": {"passed": True, "row_count": len(dates)},
        "layer_audits": {
            "raw": {"files_complete": True},
            "silver": {"files_complete": True},
            "gold": {"files_complete": True},
        },
        "partition_audit": {"passed": True},
        "source_query_hash": "source-query-hash",
        "seed": {
            "file_path": "/repo/major_indices.cn_a.csv",
            "file_hash": "seed-file-hash",
            "current_count": 10,
            "target_count": 11,
        },
        "targets": {
            "raw_files": [
                str(
                    FORMAL_LAKE_ROOT
                    / "raw"
                    / "index_daily"
                    / f"trade_date={trade_date}"
                    / "part-000.parquet"
                )
                for trade_date in dates
            ],
            "silver_files": [
                str(
                    FORMAL_LAKE_ROOT
                    / "silver"
                    / "index_daily"
                    / f"trade_date={trade_date}"
                    / "part-000.parquet"
                )
                for trade_date in dates
            ],
            "gold_files": [
                str(
                    FORMAL_LAKE_ROOT
                    / "gold"
                    / "market"
                    / "major_indices_daily"
                    / f"trade_date={trade_date}"
                    / "part-000.parquet"
                )
                for trade_date in resolved_gold_dates
            ],
            "max_batch_date_count": 100,
        },
        "should_stop": False,
        "stop_reason_codes": [],
        "writes": {
            "formal_lake": 0,
            "source_staging": 0,
            "dagster_db": 0,
            "dynamic_partitions": 0,
            "dagster_events": 0,
        },
    }
    payload["plan_hash"] = compute_frozen_plan_hash(payload)
    return payload


def write_plan(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_green_physical_audit(path: Path, *, plan_hash: str) -> str:
    source_plan_hash = "source-plan-hash"
    source = {
        "passed": True,
        "row_count": 1,
        "expected_row_count": 1,
    }
    layers = {
        "raw": {"passed": True, "target_row_count": 1},
        "silver": {"passed": True, "target_row_count": 1},
        "gold": {"passed": True, "target_row_count": 1},
    }
    cross_layer = {
        "source_plan_history_matches": True,
        "source_raw_history_matches": True,
        "raw_silver_history_matches": True,
        "silver_gold_matches": True,
    }
    audit_hash = hash_payload(
        {
            "plan_hash": plan_hash,
            "source_plan_hash": source_plan_hash,
            "source": source,
            "raw": layers["raw"],
            "silver": layers["silver"],
            "gold": layers["gold"],
            **cross_layer,
        }
    )
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "plan_hash": plan_hash,
                "source_plan_hash": source_plan_hash,
                "source": source,
                "layers": layers,
                "cross_layer": cross_layer,
                "audit_hash": audit_hash,
                "passed": True,
            }
        ),
        encoding="utf-8",
    )
    return audit_hash


class FakeDagsterInstance:
    def __init__(
        self,
        *,
        dates: tuple[str, ...] = (),
        codes: tuple[str, ...] = (),
        materialized: dict[str, set[str]] | None = None,
    ) -> None:
        self.dates = list(dates)
        self.codes = list(codes)
        self.materialized = materialized or {}
        self.partition_writes: list[tuple[str, tuple[str, ...]]] = []
        self.events: list[object] = []

    def get_dynamic_partitions(self, name: str) -> list[str]:
        if name == cn_a_index_trade_days.name:
            return list(self.dates)
        if name == cn_a_index_ts_codes.name:
            return list(self.codes)
        raise AssertionError(f"Unexpected partition set: {name}")

    def add_dynamic_partitions(self, name: str, keys: list[str]) -> None:
        self.partition_writes.append((name, tuple(keys)))
        target = self.dates if name == cn_a_index_trade_days.name else self.codes
        target.extend(key for key in keys if key not in target)

    def get_materialized_partitions(self, asset_key: dg.AssetKey) -> set[str]:
        return set(self.materialized.get(asset_key.to_user_string(), set()))

    def report_runless_asset_event(self, event: object) -> None:
        self.events.append(event)
