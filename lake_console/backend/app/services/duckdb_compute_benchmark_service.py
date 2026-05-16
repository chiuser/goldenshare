from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from lake_console.backend.app.settings import LakeConsoleSettings


@dataclass(frozen=True)
class BenchmarkInputPaths:
    clean_paths: list[Path]
    adj_factor_paths: list[Path]
    latest_adj_factor_paths: list[Path]
    identity_map_path: Path


class DuckDbComputeBenchmarkService:
    """Read-only benchmark for the planned DuckDB large-compute shell."""

    def __init__(self, *, settings: LakeConsoleSettings) -> None:
        self.settings = settings
        self.lake_root = settings.lake_root

    def run_stk_mins_qfq_sample(self, *, sample_month: str, freqs: Iterable[int]) -> dict[str, Any]:
        selected_freqs = _normalize_freqs(freqs)
        month_start, month_end = _parse_month_range(sample_month)
        temp_dir = _resolve_lake_relative_path(self.lake_root, self.settings.duckdb_temp_directory)
        paths = self._collect_paths(month_start=month_start, month_end=month_end, freqs=selected_freqs)
        temp_dir.mkdir(parents=True, exist_ok=True)

        duckdb = _require_duckdb()
        connection = duckdb.connect(database=":memory:")
        try:
            connection.execute(f"PRAGMA threads={self.settings.duckdb_threads}")
            connection.execute(f"PRAGMA memory_limit='{self.settings.duckdb_memory_limit}'")
            connection.execute(f"SET temp_directory='{temp_dir}'")
            started = time.perf_counter()
            metrics = connection.execute(
                """
                with clean as (
                    select
                        ts_code,
                        cast(freq as integer) as freq,
                        cast(trade_time as timestamp) as trade_time,
                        cast(trade_date as date) as trade_date,
                        cast(open as double) as open,
                        cast(high as double) as high,
                        cast(low as double) as low,
                        cast(close as double) as close,
                        cast(vwap as double) as vwap,
                        cast(vol as bigint) as vol,
                        cast(amount as double) as amount
                    from read_parquet(?, hive_partitioning=1)
                ),
                day_factor as (
                    select
                        ts_code,
                        cast(trade_date as date) as trade_date,
                        cast(adj_factor as double) as adj_factor
                    from read_parquet(?, hive_partitioning=1)
                ),
                latest_factor as (
                    select
                        ts_code,
                        cast(adj_factor as double) as latest_adj_factor
                    from read_parquet(?, hive_partitioning=1)
                ),
                joined as (
                    select
                        clean.*,
                        day_factor.adj_factor,
                        latest_factor.latest_adj_factor,
                        clean.close * day_factor.adj_factor / latest_factor.latest_adj_factor as qfq_close
                    from clean
                    left join day_factor
                      on clean.ts_code = day_factor.ts_code
                     and clean.trade_date = day_factor.trade_date
                    left join latest_factor
                      on clean.ts_code = latest_factor.ts_code
                )
                select
                    count(*) as row_count,
                    count(distinct ts_code) as security_count,
                    min(trade_time) as min_trade_time,
                    max(trade_time) as max_trade_time,
                    sum(case when adj_factor is null then 1 else 0 end) as missing_adj_factor_rows,
                    sum(case when latest_adj_factor is null then 1 else 0 end) as missing_latest_adj_factor_rows,
                    sum(
                        case
                            when adj_factor is not null
                             and latest_adj_factor is not null
                             and (adj_factor <= 0 or latest_adj_factor <= 0)
                            then 1
                            else 0
                        end
                    ) as non_positive_factor_rows,
                    sum(case when qfq_close is null then 0 else qfq_close end) as qfq_close_checksum
                from joined
                """,
                [
                    [str(path) for path in paths.clean_paths],
                    [str(path) for path in paths.adj_factor_paths],
                    [str(path) for path in paths.latest_adj_factor_paths],
                ],
            ).fetchone()
            elapsed_seconds = time.perf_counter() - started
            identity_metrics = connection.execute(
                """
                select
                    count(*) as identity_row_count,
                    count(distinct latest_ts_code) as identity_count,
                    count(distinct source_ts_code) as source_code_count
                from read_parquet(?)
                """,
                [str(paths.identity_map_path)],
            ).fetchone()
        finally:
            connection.close()

        row_count = int(metrics[0] or 0)
        return {
            "benchmark": "stk_mins_qfq_sample",
            "sample_month": sample_month,
            "freqs": selected_freqs,
            "config": {
                "duckdb_threads": self.settings.duckdb_threads,
                "duckdb_memory_limit": self.settings.duckdb_memory_limit,
                "duckdb_temp_directory": str(temp_dir),
                "compute_bucket_count": self.settings.compute_bucket_count,
                "compute_max_active_writers": self.settings.compute_max_active_writers,
                "compute_progress_interval_seconds": self.settings.compute_progress_interval_seconds,
                "compute_stale_heartbeat_seconds": self.settings.compute_stale_heartbeat_seconds,
                "compute_max_unit_retries": self.settings.compute_max_unit_retries,
            },
            "inputs": {
                "clean_file_count": len(paths.clean_paths),
                "clean_total_bytes": _total_size(paths.clean_paths),
                "adj_factor_file_count": len(paths.adj_factor_paths),
                "adj_factor_total_bytes": _total_size(paths.adj_factor_paths),
                "latest_adj_factor_file_count": len(paths.latest_adj_factor_paths),
                "identity_map_path": str(paths.identity_map_path),
            },
            "metrics": {
                "elapsed_seconds": round(elapsed_seconds, 3),
                "rows_per_second": round(row_count / elapsed_seconds, 2) if elapsed_seconds > 0 else row_count,
                "row_count": row_count,
                "security_count": int(metrics[1] or 0),
                "min_trade_time": metrics[2],
                "max_trade_time": metrics[3],
                "missing_adj_factor_rows": int(metrics[4] or 0),
                "missing_latest_adj_factor_rows": int(metrics[5] or 0),
                "non_positive_factor_rows": int(metrics[6] or 0),
                "qfq_close_checksum": float(metrics[7] or 0),
                "identity_row_count": int(identity_metrics[0] or 0),
                "identity_count": int(identity_metrics[1] or 0),
                "identity_source_code_count": int(identity_metrics[2] or 0),
            },
        }

    def _collect_paths(self, *, month_start: date, month_end: date, freqs: list[int]) -> BenchmarkInputPaths:
        clean_paths: list[Path] = []
        adj_paths: list[Path] = []
        for current_freq in freqs:
            freq_root = self.lake_root / "research" / "stk_mins_by_date_clean_next" / f"freq={current_freq}"
            clean_paths.extend(_partition_files_in_date_range(freq_root, "trade_date", month_start, month_end))
        adj_root = self.lake_root / "raw_tushare" / "adj_factor"
        adj_paths.extend(_partition_files_in_date_range(adj_root, "trade_date", month_start, month_end))
        latest_adj_paths = _latest_partition_files(adj_root, "trade_date")
        identity_map = self.lake_root / "manifest" / "security_identity" / "security_identity_map.parquet"
        missing = []
        if not clean_paths:
            missing.append(f"clean_next sample month {month_start:%Y-%m}")
        if not adj_paths:
            missing.append(f"adj_factor sample month {month_start:%Y-%m}")
        if not latest_adj_paths:
            missing.append("adj_factor latest partition")
        if not identity_map.exists():
            missing.append(str(identity_map))
        if missing:
            raise RuntimeError(f"DuckDB benchmark 缺少输入：{', '.join(missing)}")
        return BenchmarkInputPaths(
            clean_paths=sorted(clean_paths),
            adj_factor_paths=sorted(adj_paths),
            latest_adj_factor_paths=sorted(latest_adj_paths),
            identity_map_path=identity_map,
        )


def _normalize_freqs(freqs: Iterable[int]) -> list[int]:
    values = list(dict.fromkeys(int(item) for item in freqs))
    allowed = {1, 5, 15, 30, 60}
    invalid = sorted(set(values) - allowed)
    if invalid:
        raise ValueError(f"不支持的 freqs={invalid}，允许值：1,5,15,30,60")
    if not values:
        raise ValueError("freqs 不能为空。")
    return values


def _parse_month_range(sample_month: str) -> tuple[date, date]:
    if len(sample_month) != 7 or sample_month[4] != "-":
        raise ValueError(f"sample_month 必须是 YYYY-MM：{sample_month}")
    year = int(sample_month[:4])
    month = int(sample_month[5:7])
    start = date(year, month, 1)
    if month == 12:
        end = date(year, 12, 31)
    else:
        end = date(year, month + 1, 1).replace(day=1)
        end = date.fromordinal(end.toordinal() - 1)
    return start, end


def _partition_files_in_date_range(root: Path, partition_key: str, start: date, end: date) -> list[Path]:
    if not root.exists():
        return []
    files: list[Path] = []
    prefix = f"{partition_key}="
    for partition in root.glob(f"{prefix}*"):
        if not partition.is_dir() or not partition.name.startswith(prefix):
            continue
        try:
            partition_date = date.fromisoformat(partition.name.removeprefix(prefix))
        except ValueError:
            continue
        if start <= partition_date <= end:
            files.extend(path for path in partition.glob("*.parquet") if path.is_file())
    return files


def _latest_partition_files(root: Path, partition_key: str) -> list[Path]:
    if not root.exists():
        return []
    prefix = f"{partition_key}="
    latest: tuple[date, Path] | None = None
    for partition in root.glob(f"{prefix}*"):
        if not partition.is_dir() or not partition.name.startswith(prefix):
            continue
        try:
            partition_date = date.fromisoformat(partition.name.removeprefix(prefix))
        except ValueError:
            continue
        if latest is None or partition_date > latest[0]:
            latest = (partition_date, partition)
    if latest is None:
        return []
    return sorted(path for path in latest[1].glob("*.parquet") if path.is_file())


def _resolve_lake_relative_path(lake_root: Path, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        resolved = path.resolve()
    else:
        resolved = (lake_root / path).resolve()
    lake_root_resolved = lake_root.resolve()
    if resolved != lake_root_resolved and lake_root_resolved not in resolved.parents:
        raise ValueError(f"DuckDB temp 目录必须位于 Lake Root 下：{resolved}")
    return resolved


def _total_size(paths: Iterable[Path]) -> int:
    return sum(path.stat().st_size for path in paths if path.exists())


def _require_duckdb():  # type: ignore[no-untyped-def]
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("缺少 duckdb 依赖，请先安装 lake_console/backend/requirements.txt。") from exc
    return duckdb
