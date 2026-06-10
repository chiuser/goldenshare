from __future__ import annotations

import argparse
import csv
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import duckdb

from orchestrator.defs.duckdb_sql import copy_query_to_parquet, duckdb_string, read_parquet
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    silver_adj_factor_path,
    silver_stk_mins_path,
)
from orchestrator.defs.stk_mins_qfq import build_daily_qfq_select_sql
from orchestrator.defs.run_contracts.asset_column_schemas import SILVER_STK_MINS_SCHEMA
from orchestrator.defs.run_contracts.stk_mins import (
    STK_MINS_FREQS,
    normalize_stk_mins_freq,
)


REPORT_JSON = "m7a_qfq_performance_summary.json"
REPORT_CSV = "m7a_qfq_performance_summary.csv"
GOLD_QFQ_COLUMNS = tuple(column.name for column in SILVER_STK_MINS_SCHEMA)


@dataclass(frozen=True)
class PerformanceMetric:
    scenario: str
    freq: int | None
    sample_days: int | None
    partition_count: int
    row_count: int
    elapsed_seconds: float
    input_bytes: int
    output_bytes: int
    output_path: str

    def as_dict(self) -> dict[str, object]:
        return {
            "scenario": self.scenario,
            "freq": self.freq,
            "sample_days": self.sample_days,
            "partition_count": self.partition_count,
            "row_count": self.row_count,
            "elapsed_seconds": round(self.elapsed_seconds, 6),
            "input_bytes": self.input_bytes,
            "output_bytes": self.output_bytes,
            "output_path": self.output_path,
        }


def assert_output_dir_is_safe(*, lake_root: Path, output_dir: Path) -> None:
    output = output_dir.expanduser().resolve(strict=False)
    lake = lake_root.expanduser().resolve(strict=False)
    default_lake = Path(DEFAULT_LAKE_ROOT).expanduser().resolve(strict=False)
    if _is_relative_to(output, lake) or _is_relative_to(output, default_lake):
        raise ValueError(
            "M7A qfq performance output_dir must not be inside the formal lake root: "
            f"{output}"
        )


def build_qfq_performance_plan(
    *,
    lake_root: Path,
    output_dir: Path,
    trade_date: str,
    stock_code: str,
    repair_sample_days: Sequence[int],
) -> dict[str, object]:
    assert_output_dir_is_safe(lake_root=lake_root, output_dir=output_dir)
    normalized_days = _normalize_sample_days(repair_sample_days)
    silver_daily_files = {
        str(freq): str(silver_stk_mins_path(lake_root, freq, trade_date))
        for freq in STK_MINS_FREQS
    }
    silver_daily_exists = {
        str(freq): Path(path).exists() for freq, path in silver_daily_files.items()
    }
    trade_date_adj_factor_path = silver_adj_factor_path(lake_root, trade_date)
    selected_sample_dates = {
        str(days): _select_recent_partition_keys(
            _discover_silver_partition_keys(lake_root, 1),
            end_partition_key=trade_date,
            limit=days,
        )
        for days in normalized_days
    }
    return {
        "command": "dry-run",
        "lake_root": str(lake_root),
        "output_dir": str(output_dir),
        "trade_date": trade_date,
        "stock_code": stock_code,
        "freqs": list(STK_MINS_FREQS),
        "silver_daily_files": silver_daily_files,
        "silver_daily_exists": silver_daily_exists,
        "trade_date_adj_factor_path": str(trade_date_adj_factor_path),
        "trade_date_adj_factor_exists": trade_date_adj_factor_path.exists(),
        "as_of_adj_factor_path": str(trade_date_adj_factor_path),
        "as_of_trade_date": trade_date,
        "repair_sample_days": list(normalized_days),
        "selected_sample_dates": selected_sample_dates,
        "will_write_files": False,
    }


def run_qfq_benchmark(
    *,
    lake_root: Path,
    output_dir: Path,
    trade_date: str,
    stock_code: str,
    repair_sample_days: Sequence[int],
) -> dict[str, object]:
    assert_output_dir_is_safe(lake_root=lake_root, output_dir=output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized_days = _normalize_sample_days(repair_sample_days)
    as_of_adj_path = _require_file(silver_adj_factor_path(lake_root, trade_date))
    metrics: list[PerformanceMetric] = []

    for freq in STK_MINS_FREQS:
        silver_path = _require_file(silver_stk_mins_path(lake_root, freq, trade_date))
        adj_path = _require_file(silver_adj_factor_path(lake_root, trade_date))
        target_path = output_dir / "daily_all_market" / f"freq={freq}" / f"trade_date={trade_date}" / "part-000.parquet"
        metrics.append(
            _time_copy_query(
                scenario="daily_all_market_qfq",
                freq=freq,
                sample_days=None,
                partition_count=1,
                select_sql=build_daily_qfq_select_sql(
                    silver_paths=[silver_path],
                    trade_adj_factor_paths=[adj_path],
                    as_of_adj_factor_paths=[as_of_adj_path],
                ),
                target_path=target_path,
                input_paths=[silver_path, adj_path],
            )
        )

    max_sample_days = max(normalized_days)
    history_dates = _select_recent_partition_keys(
        _discover_silver_partition_keys(lake_root, 1),
        end_partition_key=trade_date,
        limit=max_sample_days,
    )
    if not history_dates:
        raise FileNotFoundError("No silver stk_mins partitions found for qfq history benchmark.")

    for freq in STK_MINS_FREQS:
        silver_paths = [_require_file(silver_stk_mins_path(lake_root, freq, key)) for key in history_dates]
        adj_paths = [_require_file(silver_adj_factor_path(lake_root, key)) for key in history_dates]
        target_path = output_dir / "history_code_subset" / f"freq={freq}" / f"stock_code={stock_code}" / "part-000.parquet"
        metrics.append(
            _time_copy_query(
                scenario="history_code_subset_qfq",
                freq=freq,
                sample_days=max_sample_days,
                partition_count=len(history_dates),
                select_sql=f"""
                SELECT *
                FROM (
                  {build_daily_qfq_select_sql(
                      silver_paths=silver_paths,
                      trade_adj_factor_paths=adj_paths,
                      as_of_adj_factor_paths=[as_of_adj_path],
                  )}
                )
                WHERE ts_code = {duckdb_string(stock_code)}
                """,
                target_path=target_path,
                input_paths=[*silver_paths, *adj_paths, as_of_adj_path],
            )
        )

    for sample_days in normalized_days:
        sample_dates = history_dates[-sample_days:]
        for freq in STK_MINS_FREQS:
            metrics.append(
                _benchmark_partition_rewrite(
                    lake_root=lake_root,
                    output_dir=output_dir,
                    freq=freq,
                    stock_code=stock_code,
                    sample_days=sample_days,
                    partition_keys=sample_dates,
                    as_of_adj_factor_path=as_of_adj_path,
                )
            )

    report = {
        "command": "benchmark",
        "lake_root": str(lake_root),
        "output_dir": str(output_dir),
        "trade_date": trade_date,
        "stock_code": stock_code,
        "repair_sample_days": list(normalized_days),
        "metrics": [metric.as_dict() for metric in metrics],
    }
    _write_report(output_dir, report)
    return report


def rewrite_qfq_partition_for_stock_code(
    *,
    existing_partition_path: Path,
    replacement_rows_path: Path,
    stock_code: str,
    target_path: Path,
) -> int:
    _require_file(existing_partition_path)
    _require_file(replacement_rows_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = _temp_path_for(target_path)
    if temp_path.exists():
        temp_path.unlink()
    select_columns = ", ".join(GOLD_QFQ_COLUMNS)
    with duckdb.connect(database=":memory:") as connection:
        replacement_row_count = connection.execute(
            f"""
            SELECT count(*)
            FROM {read_parquet(replacement_rows_path, hive_partitioning=False)}
            WHERE ts_code = {duckdb_string(stock_code)}
            """
        ).fetchone()[0]
        if replacement_row_count == 0:
            raise ValueError(
                "Replacement qfq rows are empty for stock_code; refusing to delete "
                f"existing rows for {stock_code}."
            )
        connection.execute(
            copy_query_to_parquet(
                f"""
                WITH merged AS (
                  SELECT {select_columns}
                  FROM {read_parquet(existing_partition_path, hive_partitioning=False)}
                  WHERE ts_code <> {duckdb_string(stock_code)}
                  UNION ALL
                  SELECT {select_columns}
                  FROM {read_parquet(replacement_rows_path, hive_partitioning=False)}
                  WHERE ts_code = {duckdb_string(stock_code)}
                )
                SELECT *
                FROM merged
                ORDER BY ts_code, trade_time
                """,
                temp_path,
            )
        )
        duplicate_count = connection.execute(
            f"""
            SELECT count(*)
            FROM (
              SELECT ts_code, trade_time, count(*) AS duplicate_count
              FROM {read_parquet(temp_path, hive_partitioning=False)}
              GROUP BY ts_code, trade_time
              HAVING count(*) > 1
            )
            """
        ).fetchone()[0]
        if duplicate_count:
            temp_path.unlink(missing_ok=True)
            raise ValueError(
                "Merged qfq partition has duplicate ts_code + trade_time keys: "
                f"{duplicate_count}"
            )
        row_count = connection.execute(
            f"SELECT count(*) FROM {read_parquet(temp_path, hive_partitioning=False)}"
        ).fetchone()[0]
    os.replace(temp_path, target_path)
    return int(row_count)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    sample_days = _parse_sample_days(args.repair_sample_days)
    if args.command == "dry-run":
        plan = build_qfq_performance_plan(
            lake_root=Path(args.lake_root),
            output_dir=Path(args.output_dir),
            trade_date=args.trade_date,
            stock_code=args.stock_code,
            repair_sample_days=sample_days,
        )
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    if args.command == "benchmark":
        report = run_qfq_benchmark(
            lake_root=Path(args.lake_root),
            output_dir=Path(args.output_dir),
            trade_date=args.trade_date,
            stock_code=args.stock_code,
            repair_sample_days=sample_days,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    raise ValueError(f"Unsupported command: {args.command}")


def _benchmark_partition_rewrite(
    *,
    lake_root: Path,
    output_dir: Path,
    freq: int,
    stock_code: str,
    sample_days: int,
    partition_keys: Sequence[str],
    as_of_adj_factor_path: Path,
) -> PerformanceMetric:
    scenario_dir = output_dir / "repair_partition_rewrite" / f"sample_days={sample_days}" / f"freq={freq}"
    input_paths: list[Path] = [as_of_adj_factor_path]
    total_rows = 0
    start = time.perf_counter()
    for partition_key in partition_keys:
        silver_path = _require_file(silver_stk_mins_path(lake_root, freq, partition_key))
        adj_path = _require_file(silver_adj_factor_path(lake_root, partition_key))
        baseline_path = scenario_dir / "baseline" / f"trade_date={partition_key}" / "part-000.parquet"
        replacement_path = scenario_dir / "replacement" / f"trade_date={partition_key}" / "part-000.parquet"
        target_path = scenario_dir / "rewritten" / f"trade_date={partition_key}" / "part-000.parquet"
        select_sql = build_daily_qfq_select_sql(
            silver_paths=[silver_path],
            trade_adj_factor_paths=[adj_path],
            as_of_adj_factor_paths=[as_of_adj_factor_path],
        )
        _copy_select_to_parquet(select_sql, baseline_path)
        _copy_select_to_parquet(
            f"""
            SELECT *
            FROM ({select_sql})
            WHERE ts_code = {duckdb_string(stock_code)}
            """,
            replacement_path,
        )
        total_rows += rewrite_qfq_partition_for_stock_code(
            existing_partition_path=baseline_path,
            replacement_rows_path=replacement_path,
            stock_code=stock_code,
            target_path=target_path,
        )
        input_paths.extend((silver_path, adj_path))
    elapsed = time.perf_counter() - start
    output_bytes = _directory_size(scenario_dir)
    return PerformanceMetric(
        scenario="repair_partition_rewrite",
        freq=freq,
        sample_days=sample_days,
        partition_count=len(partition_keys),
        row_count=total_rows,
        elapsed_seconds=elapsed,
        input_bytes=_sum_existing_file_sizes(input_paths),
        output_bytes=output_bytes,
        output_path=str(scenario_dir),
    )


def _time_copy_query(
    *,
    scenario: str,
    freq: int,
    sample_days: int | None,
    partition_count: int,
    select_sql: str,
    target_path: Path,
    input_paths: Sequence[Path],
) -> PerformanceMetric:
    start = time.perf_counter()
    _copy_select_to_parquet(select_sql, target_path)
    elapsed = time.perf_counter() - start
    return PerformanceMetric(
        scenario=scenario,
        freq=freq,
        sample_days=sample_days,
        partition_count=partition_count,
        row_count=_count_parquet_rows(target_path),
        elapsed_seconds=elapsed,
        input_bytes=_sum_existing_file_sizes(input_paths),
        output_bytes=target_path.stat().st_size,
        output_path=str(target_path),
    )


def _copy_select_to_parquet(select_sql: str, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = _temp_path_for(target_path)
    if temp_path.exists():
        temp_path.unlink()
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(copy_query_to_parquet(select_sql, temp_path))
    os.replace(temp_path, target_path)


def _count_parquet_rows(path: Path) -> int:
    with duckdb.connect(database=":memory:") as connection:
        return int(
            connection.execute(
                f"SELECT count(*) FROM {read_parquet(path, hive_partitioning=False)}"
            ).fetchone()[0]
        )


def _discover_silver_partition_keys(lake_root: Path, freq: int) -> tuple[str, ...]:
    normalized_freq = normalize_stk_mins_freq(freq)
    root = lake_root / "silver" / "quote" / "stk_mins" / f"freq={normalized_freq}"
    keys: list[str] = []
    for path in root.glob("trade_date=*/part-000.parquet"):
        keys.append(path.parent.name.removeprefix("trade_date="))
    return tuple(sorted(keys))


def _select_recent_partition_keys(
    partition_keys: Sequence[str],
    *,
    end_partition_key: str,
    limit: int,
) -> tuple[str, ...]:
    candidates = [key for key in sorted(partition_keys) if key <= end_partition_key]
    return tuple(candidates[-limit:])


def _require_file(path: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"Missing required qfq benchmark input: {path}")
    return path


def _write_report(output_dir: Path, report: dict[str, object]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / REPORT_JSON).write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    metrics = report.get("metrics", [])
    if not isinstance(metrics, list):
        raise TypeError("Report metrics must be a list.")
    fieldnames = (
        "scenario",
        "freq",
        "sample_days",
        "partition_count",
        "row_count",
        "elapsed_seconds",
        "input_bytes",
        "output_bytes",
        "output_path",
    )
    with (output_dir / REPORT_CSV).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for metric in metrics:
            if isinstance(metric, dict):
                writer.writerow({field: metric.get(field) for field in fieldnames})


def _sum_existing_file_sizes(paths: Sequence[Path]) -> int:
    unique_paths = {path for path in paths if path.exists()}
    return sum(path.stat().st_size for path in unique_paths)


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _temp_path_for(target_path: Path) -> Path:
    return target_path.with_suffix(target_path.suffix + ".tmp")


def _is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def _normalize_sample_days(sample_days: Sequence[int]) -> tuple[int, ...]:
    normalized = tuple(sorted({int(days) for days in sample_days}))
    if not normalized or any(days <= 0 for days in normalized):
        raise ValueError("repair sample days must be positive integers.")
    return normalized


def _parse_sample_days(value: str) -> tuple[int, ...]:
    return _normalize_sample_days(tuple(int(item.strip()) for item in value.split(",") if item.strip()))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark stk_mins qfq writeback performance.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("dry-run", "benchmark"):
        command = subparsers.add_parser(name)
        command.add_argument("--lake-root", required=True)
        command.add_argument("--output-dir", required=True)
        command.add_argument("--trade-date", required=True)
        command.add_argument("--stock-code", required=True)
        command.add_argument("--repair-sample-days", default="20,100")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
