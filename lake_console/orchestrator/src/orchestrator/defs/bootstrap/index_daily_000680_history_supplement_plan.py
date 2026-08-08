"""Read-only M0/M1 plan for the 000680.SH index-daily supplement."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from orchestrator.defs.duckdb_sql import INDEX_DAILY_RAW_COLUMNS
from orchestrator.defs.partitions import cn_a_index_trade_days, cn_a_index_ts_codes
from orchestrator.defs.paths import (
    gold_market_major_indices_daily_path,
    raw_index_daily_path,
    silver_index_daily_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.prod_db.index_daily import (
    PROD_INDEX_DAILY_SOURCE_COLUMNS,
    PROD_INDEX_DAILY_SOURCE_TABLE,
)
from orchestrator.defs.resources import DuckDBResource, ProdPostgresResource
from orchestrator.seeds.market.major_indices import load_major_indices_seed

TARGET_CODE = "000680.SH"
HISTORY_START_DATE = "2020-01-02"
HISTORY_END_DATE = "2025-01-16"
EXPECTED_HISTORY_DATE_COUNT = 1_223
EXPECTED_TARGET_SEED_COUNT = 11
MAX_BATCH_DATE_COUNT = 100
DEFAULT_STAGING_ROOT = Path("/Volumes/datasource/data_lake_staging")
SUPPLEMENT_NAME = "index_daily_000680_history_supplement"

SOURCE_SELECT_SQL = f"""
SELECT
  ts_code,
  to_char(trade_date, 'YYYYMMDD') AS trade_date,
  open,
  high,
  low,
  close,
  pre_close,
  change_amount AS change,
  pct_chg,
  vol,
  amount
FROM {PROD_INDEX_DAILY_SOURCE_TABLE}
WHERE ts_code = '{TARGET_CODE}'
  AND trade_date BETWEEN DATE '{HISTORY_START_DATE}' AND DATE '{HISTORY_END_DATE}'
ORDER BY trade_date
"""

SOURCE_BOUNDARY_SQL = f"""
SELECT previous.close, following.pre_close
FROM {PROD_INDEX_DAILY_SOURCE_TABLE} previous
JOIN {PROD_INDEX_DAILY_SOURCE_TABLE} following
  ON following.ts_code = previous.ts_code
WHERE previous.ts_code = '{TARGET_CODE}'
  AND previous.trade_date = DATE '{HISTORY_END_DATE}'
  AND following.trade_date = DATE '2025-01-17'
"""


class IndexDaily000680HistorySupplementPlanError(ValueError):
    """Raised when the read-only supplement plan cannot be trusted."""


def hash_payload(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def hash_lines(values: Sequence[str]) -> str:
    return hashlib.sha256(("\n".join(values) + "\n").encode("utf-8")).hexdigest()


def _target_dates_from_serialized_plan(
    payload: Mapping[str, Any], layer: str
) -> tuple[str, ...]:
    targets = payload.get("targets")
    if not isinstance(targets, Mapping):
        raise IndexDaily000680HistorySupplementPlanError(
            "Frozen plan has no targets object."
        )
    values = targets.get(f"{layer}_files")
    if not isinstance(values, list):
        raise IndexDaily000680HistorySupplementPlanError(
            f"Frozen plan has no {layer} target files."
        )
    dates: list[str] = []
    for value in values:
        partition = next(
            (
                part.removeprefix("trade_date=")
                for part in Path(str(value)).parts
                if part.startswith("trade_date=")
            ),
            None,
        )
        if partition is None:
            raise IndexDaily000680HistorySupplementPlanError(
                f"Target path has no trade_date partition: {value}"
            )
        dates.append(partition)
    return tuple(dates)


def frozen_plan_hash_payload(payload: Mapping[str, Any]) -> dict[str, object]:
    """Return every write-relevant field covered by the frozen plan hash."""

    layer_audits = payload.get("layer_audits")
    seed = payload.get("seed")
    targets = payload.get("targets")
    if not isinstance(layer_audits, Mapping):
        raise IndexDaily000680HistorySupplementPlanError(
            "Frozen plan has no layer_audits object."
        )
    if not isinstance(seed, Mapping):
        raise IndexDaily000680HistorySupplementPlanError(
            "Frozen plan has no seed object."
        )
    if not isinstance(targets, Mapping):
        raise IndexDaily000680HistorySupplementPlanError(
            "Frozen plan has no targets object."
        )
    history_dates = _target_dates_from_serialized_plan(payload, "raw")
    silver_dates = _target_dates_from_serialized_plan(payload, "silver")
    gold_dates = _target_dates_from_serialized_plan(payload, "gold")
    if history_dates != silver_dates:
        raise IndexDaily000680HistorySupplementPlanError(
            "Raw and Silver target dates differ in the frozen plan."
        )
    return {
        "schema_version": payload.get("schema_version"),
        "code_commit": payload.get("code_commit"),
        "lake_root": payload.get("lake_root"),
        "staging_root": payload.get("staging_root"),
        "run_id": payload.get("run_id"),
        "target_code": payload.get("target_code"),
        "history_dates": history_dates,
        "gold_dates": gold_dates,
        "source_audit": payload.get("source_audit"),
        "raw_audit": layer_audits.get("raw"),
        "silver_audit": layer_audits.get("silver"),
        "gold_audit": layer_audits.get("gold"),
        "partition_audit": payload.get("partition_audit"),
        "source_query_hash": payload.get("source_query_hash"),
        "seed_file_path": seed.get("file_path"),
        "seed_file_hash": seed.get("file_hash"),
        "current_seed_count": seed.get("current_count"),
        "target_seed_count": seed.get("target_count"),
        "raw_target_files": tuple(targets.get("raw_files", ())),
        "silver_target_files": tuple(targets.get("silver_files", ())),
        "gold_target_files": tuple(targets.get("gold_files", ())),
        "max_batch_date_count": targets.get("max_batch_date_count"),
        "stop_reason_codes": tuple(payload.get("stop_reason_codes", ())),
    }


def compute_frozen_plan_hash(payload: Mapping[str, Any]) -> str:
    return hash_payload(frozen_plan_hash_payload(payload))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class SupplementSourceAudit:
    row_count: int
    distinct_date_count: int
    min_trade_date: str | None
    max_trade_date: str | None
    duplicate_key_count: int
    null_critical_row_count: int
    invalid_ohlc_row_count: int
    unexpected_code_count: int
    unexpected_date_count: int
    expected_date_missing_count: int
    unexpected_date_samples: tuple[str, ...]
    missing_date_samples: tuple[str, ...]
    date_fingerprint: str
    boundary_close: float | None
    following_pre_close: float | None
    boundary_matches: bool

    @property
    def passed(self) -> bool:
        return (
            self.row_count == EXPECTED_HISTORY_DATE_COUNT
            and self.distinct_date_count == EXPECTED_HISTORY_DATE_COUNT
            and self.min_trade_date == HISTORY_START_DATE
            and self.max_trade_date == HISTORY_END_DATE
            and self.duplicate_key_count == 0
            and self.null_critical_row_count == 0
            and self.invalid_ohlc_row_count == 0
            and self.unexpected_code_count == 0
            and self.unexpected_date_count == 0
            and self.expected_date_missing_count == 0
            and self.boundary_matches
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {"passed": self.passed}


@dataclass(frozen=True, slots=True)
class SupplementLayerAudit:
    layer: str
    expected_file_count: int
    existing_file_count: int
    missing_file_count: int
    target_row_count: int
    target_distinct_date_count: int
    target_duplicate_date_count: int
    missing_file_samples: tuple[str, ...]

    @property
    def files_complete(self) -> bool:
        return self.missing_file_count == 0

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {"files_complete": self.files_complete}


@dataclass(frozen=True, slots=True)
class SupplementPartitionAudit:
    date_partition_set: str
    code_partition_set: str
    expected_date_count: int
    missing_date_count: int
    missing_date_samples: tuple[str, ...]
    target_code_registered: bool
    registered_code_count: int

    @property
    def passed(self) -> bool:
        return self.missing_date_count == 0 and self.target_code_registered

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {"passed": self.passed}


@dataclass(frozen=True, slots=True)
class IndexDaily000680HistorySupplementPlan:
    generated_at: str
    code_commit: str
    lake_root: Path
    staging_root: Path
    run_id: str
    history_dates: tuple[str, ...]
    gold_dates: tuple[str, ...]
    source_audit: SupplementSourceAudit
    raw_audit: SupplementLayerAudit
    silver_audit: SupplementLayerAudit
    gold_audit: SupplementLayerAudit
    partition_audit: SupplementPartitionAudit
    source_query_hash: str
    seed_file_path: Path
    seed_file_hash: str
    current_seed_count: int
    target_seed_count: int
    raw_target_files: tuple[str, ...]
    silver_target_files: tuple[str, ...]
    gold_target_files: tuple[str, ...]
    plan_hash: str
    stop_reason_codes: tuple[str, ...]

    @property
    def should_stop(self) -> bool:
        return bool(self.stop_reason_codes)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "generated_at": self.generated_at,
            "code_commit": self.code_commit,
            "lake_root": str(self.lake_root),
            "staging_root": str(self.staging_root),
            "run_id": self.run_id,
            "target_code": TARGET_CODE,
            "history_start_date": HISTORY_START_DATE,
            "history_end_date": HISTORY_END_DATE,
            "history_date_count": len(self.history_dates),
            "history_date_fingerprint": hash_lines(self.history_dates),
            "gold_start_date": self.gold_dates[0],
            "gold_end_date": self.gold_dates[-1],
            "gold_date_count": len(self.gold_dates),
            "gold_date_fingerprint": hash_lines(self.gold_dates),
            "source_audit": self.source_audit.to_dict(),
            "layer_audits": {
                "raw": self.raw_audit.to_dict(),
                "silver": self.silver_audit.to_dict(),
                "gold": self.gold_audit.to_dict(),
            },
            "partition_audit": self.partition_audit.to_dict(),
            "source_query_hash": self.source_query_hash,
            "seed": {
                "file_path": str(self.seed_file_path),
                "file_hash": self.seed_file_hash,
                "current_count": self.current_seed_count,
                "target_count": self.target_seed_count,
            },
            "targets": {
                "raw_files": list(self.raw_target_files),
                "silver_files": list(self.silver_target_files),
                "gold_files": list(self.gold_target_files),
                "file_count": (
                    len(self.raw_target_files)
                    + len(self.silver_target_files)
                    + len(self.gold_target_files)
                ),
                "max_batch_date_count": MAX_BATCH_DATE_COUNT,
            },
            "performance_budget": {
                "source_query_count": 2,
                "source_row_count": self.source_audit.row_count,
                "raw_file_count": len(self.raw_target_files),
                "silver_file_count": len(self.silver_target_files),
                "gold_file_count": len(self.gold_target_files),
                "planned_file_promotion_count": (
                    len(self.raw_target_files)
                    + len(self.silver_target_files)
                    + len(self.gold_target_files)
                ),
                "batch_date_count_max": MAX_BATCH_DATE_COUNT,
            },
            "plan_hash": self.plan_hash,
            "should_stop": self.should_stop,
            "stop_reason_codes": list(self.stop_reason_codes),
            "writes": {
                "formal_lake": 0,
                "source_staging": 0,
                "dagster_db": 0,
                "dynamic_partitions": 0,
                "dagster_events": 0,
            },
        }


def _normalize_trade_date(value: object) -> str:
    text = value.isoformat() if isinstance(value, date) else str(value)
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return date.fromisoformat(text).isoformat()


def build_source_audit(
    *,
    rows: Sequence[Sequence[object]],
    expected_dates: Sequence[str],
    boundary_close: object | None,
    following_pre_close: object | None,
) -> SupplementSourceAudit:
    if tuple(INDEX_DAILY_RAW_COLUMNS) != tuple(PROD_INDEX_DAILY_SOURCE_COLUMNS):
        raise IndexDaily000680HistorySupplementPlanError(
            "Prod source columns do not match INDEX_DAILY_RAW_COLUMNS."
        )
    expected = tuple(expected_dates)
    expected_set = set(expected)
    observed_dates: list[str] = []
    key_counts: dict[tuple[str, str], int] = {}
    null_critical_row_count = 0
    invalid_ohlc_row_count = 0
    unexpected_code_count = 0
    for row in rows:
        if len(row) != len(INDEX_DAILY_RAW_COLUMNS):
            raise IndexDaily000680HistorySupplementPlanError(
                "Prod source row width does not match the Raw contract."
            )
        values = dict(zip(INDEX_DAILY_RAW_COLUMNS, row, strict=True))
        trade_date = _normalize_trade_date(values["trade_date"])
        ts_code = str(values["ts_code"] or "")
        observed_dates.append(trade_date)
        key = (ts_code, trade_date)
        key_counts[key] = key_counts.get(key, 0) + 1
        if ts_code != TARGET_CODE:
            unexpected_code_count += 1
        if any(values[column] is None for column in INDEX_DAILY_RAW_COLUMNS):
            null_critical_row_count += 1
        if all(values[column] is not None for column in ("open", "high", "low", "close")):
            open_value = float(values["open"])
            high_value = float(values["high"])
            low_value = float(values["low"])
            close_value = float(values["close"])
            if high_value < max(open_value, close_value, low_value) or low_value > min(
                open_value, close_value, high_value
            ):
                invalid_ohlc_row_count += 1
    distinct_dates = tuple(sorted(set(observed_dates)))
    missing_dates = tuple(sorted(expected_set - set(distinct_dates)))
    unexpected_dates = tuple(sorted(set(distinct_dates) - expected_set))
    normalized_boundary_close = (
        float(boundary_close) if boundary_close is not None else None
    )
    normalized_following_pre_close = (
        float(following_pre_close) if following_pre_close is not None else None
    )
    return SupplementSourceAudit(
        row_count=len(rows),
        distinct_date_count=len(distinct_dates),
        min_trade_date=distinct_dates[0] if distinct_dates else None,
        max_trade_date=distinct_dates[-1] if distinct_dates else None,
        duplicate_key_count=sum(count != 1 for count in key_counts.values()),
        null_critical_row_count=null_critical_row_count,
        invalid_ohlc_row_count=invalid_ohlc_row_count,
        unexpected_code_count=unexpected_code_count,
        unexpected_date_count=len(unexpected_dates),
        expected_date_missing_count=len(missing_dates),
        unexpected_date_samples=unexpected_dates[:10],
        missing_date_samples=missing_dates[:10],
        date_fingerprint=hash_lines(distinct_dates),
        boundary_close=normalized_boundary_close,
        following_pre_close=normalized_following_pre_close,
        boundary_matches=(
            normalized_boundary_close is not None
            and normalized_following_pre_close is not None
            and normalized_boundary_close == normalized_following_pre_close
        ),
    )


def read_prod_source_rows(
    prod_postgres: ProdPostgresResource,
) -> tuple[tuple[tuple[object, ...], ...], object | None, object | None]:
    with (
        prod_postgres.connect_readonly_transaction() as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(SOURCE_SELECT_SQL)
        rows = tuple(tuple(row) for row in cursor.fetchall())
        cursor.execute(SOURCE_BOUNDARY_SQL)
        boundary = cursor.fetchone()
    if boundary is None:
        return rows, None, None
    return rows, boundary[0], boundary[1]


def _read_calendar_dates(
    connection: Any,
    *,
    lake_root: Path,
    start_date: str,
    end_date: str | None,
) -> tuple[str, ...]:
    calendar_path = silver_trade_calendar_path(lake_root)
    if not calendar_path.is_file():
        raise IndexDaily000680HistorySupplementPlanError(
            f"Missing formal Silver trade calendar: {calendar_path}"
        )
    end_filter = "" if end_date is None else "AND CAST(trade_date AS DATE) <= CAST(? AS DATE)"
    params: list[object] = [str(calendar_path), start_date]
    if end_date is not None:
        params.append(end_date)
    rows = connection.execute(
        f"""
        SELECT CAST(trade_date AS DATE)::VARCHAR, count(*)
        FROM read_parquet(?)
        WHERE exchange = 'SSE'
          AND is_open = true
          AND CAST(trade_date AS DATE) >= CAST(? AS DATE)
          {end_filter}
        GROUP BY CAST(trade_date AS DATE)
        ORDER BY CAST(trade_date AS DATE)
        """,
        params,
    ).fetchall()
    duplicate_dates = [str(row[0]) for row in rows if int(row[1]) != 1]
    if duplicate_dates:
        raise IndexDaily000680HistorySupplementPlanError(
            f"Duplicate SSE calendar dates: {duplicate_dates[:10]}"
        )
    return tuple(str(row[0]) for row in rows)


def _read_existing_target_silver_dates(connection: Any, lake_root: Path) -> tuple[str, ...]:
    glob_path = lake_root / "silver" / "index_daily" / "trade_date=*" / "part-000.parquet"
    rows = connection.execute(
        """
        SELECT DISTINCT CAST(trade_date AS DATE)::VARCHAR
        FROM read_parquet(?, union_by_name=true)
        WHERE ts_code = ?
        ORDER BY 1
        """,
        [str(glob_path), TARGET_CODE],
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def _audit_layer(
    connection: Any,
    *,
    layer: str,
    paths: Sequence[Path],
) -> SupplementLayerAudit:
    missing = tuple(str(path) for path in paths if not path.is_file())
    existing = tuple(path for path in paths if path.is_file())
    if existing:
        date_expression = (
            "strptime(trade_date, '%Y%m%d')" if layer == "raw" else "CAST(trade_date AS DATE)"
        )
        row = connection.execute(
            f"""
            WITH target AS (
              SELECT {date_expression} AS normalized_trade_date
              FROM read_parquet(
                ?, union_by_name=true, hive_partitioning=false
              )
              WHERE ts_code = ?
            )
            SELECT
              count(*),
              count(DISTINCT normalized_trade_date),
              count(*) - count(DISTINCT normalized_trade_date)
            FROM target
            """,
            [[str(path) for path in existing], TARGET_CODE],
        ).fetchone()
        target_row_count = int(row[0])
        target_distinct_date_count = int(row[1])
        target_duplicate_date_count = int(row[2])
    else:
        target_row_count = 0
        target_distinct_date_count = 0
        target_duplicate_date_count = 0
    return SupplementLayerAudit(
        layer=layer,
        expected_file_count=len(paths),
        existing_file_count=len(existing),
        missing_file_count=len(missing),
        target_row_count=target_row_count,
        target_distinct_date_count=target_distinct_date_count,
        target_duplicate_date_count=target_duplicate_date_count,
        missing_file_samples=missing[:10],
    )


def _current_code_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def build_plan(
    *,
    lake_root: Path,
    staging_root: Path,
    duckdb_resource: DuckDBResource,
    source_rows: Sequence[Sequence[object]],
    boundary_close: object | None,
    following_pre_close: object | None,
    registered_dates: Sequence[str],
    registered_codes: Sequence[str],
    run_id: str,
    code_commit: str | None = None,
    enforce_formal_roots: bool = True,
) -> IndexDaily000680HistorySupplementPlan:
    lake_root = lake_root.resolve()
    staging_root = staging_root.resolve()
    if enforce_formal_roots and lake_root != Path("/Volumes/datasource/data_lake"):
        raise IndexDaily000680HistorySupplementPlanError(
            "M0/M1 formal Lake root must be /Volumes/datasource/data_lake."
        )
    if enforce_formal_roots and staging_root != DEFAULT_STAGING_ROOT:
        raise IndexDaily000680HistorySupplementPlanError(
            "M0/M1 staging root must be /Volumes/datasource/data_lake_staging."
        )
    with duckdb_resource.connect() as connection:
        history_dates = _read_calendar_dates(
            connection,
            lake_root=lake_root,
            start_date=HISTORY_START_DATE,
            end_date=HISTORY_END_DATE,
        )
        existing_target_silver_dates = _read_existing_target_silver_dates(
            connection, lake_root
        )
        if not existing_target_silver_dates:
            raise IndexDaily000680HistorySupplementPlanError(
                "Formal Silver has no current 000680.SH rows."
            )
        latest_target_silver_date = existing_target_silver_dates[-1]
        gold_dates = _read_calendar_dates(
            connection,
            lake_root=lake_root,
            start_date=HISTORY_START_DATE,
            end_date=latest_target_silver_date,
        )
        source_audit = build_source_audit(
            rows=source_rows,
            expected_dates=history_dates,
            boundary_close=boundary_close,
            following_pre_close=following_pre_close,
        )
        raw_paths = tuple(raw_index_daily_path(lake_root, value) for value in history_dates)
        silver_paths = tuple(
            silver_index_daily_path(lake_root, value) for value in history_dates
        )
        gold_paths = tuple(
            gold_market_major_indices_daily_path(lake_root, value) for value in gold_dates
        )
        raw_audit = _audit_layer(connection, layer="raw", paths=raw_paths)
        silver_audit = _audit_layer(connection, layer="silver", paths=silver_paths)
        gold_audit = _audit_layer(connection, layer="gold", paths=gold_paths)
    if len(history_dates) != EXPECTED_HISTORY_DATE_COUNT:
        raise IndexDaily000680HistorySupplementPlanError(
            "SSE history date count changed: "
            f"expected={EXPECTED_HISTORY_DATE_COUNT}, observed={len(history_dates)}."
        )
    registered_date_set = set(registered_dates)
    missing_registered_dates = tuple(
        value for value in history_dates if value not in registered_date_set
    )
    registered_code_set = set(registered_codes)
    partition_audit = SupplementPartitionAudit(
        date_partition_set=cn_a_index_trade_days.name,
        code_partition_set=cn_a_index_ts_codes.name,
        expected_date_count=len(history_dates),
        missing_date_count=len(missing_registered_dates),
        missing_date_samples=missing_registered_dates[:10],
        target_code_registered=TARGET_CODE in registered_code_set,
        registered_code_count=len(registered_code_set),
    )
    seed_path = (
        Path(__file__).resolve().parents[2]
        / "seeds"
        / "market"
        / "major_indices.cn_a.csv"
    )
    current_seed_count = len(load_major_indices_seed())
    source_query_hash = hash_payload(
        {
            "select": " ".join(SOURCE_SELECT_SQL.split()),
            "boundary": " ".join(SOURCE_BOUNDARY_SQL.split()),
            "columns": PROD_INDEX_DAILY_SOURCE_COLUMNS,
        }
    )
    seed_file_hash = file_sha256(seed_path)
    stop_reason_codes: list[str] = []
    if not source_audit.passed:
        stop_reason_codes.append("SOURCE_AUDIT_FAILED")
    if not raw_audit.files_complete:
        stop_reason_codes.append("RAW_FILE_MISSING")
    if not silver_audit.files_complete:
        stop_reason_codes.append("SILVER_FILE_MISSING")
    if not gold_audit.files_complete:
        stop_reason_codes.append("GOLD_FILE_MISSING")
    if not partition_audit.passed:
        stop_reason_codes.append("PARTITION_REGISTRY_INCOMPLETE")
    resolved_commit = code_commit or _current_code_commit()
    plan_hash_source: Mapping[str, Any] = {
        "schema_version": 1,
        "code_commit": resolved_commit,
        "lake_root": str(lake_root),
        "staging_root": str(staging_root),
        "run_id": run_id,
        "target_code": TARGET_CODE,
        "source_audit": source_audit.to_dict(),
        "layer_audits": {
            "raw": raw_audit.to_dict(),
            "silver": silver_audit.to_dict(),
            "gold": gold_audit.to_dict(),
        },
        "partition_audit": partition_audit.to_dict(),
        "source_query_hash": source_query_hash,
        "seed": {
            "file_path": str(seed_path),
            "file_hash": seed_file_hash,
            "current_count": current_seed_count,
            "target_count": EXPECTED_TARGET_SEED_COUNT,
        },
        "targets": {
            "raw_files": [str(path) for path in raw_paths],
            "silver_files": [str(path) for path in silver_paths],
            "gold_files": [str(path) for path in gold_paths],
            "max_batch_date_count": MAX_BATCH_DATE_COUNT,
        },
        "stop_reason_codes": stop_reason_codes,
    }
    return IndexDaily000680HistorySupplementPlan(
        generated_at=datetime.now(timezone.utc).isoformat(),
        code_commit=resolved_commit,
        lake_root=lake_root,
        staging_root=staging_root,
        run_id=run_id,
        history_dates=history_dates,
        gold_dates=gold_dates,
        source_audit=source_audit,
        raw_audit=raw_audit,
        silver_audit=silver_audit,
        gold_audit=gold_audit,
        partition_audit=partition_audit,
        source_query_hash=source_query_hash,
        seed_file_path=seed_path,
        seed_file_hash=seed_file_hash,
        current_seed_count=current_seed_count,
        target_seed_count=EXPECTED_TARGET_SEED_COUNT,
        raw_target_files=tuple(str(path) for path in raw_paths),
        silver_target_files=tuple(str(path) for path in silver_paths),
        gold_target_files=tuple(str(path) for path in gold_paths),
        plan_hash=compute_frozen_plan_hash(plan_hash_source),
        stop_reason_codes=tuple(stop_reason_codes),
    )


def run_dry_run(
    *,
    lake_root: Path,
    staging_root: Path,
    duckdb_resource: DuckDBResource,
    prod_postgres: ProdPostgresResource,
    instance: Any,
    run_id: str,
) -> IndexDaily000680HistorySupplementPlan:
    source_rows, boundary_close, following_pre_close = read_prod_source_rows(
        prod_postgres
    )
    return build_plan(
        lake_root=lake_root,
        staging_root=staging_root,
        duckdb_resource=duckdb_resource,
        source_rows=source_rows,
        boundary_close=boundary_close,
        following_pre_close=following_pre_close,
        registered_dates=instance.get_dynamic_partitions(cn_a_index_trade_days.name),
        registered_codes=instance.get_dynamic_partitions(cn_a_index_ts_codes.name),
        run_id=run_id,
    )


def write_report(
    plan: IndexDaily000680HistorySupplementPlan, output_path: Path
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(plan.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
