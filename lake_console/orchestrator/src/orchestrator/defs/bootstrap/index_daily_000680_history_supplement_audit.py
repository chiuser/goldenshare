"""Read-only physical audit for the 000680.SH history supplement."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from orchestrator.defs.bootstrap.index_daily_000680_history_supplement_apply import (
    load_frozen_plan,
)
from orchestrator.defs.bootstrap.index_daily_000680_history_supplement_plan import (
    TARGET_CODE,
    hash_payload,
)
from orchestrator.defs.resources import DuckDBResource


class IndexDaily000680HistorySupplementAuditError(RuntimeError):
    """Raised when the formal Lake cannot be audited safely."""


@dataclass(frozen=True, slots=True)
class PhysicalLayerAudit:
    layer: str
    expected_file_count: int
    existing_file_count: int
    missing_file_count: int
    target_row_count: int
    target_distinct_date_count: int
    target_duplicate_key_count: int
    target_missing_file_count: int
    invalid_partition_row_count: int
    target_fingerprint: str
    missing_file_samples: tuple[str, ...]
    target_missing_file_samples: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return (
            self.existing_file_count == self.expected_file_count
            and self.missing_file_count == 0
            and self.target_row_count == self.expected_file_count
            and self.target_distinct_date_count == self.expected_file_count
            and self.target_duplicate_key_count == 0
            and self.target_missing_file_count == 0
            and self.invalid_partition_row_count == 0
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {"passed": self.passed}


@dataclass(frozen=True, slots=True)
class PhysicalAuditReport:
    plan_hash: str
    raw: PhysicalLayerAudit
    silver: PhysicalLayerAudit
    gold: PhysicalLayerAudit
    raw_silver_history_matches: bool
    silver_gold_matches: bool
    audit_hash: str

    @property
    def passed(self) -> bool:
        return (
            self.raw.passed
            and self.silver.passed
            and self.gold.passed
            and self.raw_silver_history_matches
            and self.silver_gold_matches
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "target_code": TARGET_CODE,
            "plan_hash": self.plan_hash,
            "layers": {
                "raw": self.raw.to_dict(),
                "silver": self.silver.to_dict(),
                "gold": self.gold.to_dict(),
            },
            "cross_layer": {
                "raw_silver_history_matches": self.raw_silver_history_matches,
                "silver_gold_matches": self.silver_gold_matches,
            },
            "audit_hash": self.audit_hash,
            "passed": self.passed,
            "writes": {
                "formal_lake": 0,
                "dagster_db": 0,
                "dynamic_partitions": 0,
                "dagster_events": 0,
            },
        }


def _partition_key(path: Path) -> str:
    for part in path.parts:
        if part.startswith("trade_date="):
            return part.removeprefix("trade_date=")
    raise IndexDaily000680HistorySupplementAuditError(
        f"Target path has no trade_date partition: {path}"
    )


def _canonical_target_rows(
    connection: Any,
    *,
    layer: str,
    paths: Sequence[Path],
) -> tuple[tuple[object, ...], ...]:
    if not paths:
        return ()
    date_expression = (
        "strptime(trade_date, '%Y%m%d')" if layer == "raw" else "CAST(trade_date AS DATE)"
    )
    change_column = "change" if layer == "raw" else "change_amount"
    rows = connection.execute(
        f"""
        SELECT
          CAST({date_expression} AS DATE)::VARCHAR,
          open,
          high,
          low,
          close,
          pre_close,
          {change_column},
          pct_chg,
          vol,
          amount
        FROM read_parquet(?, hive_partitioning=false)
        WHERE ts_code = ?
        ORDER BY 1
        """,
        [[str(path) for path in paths], TARGET_CODE],
    ).fetchall()
    return tuple(tuple(value) for value in rows)


def audit_layer(
    connection: Any,
    *,
    layer: str,
    paths: Sequence[Path],
) -> tuple[PhysicalLayerAudit, tuple[tuple[object, ...], ...]]:
    missing = tuple(path for path in paths if not path.is_file())
    existing = tuple(path for path in paths if path.is_file())
    target_rows = _canonical_target_rows(
        connection,
        layer=layer,
        paths=existing,
    )
    expected_date_by_file = {str(path): _partition_key(path) for path in existing}
    target_counts_by_file: dict[str, int] = {value: 0 for value in expected_date_by_file}
    invalid_partition_row_count = 0
    duplicate_key_count = 0
    if existing:
        date_expression = (
            "strptime(trade_date, '%Y%m%d')"
            if layer == "raw"
            else "CAST(trade_date AS DATE)"
        )
        target_file_rows = connection.execute(
            f"""
            SELECT filename, CAST({date_expression} AS DATE)::VARCHAR, count(*)
            FROM read_parquet(?, filename=true, hive_partitioning=false)
            WHERE ts_code = ?
            GROUP BY filename, CAST({date_expression} AS DATE)
            ORDER BY filename
            """,
            [[str(path) for path in existing], TARGET_CODE],
        ).fetchall()
        for filename, trade_date, row_count in target_file_rows:
            normalized_filename = str(filename)
            count = int(row_count)
            target_counts_by_file[normalized_filename] = (
                target_counts_by_file.get(normalized_filename, 0) + count
            )
            duplicate_key_count += max(count - 1, 0)
            if str(trade_date) != expected_date_by_file.get(normalized_filename):
                invalid_partition_row_count += count
    target_missing_files = tuple(
        filename for filename, count in target_counts_by_file.items() if count != 1
    )
    audit = PhysicalLayerAudit(
        layer=layer,
        expected_file_count=len(paths),
        existing_file_count=len(existing),
        missing_file_count=len(missing),
        target_row_count=len(target_rows),
        target_distinct_date_count=len({str(row[0]) for row in target_rows}),
        target_duplicate_key_count=duplicate_key_count,
        target_missing_file_count=len(target_missing_files),
        invalid_partition_row_count=invalid_partition_row_count,
        target_fingerprint=hash_payload(target_rows),
        missing_file_samples=tuple(str(path) for path in missing[:10]),
        target_missing_file_samples=target_missing_files[:10],
    )
    return audit, target_rows


def audit_formal_lake(
    *,
    plan_path: Path,
    expected_plan_hash: str,
    duckdb_resource: DuckDBResource,
) -> PhysicalAuditReport:
    plan = load_frozen_plan(
        plan_path,
        expected_plan_hash=expected_plan_hash,
        require_green=True,
    )
    targets = plan.get("targets")
    if not isinstance(targets, Mapping):
        raise IndexDaily000680HistorySupplementAuditError(
            "Frozen plan has no targets object."
        )
    raw_paths = tuple(Path(str(value)) for value in targets["raw_files"])
    silver_history_paths = tuple(Path(str(value)) for value in targets["silver_files"])
    gold_paths = tuple(Path(str(value)) for value in targets["gold_files"])
    lake_root = Path(str(plan["lake_root"]))
    silver_gold_paths = tuple(
        lake_root / "silver" / "index_daily" / path.parent.name / path.name
        for path in gold_paths
    )
    with duckdb_resource.connect() as connection:
        raw_audit, raw_rows = audit_layer(
            connection,
            layer="raw",
            paths=raw_paths,
        )
        silver_audit, silver_history_rows = audit_layer(
            connection,
            layer="silver",
            paths=silver_history_paths,
        )
        gold_audit, gold_rows = audit_layer(
            connection,
            layer="gold",
            paths=gold_paths,
        )
        _, silver_gold_rows = audit_layer(
            connection,
            layer="silver",
            paths=silver_gold_paths,
        )
    raw_silver_matches = raw_rows == silver_history_rows
    silver_gold_matches = silver_gold_rows == gold_rows
    payload = {
        "plan_hash": expected_plan_hash,
        "raw": raw_audit.to_dict(),
        "silver": silver_audit.to_dict(),
        "gold": gold_audit.to_dict(),
        "raw_silver_history_matches": raw_silver_matches,
        "silver_gold_matches": silver_gold_matches,
    }
    return PhysicalAuditReport(
        plan_hash=expected_plan_hash,
        raw=raw_audit,
        silver=silver_audit,
        gold=gold_audit,
        raw_silver_history_matches=raw_silver_matches,
        silver_gold_matches=silver_gold_matches,
        audit_hash=hash_payload(payload),
    )


def write_report(report: PhysicalAuditReport, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
