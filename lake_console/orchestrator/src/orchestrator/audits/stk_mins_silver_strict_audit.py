from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    raw_stk_mins_path,
    silver_namechange_path,
    silver_stock_basic_path,
    silver_stock_daily_path,
    silver_stock_identity_map_path,
    silver_stock_suspend_daily_path,
)
from orchestrator.defs.run_contracts.stk_mins import STK_MINS_FREQS


REPORT_FILE_SPECS: dict[str, tuple[str, tuple[str, ...]]] = {
    "summary": (
        "00_audit_summary.csv",
        ("category", "freq", "partition_key", "metric", "value"),
    ),
    "coverage": (
        "01_partition_coverage.csv",
        (
            "freq",
            "partition_key",
            "raw_file_exists",
            "raw_row_count",
            "daily_file_exists",
            "suspend_file_exists",
            "stock_basic_file_exists",
            "identity_map_file_exists",
            "namechange_file_exists",
            "status",
        ),
    ),
    "time_grid": (
        "02_time_grid_anomalies.csv",
        (
            "freq",
            "partition_key",
            "checked_row_count",
            "null_trade_time_count",
            "partition_date_mismatch_count",
            "failed_row_count",
        ),
    ),
    "exchange": (
        "03_exchange_anomalies.csv",
        (
            "freq",
            "partition_key",
            "checked_row_count",
            "normalized_sse_count",
            "normalized_szse_count",
            "normalized_bse_count",
            "existing_exchange_missing_count",
            "existing_exchange_differs_from_normalized_count",
            "suffix_unmapped_count",
            "failed_row_count",
        ),
    ),
    "price_zero_null": (
        "04_price_zero_null_anomalies.csv",
        (
            "freq",
            "partition_key",
            "ts_code",
            "trade_time",
            "open",
            "high",
            "low",
            "close",
            "null_price_fields",
            "zero_price_fields",
            "negative_price_fields",
            "reason",
        ),
    ),
    "price_relation": (
        "05_price_relation_anomalies.csv",
        (
            "freq",
            "partition_key",
            "ts_code",
            "trade_time",
            "open",
            "high",
            "low",
            "close",
            "high_low_error",
            "open_outside_range",
            "close_outside_range",
            "reason",
        ),
    ),
    "volume_amount_vwap": (
        "06_volume_amount_vwap_anomalies.csv",
        (
            "freq",
            "partition_key",
            "ts_code",
            "trade_time",
            "vol",
            "amount",
            "vwap",
            "expected_vwap",
            "vwap_abs_diff",
            "open",
            "high",
            "low",
            "close",
            "reason",
        ),
    ),
    "identity": (
        "07_identity_mapping_anomalies.csv",
        (
            "freq",
            "partition_key",
            "checked_code_count",
            "missing_source_mapping_count",
            "mapping_not_effective_count",
            "latest_ts_code_missing_count",
            "before_effective_list_date_count",
            "failed_code_count",
        ),
    ),
    "mapped_duplicates": (
        "08_mapped_duplicate_conflicts.csv",
        (
            "freq",
            "partition_key",
            "checked_group_count",
            "duplicate_group_count",
            "conflicting_duplicate_group_count",
            "exact_duplicate_group_count",
        ),
    ),
    "universe": (
        "09_stock_daily_suspend_universe_anomalies.csv",
        (
            "freq",
            "partition_key",
            "mapped_raw_code_count",
            "daily_code_count",
            "suspend_code_count",
            "raw_code_not_in_daily_or_suspend_count",
            "daily_code_not_in_mapped_raw_count",
        ),
    ),
    "name": (
        "10_name_timeline_coverage_anomalies.csv",
        (
            "freq",
            "partition_key",
            "mapped_raw_code_count",
            "covered_by_namechange_count",
            "covered_by_stock_basic_count",
            "missing_name_count",
        ),
    ),
    "samples": (
        "11_anomaly_samples.csv",
        (
            "anomaly_type",
            "freq",
            "partition_key",
            "ts_code",
            "latest_ts_code",
            "trade_time",
            "details_json",
        ),
    ),
}

DEFAULT_START_DATE = "2014-01-01"
NORMALIZED_EXCHANGES = ("SSE", "SZSE", "BSE")
VWAP_VALUE_TOLERANCE = 1.0
VWAP_PRICE_RANGE_TOLERANCE = 1.0


@dataclass(frozen=True)
class StkMinsSilverAuditDryRun:
    raw_partition_counts: Mapping[int, int]
    selected_partition_keys: tuple[str, ...]
    planned_asset_partition_count: int
    dependency_status: Mapping[str, bool]
    output_dir: Path


class CsvReportSet:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._files = {}
        self._writers = {}
        for key, (filename, fieldnames) in REPORT_FILE_SPECS.items():
            handle = (self.output_dir / filename).open(
                "w",
                newline="",
                encoding="utf-8",
            )
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            self._files[key] = handle
            self._writers[key] = writer

    def write(self, key: str, row: Mapping[str, Any]) -> None:
        fieldnames = REPORT_FILE_SPECS[key][1]
        self._writers[key].writerow(
            {field: _csv_value(row.get(field, "")) for field in fieldnames}
        )

    def close(self) -> None:
        for handle in self._files.values():
            handle.close()

    def __enter__(self) -> CsvReportSet:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


class AuditCounters:
    def __init__(self) -> None:
        self.metrics: Counter[tuple[str, str, str]] = Counter()

    def add(
        self,
        *,
        category: str,
        metric: str,
        value: int,
        freq: int | str = "",
        partition_key: str = "",
    ) -> None:
        self.metrics[(category, str(freq), partition_key, metric)] += int(value)

    def write_to(self, reports: CsvReportSet) -> None:
        for (category, freq, partition_key, metric), value in sorted(
            self.metrics.items()
        ):
            reports.write(
                "summary",
                {
                    "category": category,
                    "freq": freq,
                    "partition_key": partition_key,
                    "metric": metric,
                    "value": value,
                },
            )


def discover_raw_stk_mins_partitions(lake_root: Path) -> dict[int, tuple[str, ...]]:
    partitions_by_freq: dict[int, tuple[str, ...]] = {}
    for freq in STK_MINS_FREQS:
        raw_root = Path(lake_root) / "raw" / "tushare" / "stk_mins" / f"freq={freq}"
        partition_keys = sorted(
            path.parent.name.removeprefix("trade_date=")
            for path in raw_root.glob("trade_date=*/part-000.parquet")
            if path.is_file()
        )
        partitions_by_freq[freq] = tuple(partition_keys)
    return partitions_by_freq


def build_stk_mins_silver_audit_dry_run(
    *,
    lake_root: Path,
    output_dir: Path,
    partition_keys: Sequence[str] | None = None,
    start_date: str = DEFAULT_START_DATE,
) -> StkMinsSilverAuditDryRun:
    raw_partitions = discover_raw_stk_mins_partitions(lake_root)
    selected_keys = _select_partition_keys(raw_partitions, partition_keys, start_date)
    dependency_status = _dependency_status(lake_root)
    return StkMinsSilverAuditDryRun(
        raw_partition_counts={
            freq: len(partitions) for freq, partitions in raw_partitions.items()
        },
        selected_partition_keys=selected_keys,
        planned_asset_partition_count=len(selected_keys) * len(STK_MINS_FREQS),
        dependency_status=dependency_status,
        output_dir=output_dir,
    )


def run_stk_mins_silver_strict_audit(
    *,
    lake_root: Path,
    output_dir: Path,
    partition_keys: Sequence[str] | None = None,
    start_date: str = DEFAULT_START_DATE,
    sample_limit: int = 20,
) -> dict[str, int]:
    raw_partitions = discover_raw_stk_mins_partitions(lake_root)
    selected_keys = _select_partition_keys(raw_partitions, partition_keys, start_date)
    counters = AuditCounters()
    processed_count = 0

    with duckdb.connect(":memory:") as connection:
        with CsvReportSet(output_dir) as reports:
            _write_global_summary(
                reports,
                counters,
                lake_root=lake_root,
                raw_partitions=raw_partitions,
                selected_keys=selected_keys,
                start_date=start_date,
            )
            for freq in STK_MINS_FREQS:
                for partition_key in selected_keys:
                    if partition_key not in raw_partitions[freq]:
                        _write_partition_coverage(
                            reports,
                            counters,
                            connection=connection,
                            lake_root=lake_root,
                            freq=freq,
                            partition_key=partition_key,
                            raw_file_exists=False,
                        )
                        continue

                    raw_path = raw_stk_mins_path(lake_root, freq, partition_key)
                    _write_partition_coverage(
                        reports,
                        counters,
                        connection=connection,
                        lake_root=lake_root,
                        freq=freq,
                        partition_key=partition_key,
                        raw_file_exists=True,
                    )
                    _audit_partition_values(
                        reports,
                        counters,
                        connection=connection,
                        raw_path=raw_path,
                        freq=freq,
                        partition_key=partition_key,
                        sample_limit=sample_limit,
                    )
                    _audit_partition_identity(
                        reports,
                        counters,
                        connection=connection,
                        lake_root=lake_root,
                        raw_path=raw_path,
                        freq=freq,
                        partition_key=partition_key,
                        sample_limit=sample_limit,
                    )
                    processed_count += 1
                    if processed_count % 250 == 0:
                        print(f"processed_asset_partitions={processed_count}")

            counters.write_to(reports)

    return {
        "selected_partition_count": len(selected_keys),
        "processed_asset_partition_count": processed_count,
    }


def sample_partition_keys(lake_root: Path, *, start_date: str = DEFAULT_START_DATE) -> tuple[str, ...]:
    raw_partitions = discover_raw_stk_mins_partitions(lake_root)
    all_keys = _select_partition_keys(raw_partitions, None, start_date)
    if not all_keys:
        return ()
    return tuple(
        dict.fromkeys(
            (
                all_keys[0],
                all_keys[len(all_keys) // 2],
                all_keys[-1],
            )
        )
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Read-only strict silver audit for stk_mins raw files."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    dry_run = subparsers.add_parser("dry-run")
    _add_common_args(dry_run)
    _add_partition_args(dry_run)

    audit = subparsers.add_parser("audit")
    _add_common_args(audit)
    _add_partition_args(audit)
    audit.add_argument("--sample-limit", type=int, default=20)

    args = parser.parse_args(argv)
    lake_root = Path(args.lake_root)
    output_dir = Path(args.output_dir)
    partition_keys = _partition_keys_from_args(args, lake_root)
    start_date = args.start_date

    if args.command == "dry-run":
        plan = build_stk_mins_silver_audit_dry_run(
            lake_root=lake_root,
            output_dir=output_dir,
            partition_keys=partition_keys,
            start_date=start_date,
        )
        print(
            json.dumps(
                {
                    "raw_partition_counts": dict(plan.raw_partition_counts),
                    "selected_partition_count": len(plan.selected_partition_keys),
                    "selected_partition_min": (
                        min(plan.selected_partition_keys)
                        if plan.selected_partition_keys
                        else None
                    ),
                    "selected_partition_max": (
                        max(plan.selected_partition_keys)
                        if plan.selected_partition_keys
                        else None
                    ),
                    "planned_asset_partition_count": plan.planned_asset_partition_count,
                    "dependency_status": dict(plan.dependency_status),
                    "start_date": start_date,
                    "output_dir": str(plan.output_dir),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.command == "audit":
        result = run_stk_mins_silver_strict_audit(
            lake_root=lake_root,
            output_dir=output_dir,
            partition_keys=partition_keys,
            start_date=start_date,
            sample_limit=args.sample_limit,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument(
        "--output-dir",
        default="lake_console/reports/stk_mins_silver_audit_20260530",
    )


def _add_partition_args(parser: argparse.ArgumentParser) -> None:
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--partition-keys")
    selection.add_argument("--sample", action="store_true")
    selection.add_argument("--all", action="store_true")


def _partition_keys_from_args(args, lake_root: Path) -> tuple[str, ...] | None:
    if args.partition_keys:
        return tuple(
            sorted(key.strip() for key in args.partition_keys.split(",") if key.strip())
        )
    if args.sample:
        return sample_partition_keys(lake_root, start_date=args.start_date)
    if args.all:
        return None
    return None


def _write_global_summary(
    reports: CsvReportSet,
    counters: AuditCounters,
    *,
    lake_root: Path,
    raw_partitions: Mapping[int, Sequence[str]],
    selected_keys: Sequence[str],
    start_date: str,
) -> None:
    for freq, partitions in raw_partitions.items():
        counters.add(
            category="input",
            freq=freq,
            metric="raw_partition_count",
            value=len(partitions),
        )
    counters.add(
        category="input",
        metric="selected_partition_count",
        value=len(selected_keys),
    )
    counters.add(
        category="input",
        metric="planned_asset_partition_count",
        value=len(selected_keys) * len(STK_MINS_FREQS),
    )
    reports.write(
        "summary",
        {
            "category": "input",
            "metric": "start_date",
            "value": start_date,
        },
    )
    for name, exists in _dependency_status(lake_root).items():
        reports.write(
            "summary",
            {
                "category": "dependency",
                "metric": name,
                "value": int(exists),
            },
        )


def _write_partition_coverage(
    reports: CsvReportSet,
    counters: AuditCounters,
    *,
    connection,
    lake_root: Path,
    freq: int,
    partition_key: str,
    raw_file_exists: bool,
) -> None:
    raw_path = raw_stk_mins_path(lake_root, freq, partition_key)
    row_count = _count_rows(connection, raw_path) if raw_file_exists else None
    daily_exists = silver_stock_daily_path(lake_root, partition_key).exists()
    suspend_exists = silver_stock_suspend_daily_path(lake_root, partition_key).exists()
    basic_exists = silver_stock_basic_path(lake_root).exists()
    identity_exists = silver_stock_identity_map_path(lake_root).exists()
    namechange_exists = silver_namechange_path(lake_root).exists()
    missing = [
        name
        for name, exists in (
            ("raw", raw_file_exists),
            ("silver_stock_daily", daily_exists),
            ("silver_stock_suspend_daily", suspend_exists),
            ("silver_stock_basic", basic_exists),
            ("silver_stock_identity_map", identity_exists),
            ("silver_namechange", namechange_exists),
        )
        if not exists
    ]
    reports.write(
        "coverage",
        {
            "freq": freq,
            "partition_key": partition_key,
            "raw_file_exists": raw_file_exists,
            "raw_row_count": row_count if row_count is not None else "",
            "daily_file_exists": daily_exists,
            "suspend_file_exists": suspend_exists,
            "stock_basic_file_exists": basic_exists,
            "identity_map_file_exists": identity_exists,
            "namechange_file_exists": namechange_exists,
            "status": "ok" if not missing else "missing:" + ",".join(missing),
        },
    )
    counters.add(
        category="coverage",
        freq=freq,
        partition_key=partition_key,
        metric="raw_missing",
        value=0 if raw_file_exists else 1,
    )
    counters.add(
        category="coverage",
        freq=freq,
        partition_key=partition_key,
        metric="dependency_missing",
        value=len(missing) - (0 if raw_file_exists else 1),
    )


def _audit_partition_values(
    reports: CsvReportSet,
    counters: AuditCounters,
    *,
    connection,
    raw_path: Path,
    freq: int,
    partition_key: str,
    sample_limit: int,
) -> None:
    relation = _read_parquet(raw_path)

    time_row = connection.execute(
        f"""
        SELECT count(*) AS checked_row_count,
               sum(CASE WHEN trade_time IS NULL THEN 1 ELSE 0 END),
               sum(CASE WHEN trade_time IS NOT NULL
                          AND CAST(trade_time AS DATE) != DATE {_sql_string(partition_key)}
                        THEN 1 ELSE 0 END)
        FROM {relation}
        """
    ).fetchone()
    time_counts = {
        "checked_row_count": int(time_row[0] or 0),
        "null_trade_time_count": int(time_row[1] or 0),
        "partition_date_mismatch_count": int(time_row[2] or 0),
    }
    time_counts["failed_row_count"] = (
        time_counts["null_trade_time_count"]
        + time_counts["partition_date_mismatch_count"]
    )
    _write_count_report(
        reports,
        counters,
        key="time_grid",
        category="time_grid",
        freq=freq,
        partition_key=partition_key,
        row=time_counts,
    )
    _write_samples(
        reports,
        connection=connection,
        anomaly_type="time_grid",
        freq=freq,
        partition_key=partition_key,
        query=f"""
            SELECT ts_code, NULL AS latest_ts_code, trade_time
            FROM {relation}
            WHERE trade_time IS NULL
               OR CAST(trade_time AS DATE) != DATE {_sql_string(partition_key)}
            ORDER BY ts_code, trade_time
            LIMIT {int(sample_limit)}
        """,
    )

    exchange_row = connection.execute(
        f"""
        WITH annotated AS (
          SELECT *,
            CASE
              WHEN right(upper(CAST(ts_code AS VARCHAR)), 3) = '.SH' THEN 'SSE'
              WHEN right(upper(CAST(ts_code AS VARCHAR)), 3) = '.SZ' THEN 'SZSE'
              WHEN right(upper(CAST(ts_code AS VARCHAR)), 3) = '.BJ' THEN 'BSE'
              ELSE NULL
            END AS normalized_exchange
          FROM {relation}
        )
        SELECT count(*) AS checked_row_count,
               sum(CASE WHEN normalized_exchange = 'SSE' THEN 1 ELSE 0 END),
               sum(CASE WHEN normalized_exchange = 'SZSE' THEN 1 ELSE 0 END),
               sum(CASE WHEN normalized_exchange = 'BSE' THEN 1 ELSE 0 END),
               sum(CASE WHEN exchange IS NULL OR trim(CAST(exchange AS VARCHAR)) = '' THEN 1 ELSE 0 END),
               sum(CASE WHEN normalized_exchange IS NOT NULL
                          AND exchange IS NOT NULL
                          AND trim(CAST(exchange AS VARCHAR)) != ''
                          AND upper(CAST(exchange AS VARCHAR)) != normalized_exchange
                        THEN 1 ELSE 0 END),
               sum(CASE WHEN normalized_exchange IS NULL THEN 1 ELSE 0 END)
        FROM annotated
        """
    ).fetchone()
    exchange_counts = {
        "checked_row_count": int(exchange_row[0] or 0),
        "normalized_sse_count": int(exchange_row[1] or 0),
        "normalized_szse_count": int(exchange_row[2] or 0),
        "normalized_bse_count": int(exchange_row[3] or 0),
        "existing_exchange_missing_count": int(exchange_row[4] or 0),
        "existing_exchange_differs_from_normalized_count": int(exchange_row[5] or 0),
        "suffix_unmapped_count": int(exchange_row[6] or 0),
    }
    exchange_counts["failed_row_count"] = exchange_counts["suffix_unmapped_count"]
    _write_count_report(
        reports,
        counters,
        key="exchange",
        category="exchange",
        freq=freq,
        partition_key=partition_key,
        row=exchange_counts,
    )
    _write_samples(
        reports,
        connection=connection,
        anomaly_type="exchange",
        freq=freq,
        partition_key=partition_key,
        query=f"""
            WITH annotated AS (
              SELECT *,
                CASE
                  WHEN right(upper(CAST(ts_code AS VARCHAR)), 3) = '.SH' THEN 'SSE'
                  WHEN right(upper(CAST(ts_code AS VARCHAR)), 3) = '.SZ' THEN 'SZSE'
                  WHEN right(upper(CAST(ts_code AS VARCHAR)), 3) = '.BJ' THEN 'BSE'
                  ELSE NULL
                END AS normalized_exchange
              FROM {relation}
            )
            SELECT ts_code, NULL AS latest_ts_code, trade_time,
                   exchange, normalized_exchange
            FROM annotated
            WHERE normalized_exchange IS NULL
            ORDER BY ts_code, trade_time
            LIMIT {int(sample_limit)}
        """,
    )

    price_zero_row = connection.execute(
        f"""
        SELECT count(*) AS checked_row_count,
               sum(CASE WHEN open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL THEN 1 ELSE 0 END),
               sum(CASE WHEN open = 0 OR high = 0 OR low = 0 OR close = 0 THEN 1 ELSE 0 END),
               sum(CASE WHEN open < 0 OR high < 0 OR low < 0 OR close < 0 THEN 1 ELSE 0 END)
        FROM {relation}
        """
    ).fetchone()
    price_zero_counts = {
        "checked_row_count": int(price_zero_row[0]),
        "null_price_count": int(price_zero_row[1] or 0),
        "zero_price_count": int(price_zero_row[2] or 0),
        "negative_price_count": int(price_zero_row[3] or 0),
    }
    price_zero_counts["failed_row_count"] = sum(
        price_zero_counts[key]
        for key in ("null_price_count", "zero_price_count", "negative_price_count")
    )
    _add_count_metrics(
        counters,
        category="price_zero_null",
        freq=freq,
        partition_key=partition_key,
        row=price_zero_counts,
    )
    _write_query_rows(
        reports,
        key="price_zero_null",
        connection=connection,
        freq=freq,
        partition_key=partition_key,
        query=f"""
            SELECT ts_code, trade_time, open, high, low, close,
                   concat_ws('|',
                     CASE WHEN open IS NULL THEN 'open' ELSE NULL END,
                     CASE WHEN high IS NULL THEN 'high' ELSE NULL END,
                     CASE WHEN low IS NULL THEN 'low' ELSE NULL END,
                     CASE WHEN close IS NULL THEN 'close' ELSE NULL END
                   ) AS null_price_fields,
                   concat_ws('|',
                     CASE WHEN open = 0 THEN 'open' ELSE NULL END,
                     CASE WHEN high = 0 THEN 'high' ELSE NULL END,
                     CASE WHEN low = 0 THEN 'low' ELSE NULL END,
                     CASE WHEN close = 0 THEN 'close' ELSE NULL END
                   ) AS zero_price_fields,
                   concat_ws('|',
                     CASE WHEN open < 0 THEN 'open' ELSE NULL END,
                     CASE WHEN high < 0 THEN 'high' ELSE NULL END,
                     CASE WHEN low < 0 THEN 'low' ELSE NULL END,
                     CASE WHEN close < 0 THEN 'close' ELSE NULL END
                   ) AS negative_price_fields,
                   concat_ws('|',
                     CASE WHEN open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL THEN 'null_price' ELSE NULL END,
                     CASE WHEN open = 0 OR high = 0 OR low = 0 OR close = 0 THEN 'zero_price' ELSE NULL END,
                     CASE WHEN open < 0 OR high < 0 OR low < 0 OR close < 0 THEN 'negative_price' ELSE NULL END
                   ) AS reason
            FROM {relation}
            WHERE open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
               OR open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
            ORDER BY ts_code, trade_time
        """,
    )

    price_relation_row = connection.execute(
        f"""
        SELECT count(*) AS checked_row_count,
               sum(CASE WHEN high < low THEN 1 ELSE 0 END),
               sum(CASE WHEN open > high OR open < low THEN 1 ELSE 0 END),
               sum(CASE WHEN close > high OR close < low THEN 1 ELSE 0 END)
        FROM {relation}
        """
    ).fetchone()
    relation_counts = {
        "checked_row_count": int(price_relation_row[0]),
        "high_low_error_count": int(price_relation_row[1] or 0),
        "open_outside_range_count": int(price_relation_row[2] or 0),
        "close_outside_range_count": int(price_relation_row[3] or 0),
    }
    relation_counts["failed_row_count"] = sum(
        relation_counts[key]
        for key in (
            "high_low_error_count",
            "open_outside_range_count",
            "close_outside_range_count",
        )
    )
    _add_count_metrics(
        counters,
        category="price_relation",
        freq=freq,
        partition_key=partition_key,
        row=relation_counts,
    )
    _write_query_rows(
        reports,
        key="price_relation",
        connection=connection,
        freq=freq,
        partition_key=partition_key,
        query=f"""
            SELECT ts_code, trade_time, open, high, low, close,
                   high < low AS high_low_error,
                   open > high OR open < low AS open_outside_range,
                   close > high OR close < low AS close_outside_range,
                   concat_ws('|',
                     CASE WHEN high < low THEN 'high_low_error' ELSE NULL END,
                     CASE WHEN open > high OR open < low THEN 'open_outside_range' ELSE NULL END,
                     CASE WHEN close > high OR close < low THEN 'close_outside_range' ELSE NULL END
                   ) AS reason
            FROM {relation}
            WHERE high < low
               OR open > high OR open < low
               OR close > high OR close < low
            ORDER BY ts_code, trade_time
        """,
    )

    vwap_row = connection.execute(
        f"""
        WITH annotated AS (
          SELECT *,
                 CASE WHEN vol > 0 AND amount > 0 AND vwap > 0 THEN amount / vol ELSE NULL END AS expected_vwap
          FROM {relation}
        ),
        failed AS (
          SELECT *
          FROM annotated
          WHERE vol < 0 OR amount < 0 OR vwap < 0
             OR ((CASE WHEN vol IS NULL THEN 1 ELSE 0 END)
               + (CASE WHEN amount IS NULL THEN 1 ELSE 0 END)
               + (CASE WHEN vwap IS NULL THEN 1 ELSE 0 END)) >= 2
             OR (vol = 0 AND amount IS NOT NULL AND amount != 0)
             OR (vol > 0 AND amount IS NOT NULL AND amount <= 0)
             OR (vol > 0 AND vwap IS NOT NULL AND vwap <= 0)
             OR (vol > 0 AND amount > 0 AND vwap > 0
                 AND abs(vwap - amount / vol) > {VWAP_VALUE_TOLERANCE})
             OR (vwap IS NOT NULL AND low IS NOT NULL AND high IS NOT NULL
                 AND vwap > 0
                 AND (vwap < low - {VWAP_PRICE_RANGE_TOLERANCE}
                      OR vwap > high + {VWAP_PRICE_RANGE_TOLERANCE}))
        )
        SELECT
          (SELECT count(*) FROM annotated),
          sum(CASE WHEN vol < 0 OR amount < 0 OR vwap < 0 THEN 1 ELSE 0 END),
          sum(CASE WHEN ((CASE WHEN vol IS NULL THEN 1 ELSE 0 END)
                       + (CASE WHEN amount IS NULL THEN 1 ELSE 0 END)
                       + (CASE WHEN vwap IS NULL THEN 1 ELSE 0 END)) >= 2
                   THEN 1 ELSE 0 END),
          sum(CASE WHEN vol = 0 AND amount IS NOT NULL AND amount != 0 THEN 1 ELSE 0 END),
          sum(CASE WHEN vol > 0 AND amount IS NOT NULL AND amount <= 0 THEN 1 ELSE 0 END),
          sum(CASE WHEN vol > 0 AND vwap IS NOT NULL AND vwap <= 0 THEN 1 ELSE 0 END),
          sum(CASE WHEN vol > 0 AND amount > 0 AND vwap > 0
                    AND abs(vwap - amount / vol) > {VWAP_VALUE_TOLERANCE}
                   THEN 1 ELSE 0 END),
          sum(CASE WHEN vwap IS NOT NULL AND low IS NOT NULL AND high IS NOT NULL
                    AND vwap > 0
                    AND (vwap < low - {VWAP_PRICE_RANGE_TOLERANCE}
                         OR vwap > high + {VWAP_PRICE_RANGE_TOLERANCE})
                   THEN 1 ELSE 0 END),
          count(*)
        FROM failed
        """
    ).fetchone()
    vwap_counts = {
        "checked_row_count": int(vwap_row[0]),
        "negative_count": int(vwap_row[1] or 0),
        "not_computable_missing_count": int(vwap_row[2] or 0),
        "zero_volume_nonzero_amount_count": int(vwap_row[3] or 0),
        "positive_volume_nonpositive_amount_count": int(vwap_row[4] or 0),
        "vwap_nonpositive_with_positive_volume_count": int(vwap_row[5] or 0),
        "vwap_formula_conflict_count": int(vwap_row[6] or 0),
        "vwap_outside_price_range_count": int(vwap_row[7] or 0),
        "failed_row_count": int(vwap_row[8] or 0),
    }
    for metric, value in vwap_counts.items():
        if metric != "checked_row_count":
            counters.add(
                category="volume_amount_vwap",
                freq=freq,
                partition_key=partition_key,
                metric=metric,
                value=value,
            )
    _write_query_rows(
        reports,
        key="volume_amount_vwap",
        connection=connection,
        freq=freq,
        partition_key=partition_key,
        query=f"""
            WITH annotated AS (
              SELECT *,
                     CASE WHEN vol > 0 AND amount > 0 AND vwap > 0 THEN amount / vol ELSE NULL END AS expected_vwap
              FROM {relation}
            )
            SELECT ts_code, trade_time, vol, amount, vwap, expected_vwap,
                   CASE WHEN expected_vwap IS NOT NULL THEN abs(vwap - expected_vwap) ELSE NULL END AS vwap_abs_diff,
                   open, high, low, close,
                   concat_ws('|',
                     CASE WHEN vol < 0 OR amount < 0 OR vwap < 0 THEN 'negative_value' ELSE NULL END,
                     CASE WHEN ((CASE WHEN vol IS NULL THEN 1 ELSE 0 END)
                              + (CASE WHEN amount IS NULL THEN 1 ELSE 0 END)
                              + (CASE WHEN vwap IS NULL THEN 1 ELSE 0 END)) >= 2
                          THEN 'not_computable_missing_fields' ELSE NULL END,
                     CASE WHEN vol = 0 AND amount IS NOT NULL AND amount != 0 THEN 'zero_volume_nonzero_amount' ELSE NULL END,
                     CASE WHEN vol > 0 AND amount IS NOT NULL AND amount <= 0 THEN 'positive_volume_nonpositive_amount' ELSE NULL END,
                     CASE WHEN vol > 0 AND vwap IS NOT NULL AND vwap <= 0 THEN 'nonpositive_vwap_with_positive_volume' ELSE NULL END,
                     CASE WHEN vol > 0 AND amount > 0 AND vwap > 0
                            AND abs(vwap - amount / vol) > {VWAP_VALUE_TOLERANCE}
                          THEN 'vwap_formula_conflict' ELSE NULL END,
                     CASE WHEN vwap IS NOT NULL AND low IS NOT NULL AND high IS NOT NULL
                            AND vwap > 0
                            AND (vwap < low - {VWAP_PRICE_RANGE_TOLERANCE}
                                 OR vwap > high + {VWAP_PRICE_RANGE_TOLERANCE})
                          THEN 'vwap_outside_price_range' ELSE NULL END
                   ) AS reason
            FROM annotated
            WHERE vol < 0 OR amount < 0 OR vwap < 0
               OR ((CASE WHEN vol IS NULL THEN 1 ELSE 0 END)
                 + (CASE WHEN amount IS NULL THEN 1 ELSE 0 END)
                 + (CASE WHEN vwap IS NULL THEN 1 ELSE 0 END)) >= 2
               OR (vol = 0 AND amount IS NOT NULL AND amount != 0)
               OR (vol > 0 AND amount IS NOT NULL AND amount <= 0)
               OR (vol > 0 AND vwap IS NOT NULL AND vwap <= 0)
               OR (vol > 0 AND amount > 0 AND vwap > 0
                   AND abs(vwap - amount / vol) > {VWAP_VALUE_TOLERANCE})
               OR (vwap IS NOT NULL AND low IS NOT NULL AND high IS NOT NULL
                   AND vwap > 0
                   AND (vwap < low - {VWAP_PRICE_RANGE_TOLERANCE}
                        OR vwap > high + {VWAP_PRICE_RANGE_TOLERANCE}))
            ORDER BY ts_code, trade_time
        """,
    )


def _audit_partition_identity(
    reports: CsvReportSet,
    counters: AuditCounters,
    *,
    connection,
    lake_root: Path,
    raw_path: Path,
    freq: int,
    partition_key: str,
    sample_limit: int,
) -> None:
    identity_path = silver_stock_identity_map_path(lake_root)
    daily_path = silver_stock_daily_path(lake_root, partition_key)
    suspend_path = silver_stock_suspend_daily_path(lake_root, partition_key)
    basic_path = silver_stock_basic_path(lake_root)
    namechange_path = silver_namechange_path(lake_root)
    if not identity_path.exists():
        return

    relation = _read_parquet(raw_path)
    identity_relation = _read_parquet(identity_path)
    date_sql = f"DATE {_sql_string(partition_key)}"

    mapped_relation = _mapped_rows_sql(relation, identity_relation, partition_key)
    duplicate_row = connection.execute(
        f"""
        WITH mapped AS ({mapped_relation}),
        duplicate_groups AS (
          SELECT
            latest_ts_code,
            trade_time,
            count(*) AS row_count,
            count(DISTINCT ts_code) AS source_code_count,
            count(DISTINCT concat_ws('|',
              CAST(open AS VARCHAR),
              CAST(high AS VARCHAR),
              CAST(low AS VARCHAR),
              CAST(close AS VARCHAR),
              CAST(vol AS VARCHAR),
              CAST(amount AS VARCHAR),
              CAST(vwap AS VARCHAR)
            )) AS fact_variant_count
          FROM mapped
          GROUP BY latest_ts_code, trade_time
          HAVING count(*) > 1
        )
        SELECT
          (SELECT count(*) FROM mapped),
          count(*) AS duplicate_group_count,
          sum(CASE WHEN fact_variant_count > 1 THEN 1 ELSE 0 END),
          sum(CASE WHEN fact_variant_count = 1 THEN 1 ELSE 0 END)
        FROM duplicate_groups
        """
    ).fetchone()
    duplicate_counts = {
        "checked_group_count": int(duplicate_row[0] or 0),
        "duplicate_group_count": int(duplicate_row[1] or 0),
        "conflicting_duplicate_group_count": int(duplicate_row[2] or 0),
        "exact_duplicate_group_count": int(duplicate_row[3] or 0),
    }
    _write_count_report(
        reports,
        counters,
        key="mapped_duplicates",
        category="mapped_duplicates",
        freq=freq,
        partition_key=partition_key,
        row=duplicate_counts,
        failure_metric="conflicting_duplicate_group_count",
    )
    _write_samples(
        reports,
        connection=connection,
        anomaly_type="mapped_duplicate_conflict",
        freq=freq,
        partition_key=partition_key,
        query=f"""
            WITH mapped AS ({mapped_relation}),
            duplicate_groups AS (
              SELECT
                latest_ts_code,
                trade_time,
                count(DISTINCT concat_ws('|',
                  CAST(open AS VARCHAR),
                  CAST(high AS VARCHAR),
                  CAST(low AS VARCHAR),
                  CAST(close AS VARCHAR),
                  CAST(vol AS VARCHAR),
                  CAST(amount AS VARCHAR),
                  CAST(vwap AS VARCHAR)
                )) AS fact_variant_count
              FROM mapped
              GROUP BY latest_ts_code, trade_time
              HAVING count(*) > 1
                 AND count(DISTINCT concat_ws('|',
                  CAST(open AS VARCHAR),
                  CAST(high AS VARCHAR),
                  CAST(low AS VARCHAR),
                  CAST(close AS VARCHAR),
                  CAST(vol AS VARCHAR),
                  CAST(amount AS VARCHAR),
                  CAST(vwap AS VARCHAR)
                 )) > 1
            )
            SELECT mapped.ts_code, mapped.latest_ts_code, mapped.trade_time,
                   mapped.open, mapped.high, mapped.low, mapped.close,
                   mapped.vol, mapped.amount, mapped.vwap
            FROM mapped
            INNER JOIN duplicate_groups USING (latest_ts_code, trade_time)
            ORDER BY mapped.latest_ts_code, mapped.trade_time, mapped.ts_code
            LIMIT {int(sample_limit)}
        """,
    )

    if daily_path.exists() and suspend_path.exists():
        daily_relation = _read_parquet(daily_path)
        suspend_relation = _read_parquet(suspend_path)
        universe_row = connection.execute(
            f"""
            WITH mapped AS ({mapped_relation}),
            mapped_codes AS (
              SELECT DISTINCT latest_ts_code AS ts_code
              FROM mapped
            ),
            daily_codes AS (
              SELECT DISTINCT ts_code
              FROM {daily_relation}
            ),
            suspend_codes AS (
              SELECT DISTINCT ts_code
              FROM {suspend_relation}
            )
            SELECT
              (SELECT count(*) FROM mapped_codes),
              (SELECT count(*) FROM daily_codes),
              (SELECT count(*) FROM suspend_codes),
              (
                SELECT count(*)
                FROM mapped_codes
                LEFT JOIN daily_codes USING (ts_code)
                LEFT JOIN suspend_codes USING (ts_code)
                WHERE daily_codes.ts_code IS NULL
                  AND suspend_codes.ts_code IS NULL
              ),
              (
                SELECT count(*)
                FROM daily_codes
                LEFT JOIN mapped_codes USING (ts_code)
                WHERE mapped_codes.ts_code IS NULL
              )
            """
        ).fetchone()
        universe_counts = {
            "mapped_raw_code_count": int(universe_row[0] or 0),
            "daily_code_count": int(universe_row[1] or 0),
            "suspend_code_count": int(universe_row[2] or 0),
            "raw_code_not_in_daily_or_suspend_count": int(universe_row[3] or 0),
            "daily_code_not_in_mapped_raw_count": int(universe_row[4] or 0),
        }
        _write_count_report(
            reports,
            counters,
            key="universe",
            category="universe",
            freq=freq,
            partition_key=partition_key,
            row=universe_counts,
            failure_metric="raw_code_not_in_daily_or_suspend_count",
        )
        _write_samples(
            reports,
            connection=connection,
            anomaly_type="raw_code_not_in_daily_or_suspend",
            freq=freq,
            partition_key=partition_key,
            query=f"""
                WITH mapped AS ({mapped_relation}),
                mapped_codes AS (
                  SELECT DISTINCT latest_ts_code AS ts_code
                  FROM mapped
                ),
                daily_codes AS (
                  SELECT DISTINCT ts_code
                  FROM {daily_relation}
                ),
                suspend_codes AS (
                  SELECT DISTINCT ts_code
                  FROM {suspend_relation}
                )
                SELECT mapped_codes.ts_code, mapped_codes.ts_code AS latest_ts_code,
                       NULL AS trade_time
                FROM mapped_codes
                LEFT JOIN daily_codes USING (ts_code)
                LEFT JOIN suspend_codes USING (ts_code)
                WHERE daily_codes.ts_code IS NULL
                  AND suspend_codes.ts_code IS NULL
                ORDER BY mapped_codes.ts_code
                LIMIT {int(sample_limit)}
            """,
        )

    if basic_path.exists() and namechange_path.exists():
        basic_relation = _read_parquet(basic_path)
        namechange_relation = _read_parquet(namechange_path)
        name_row = connection.execute(
            f"""
            WITH mapped AS ({mapped_relation}),
            mapped_codes AS (
              SELECT DISTINCT latest_ts_code AS ts_code
              FROM mapped
            ),
            active_namechange AS (
              SELECT DISTINCT ts_code
              FROM {namechange_relation}
              WHERE {date_sql} >= start_date
                AND (end_date IS NULL OR {date_sql} <= end_date)
            ),
            basic_codes AS (
              SELECT DISTINCT ts_code
              FROM {basic_relation}
            )
            SELECT
              (SELECT count(*) FROM mapped_codes),
              (
                SELECT count(*)
                FROM mapped_codes
                INNER JOIN active_namechange USING (ts_code)
              ),
              (
                SELECT count(*)
                FROM mapped_codes
                INNER JOIN basic_codes USING (ts_code)
              ),
              (
                SELECT count(*)
                FROM mapped_codes
                LEFT JOIN active_namechange USING (ts_code)
                LEFT JOIN basic_codes USING (ts_code)
                WHERE active_namechange.ts_code IS NULL
                  AND basic_codes.ts_code IS NULL
              )
            """
        ).fetchone()
        name_counts = {
            "mapped_raw_code_count": int(name_row[0] or 0),
            "covered_by_namechange_count": int(name_row[1] or 0),
            "covered_by_stock_basic_count": int(name_row[2] or 0),
            "missing_name_count": int(name_row[3] or 0),
        }
        _write_count_report(
            reports,
            counters,
            key="name",
            category="name",
            freq=freq,
            partition_key=partition_key,
            row=name_counts,
            failure_metric="missing_name_count",
        )
        _write_samples(
            reports,
            connection=connection,
            anomaly_type="name_timeline_missing",
            freq=freq,
            partition_key=partition_key,
            query=f"""
                WITH mapped AS ({mapped_relation}),
                mapped_codes AS (
                  SELECT DISTINCT latest_ts_code AS ts_code
                  FROM mapped
                ),
                active_namechange AS (
                  SELECT DISTINCT ts_code
                  FROM {namechange_relation}
                  WHERE {date_sql} >= start_date
                    AND (end_date IS NULL OR {date_sql} <= end_date)
                ),
                basic_codes AS (
                  SELECT DISTINCT ts_code
                  FROM {basic_relation}
                )
                SELECT mapped_codes.ts_code, mapped_codes.ts_code AS latest_ts_code,
                       NULL AS trade_time
                FROM mapped_codes
                LEFT JOIN active_namechange USING (ts_code)
                LEFT JOIN basic_codes USING (ts_code)
                WHERE active_namechange.ts_code IS NULL
                  AND basic_codes.ts_code IS NULL
                ORDER BY mapped_codes.ts_code
                LIMIT {int(sample_limit)}
            """,
        )


def _mapped_rows_sql(raw_relation: str, identity_relation: str, partition_key: str) -> str:
    date_sql = f"DATE {_sql_string(partition_key)}"
    return f"""
        SELECT
          raw.*,
          id.latest_ts_code
        FROM {raw_relation} raw
        INNER JOIN {identity_relation} id
          ON raw.ts_code = id.source_ts_code
         AND {date_sql} >= id.valid_from
         AND (id.valid_to IS NULL OR {date_sql} < id.valid_to)
        WHERE id.latest_ts_code IS NOT NULL
          AND trim(CAST(id.latest_ts_code AS VARCHAR)) != ''
    """


def _write_count_report(
    reports: CsvReportSet,
    counters: AuditCounters,
    *,
    key: str,
    category: str,
    freq: int,
    partition_key: str,
    row: Mapping[str, Any],
    failure_metric: str = "failed_row_count",
) -> None:
    reports.write(
        key,
        {
            "freq": freq,
            "partition_key": partition_key,
            **row,
        },
    )
    if failure_metric in row:
        counters.add(
            category=category,
            freq=freq,
            partition_key=partition_key,
            metric=failure_metric,
            value=int(row[failure_metric] or 0),
        )


def _add_count_metrics(
    counters: AuditCounters,
    *,
    category: str,
    freq: int,
    partition_key: str,
    row: Mapping[str, Any],
) -> None:
    for metric, value in row.items():
        if metric == "checked_row_count":
            continue
        counters.add(
            category=category,
            freq=freq,
            partition_key=partition_key,
            metric=metric,
            value=int(value or 0),
        )


def _write_samples(
    reports: CsvReportSet,
    *,
    connection,
    anomaly_type: str,
    freq: int,
    partition_key: str,
    query: str,
) -> None:
    rows = connection.execute(query).fetchall()
    columns = [description[0] for description in connection.description]
    for row in rows:
        sample = dict(zip(columns, row, strict=True))
        reports.write(
            "samples",
            {
                "anomaly_type": anomaly_type,
                "freq": freq,
                "partition_key": partition_key,
                "ts_code": sample.pop("ts_code", ""),
                "latest_ts_code": sample.pop("latest_ts_code", ""),
                "trade_time": _csv_value(sample.pop("trade_time", "")),
                "details_json": json.dumps(
                    _json_safe(sample),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            },
        )


def _write_query_rows(
    reports: CsvReportSet,
    *,
    key: str,
    connection,
    freq: int,
    partition_key: str,
    query: str,
) -> None:
    cursor = connection.execute(query)
    columns = [description[0] for description in connection.description]
    while True:
        rows = cursor.fetchmany(10_000)
        if not rows:
            break
        for row in rows:
            item = dict(zip(columns, row, strict=True))
            reports.write(
                key,
                {
                    "freq": freq,
                    "partition_key": partition_key,
                    **item,
                },
            )


def _dependency_status(lake_root: Path) -> dict[str, bool]:
    return {
        "silver_stock_basic": silver_stock_basic_path(lake_root).exists(),
        "silver_stock_identity_map": silver_stock_identity_map_path(lake_root).exists(),
        "silver_namechange": silver_namechange_path(lake_root).exists(),
    }


def _select_partition_keys(
    raw_partitions: Mapping[int, Sequence[str]],
    partition_keys: Sequence[str] | None,
    start_date: str,
) -> tuple[str, ...]:
    if partition_keys is not None:
        keys = tuple(sorted(dict.fromkeys(partition_keys)))
    else:
        keys = tuple(sorted(set().union(*(set(keys) for keys in raw_partitions.values()))))
    return tuple(key for key in keys if key >= start_date)


def _read_parquet(path: Path) -> str:
    return f"read_parquet({_sql_string(path.as_posix())}, hive_partitioning=false)"


def _count_rows(connection, path: Path) -> int:
    return int(connection.execute(f"SELECT count(*) FROM {_read_parquet(path)}").fetchone()[0])


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


if __name__ == "__main__":
    main()
