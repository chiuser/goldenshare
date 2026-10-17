"""Bounded contracts and durable records for an explicit historical factor repair.

This module never imports an instance, creates definitions or writes formal Lake.
The immutable plan and per-file records belong to this execution only.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import tempfile
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import cache
from pathlib import Path
from typing import Any

from orchestrator.defs.duckdb_connection import DuckDBConnectionSettings
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT

# Approved objects and exact input ranges; never an automatic stock pool.
APPROVED_FACTOR_RANGES = (
    ("000430.SZ", "2025-12-29", "2026-07-03", 122),
    ("000615.SZ", "2025-12-29", "2026-07-03", 122),
    ("000691.SZ", "2026-01-05", "2026-07-03", 119),
    ("000697.SZ", "2025-11-27", "2026-09-22", 201),
    ("000793.SZ", "2026-06-22", "2026-07-03", 10),
    ("000908.SZ", "2026-03-11", "2026-07-03", 78),
    ("001331.SZ", "2026-06-26", "2026-06-29", 2),
    ("002012.SZ", "2026-07-06", "2026-09-22", 57),
    ("002117.SZ", "2024-06-25", "2024-11-14", 96),
    ("002200.SZ", "2025-12-12", "2026-07-03", 133),
    ("002713.SZ", "2025-12-30", "2026-09-22", 178),
    ("002742.SZ", "2025-12-10", "2026-07-03", 135),
    ("002822.SZ", "2025-12-30", "2026-07-03", 121),
    ("300091.SZ", "2026-02-12", "2026-09-22", 148),
    ("300093.SZ", "2025-11-20", "2026-07-03", 149),
    ("300125.SZ", "2025-12-29", "2026-07-03", 122),
    ("300159.SZ", "2025-12-24", "2026-07-03", 125),
    ("300176.SZ", "2026-08-21", "2026-09-07", 12),
    ("300506.SZ", "2025-12-22", "2026-07-03", 127),
    ("600016.SH", "2023-06-01", "2023-06-21", 15),
    ("600165.SH", "2025-12-10", "2026-07-03", 135),
    ("600717.SH", "2026-06-23", "2026-07-03", 9),
    ("603221.SH", "2026-08-18", "2026-09-22", 26),
    ("688109.SH", "2025-09-25", "2026-09-22", 240),
    ("688689.SH", "2026-06-29", "2026-07-07", 7),
)
FACTOR_SOURCE_COLUMNS = ("ts_code", "trade_date", "adj_factor")
REPAIR_PLAN_MAX_BYTES = 192 * 1024**2


class FactorRepairError(RuntimeError):
    """A stable reason code; never include tokens or unbounded source payloads."""


@dataclass(frozen=True)
class RepairBudget:
    memory_limit: str = "2GiB"
    max_rss: int = 4 * 1024**3
    threads: int = 2
    max_spill: int = 2 * 1024**3
    max_candidate_bytes: int = 10 * 1024**3
    max_stock_batch_rows: int = 100_000
    progress_interval: int = 30

    def connection_settings(self, temporary_directory: Path) -> DuckDBConnectionSettings:
        return DuckDBConnectionSettings(
            temp_directory=temporary_directory,
            memory_limit=self.memory_limit,
            threads=self.threads,
            max_temp_directory_size=f"{self.max_spill}B",
        )


@dataclass(frozen=True)
class FactorRepairScope:
    ts_code: str
    factor_ranges: tuple[tuple[str, str], ...]
    as_of_trade_date: str
    repair_end_trade_date: str
    daily_basis_start_trade_date: str | None = None

    def __post_init__(self):
        expected = next((r for r in APPROVED_FACTOR_RANGES if r[0] == self.ts_code), None)
        if expected is None or self.factor_ranges != ((expected[1], expected[2]),):
            raise FactorRepairError("factor_scope_not_approved")
        for value in (self.as_of_trade_date, self.repair_end_trade_date):
            if date.fromisoformat(value).isoformat() != value:
                raise FactorRepairError("factor_scope_date_invalid")
        if not expected[2] <= self.as_of_trade_date <= self.repair_end_trade_date:
            raise FactorRepairError("factor_scope_anchor_invalid")
        if self.daily_basis_start_trade_date is not None and (
            self.ts_code != "688689.SH"
            or self.daily_basis_start_trade_date != "2021-01-27"
        ):
            raise FactorRepairError("daily_basis_scope_not_approved")

    @property
    def expected_factor_rows(self) -> int:
        return next(r[3] for r in APPROVED_FACTOR_RANGES if r[0] == self.ts_code)


@dataclass(frozen=True)
class FileIdentity:
    path: str
    size: int
    mtime_ns: int
    sha256: str


def repair_hash(value: Any) -> str:
    digest = hashlib.sha256()
    for chunk in json.JSONEncoder(sort_keys=True,separators=(",",":"),allow_nan=False).iterencode(value):
        digest.update(chunk.encode())
    return digest.hexdigest()


def check_repair_cancel(cancel=None) -> None:
    if cancel is not None and cancel():
        raise FactorRepairError("canceled")


def check_repair_path(path: Path) -> Path:
    """Reject links before resolving, including ancestors and non-existing leaves."""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise FactorRepairError("repair_path_invalid")
    for part in (*reversed(path.parents), path):
        if (part.exists() or part.is_symlink()) and stat.S_ISLNK(part.lstat().st_mode):
            raise FactorRepairError("repair_path_symlink")
    return path


def check_repair_roots(lake_root: Path, run_root: Path) -> None:
    check_repair_path(lake_root)
    check_repair_path(run_root)
    if lake_root != Path(DEFAULT_LAKE_ROOT) or (
        run_root.parent != Path(DEFAULT_LAKE_STAGING_ROOT) / "stock_adj_factor_history_repair"
        or not run_root.name.startswith("run_id=")
    ):
        raise FactorRepairError("repair_root_not_approved")


def file_identity(path: Path, *, cancel=None, progress=None) -> FileIdentity:
    path = check_repair_path(path)
    before = path.stat()
    digest = hashlib.sha256()
    read_bytes = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            check_repair_cancel(cancel)
            digest.update(chunk)
            read_bytes += len(chunk)
            if progress:
                progress(read_bytes, before.st_size)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise FactorRepairError("input_drift")
    return FileIdentity(str(path), after.st_size, after.st_mtime_ns, digest.hexdigest())


def atomic_repair_json(path: Path, payload: Any) -> None:
    check_repair_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    with os.fdopen(fd, "w") as stream:
        json.dump(payload, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    sync_repair_directory(path.parent)


def sync_repair_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def normalized_factor_rows(scope: FactorRepairScope, rows) -> tuple[dict, ...]:
    normalized, keys = [], set()
    start, end = scope.factor_ranges[0]
    for row in rows:
        if set(row) != set(FACTOR_SOURCE_COLUMNS) or row["ts_code"] != scope.ts_code:
            raise FactorRepairError("factor_source_scope_invalid")
        value = row["trade_date"]
        if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
            raise FactorRepairError("factor_source_date_invalid")
        try:
            day = date.fromisoformat(f"{value[:4]}-{value[4:6]}-{value[6:8]}").isoformat()
            factor = Decimal(str(row["adj_factor"]))
        except (ValueError, InvalidOperation) as error:
            raise FactorRepairError("factor_source_value_invalid") from error
        if not start <= day <= end or day in keys:
            raise FactorRepairError("factor_source_keys_invalid")
        if not factor.is_finite() or factor <= 0 or not math.isfinite(float(factor)):
            raise FactorRepairError("factor_source_value_invalid")
        keys.add(day)
        normalized.append({"ts_code": scope.ts_code, "trade_date": value, "adj_factor": str(factor.normalize())})
    if len(normalized) != scope.expected_factor_rows:
        raise FactorRepairError("factor_source_count_changed")
    return tuple(sorted(normalized, key=lambda r: r["trade_date"]))


def fetch_current_factor_rows(scope: FactorRepairScope, tushare, *, cancel=None) -> tuple[dict, ...]:
    """Bounded source-only facts; source errors propagate, no hidden retry."""
    start, end = scope.factor_ranges[0]
    rows = []
    for offset in (0, 6000):
        check_repair_cancel(cancel)
        result = tushare.call(
            "adj_factor",
            {"ts_code": scope.ts_code, "start_date": start.replace("-", ""),
             "end_date": end.replace("-", ""), "limit": 6000, "offset": offset},
            FACTOR_SOURCE_COLUMNS,
        )
        check_repair_cancel(cancel)
        if tuple(result.columns) != FACTOR_SOURCE_COLUMNS:
            raise FactorRepairError("factor_source_columns_invalid")
        if len(result.rows) > 6000:
            raise FactorRepairError("factor_source_page_invalid")
        rows.extend(result.rows)
        if len(result.rows) < 6000:
            return normalized_factor_rows(scope, rows)
    raise FactorRepairError("factor_source_page_budget_exceeded")


def inspect_factor_rows(connection, lake_root: Path, scopes, source_rows) -> dict:
    """Read only bounded factor keys; no candidate, run directory or checkpoint."""
    from orchestrator.defs.duckdb_sql import adj_factor_current_listed_stock_select
    from orchestrator.defs.paths import (
        raw_adj_factor_path,
        silver_adj_factor_path,
        silver_stock_lifecycle_path,
    )

    expected_codes = {scope.ts_code for scope in scopes}
    if {row["ts_code"] for row in source_rows} != expected_codes:
        raise FactorRepairError("factor_source_scope_invalid")
    for scope in scopes:
        normalized_factor_rows(scope, [r for r in source_rows if r["ts_code"] == scope.ts_code])
    create_factor_source_relation(connection, source_rows)
    days = sorted({f"{r['trade_date'][:4]}-{r['trade_date'][4:6]}-{r['trade_date'][6:]}" for r in source_rows})
    raw = [raw_adj_factor_path(lake_root, day) for day in days]
    silver = [silver_adj_factor_path(lake_root, day) for day in days]
    for path in raw + silver:
        check_repair_path(path)
        if not path.is_file():
            raise FactorRepairError("factor_input_missing")
    connection.execute("""CREATE OR REPLACE TEMP TABLE repair_factor_raw AS
      SELECT r.ts_code,r.trade_date,r.adj_factor::DOUBLE adj_factor
      FROM read_parquet(?,hive_partitioning=false) r
      JOIN repair_source s USING(ts_code,trade_date)""", [[str(p) for p in raw]])
    connection.execute("""CREATE OR REPLACE TEMP TABLE repair_factor_silver AS
      SELECT r.ts_code,strftime(r.trade_date,'%Y%m%d') trade_date,r.adj_factor::DOUBLE adj_factor
      FROM read_parquet(?,hive_partitioning=false) r
      JOIN repair_source s ON r.ts_code=s.ts_code AND strftime(r.trade_date,'%Y%m%d')=s.trade_date""",
                       [[str(p) for p in silver]])
    for relation in ("repair_source", "repair_factor_raw", "repair_factor_silver"):
        n, unique_keys = connection.execute(f"SELECT count(*),count(DISTINCT (ts_code,trade_date)) FROM {relation}").fetchone()
        if n != len(source_rows) or n != unique_keys:
            raise FactorRepairError("factor_existing_keys_invalid")
    mismatch, precision_only, changed = connection.execute("""
      SELECT count(*) FILTER(WHERE r.adj_factor<>v.adj_factor),
             count(*) FILTER(WHERE r.adj_factor<>s.adj_factor AND round(r.adj_factor,3)=s.adj_factor),
             count(*) FILTER(WHERE r.adj_factor<>s.adj_factor)
      FROM repair_source s JOIN repair_factor_raw r USING(ts_code,trade_date)
      JOIN repair_factor_silver v USING(ts_code,trade_date)
    """).fetchone()
    if mismatch or precision_only:
        raise FactorRepairError("factor_existing_values_changed")
    life = adj_factor_current_listed_stock_select(silver_stock_lifecycle_path(lake_root))
    invalid = connection.execute(f"""WITH life AS ({life})
      SELECT count(*) FROM repair_source s LEFT JOIN life l USING(ts_code)
      WHERE l.ts_code IS NULL OR strptime(s.trade_date,'%Y%m%d')::DATE<l.list_date
        OR (l.delist_date IS NOT NULL AND strptime(s.trade_date,'%Y%m%d')::DATE>=l.delist_date)
    """).fetchone()[0]
    if invalid:
        raise FactorRepairError("factor_lifecycle_conflict")
    return {"source_rows": len(source_rows), "changed_factor_keys": int(changed),
            "factor_days": days, "factor_files": [str(p) for p in raw + silver],
            "lifecycle_conflicts": 0}


def create_factor_source_relation(connection, rows) -> None:
    """The source payload is at most 2,489 records; Parquet writes remain columnar."""
    connection.execute("""CREATE OR REPLACE TEMP TABLE repair_source AS
      SELECT unnest(?::VARCHAR[]) ts_code,unnest(?::VARCHAR[]) trade_date,
             unnest(?::DOUBLE[]) adj_factor""",
                       [[r["ts_code"] for r in rows], [r["trade_date"] for r in rows],
                        [float(r["adj_factor"]) for r in rows]])


def write_candidate_record(run_root: Path, record: dict) -> Path:
    """One durable record per target; never rewrite a growing path list."""
    relative = record["target_relative_path"]
    target_id = hashlib.sha256(relative.encode()).hexdigest()
    path = run_root / "checkpoints/candidates" / f"{target_id}.json"
    atomic_repair_json(path, {"format_version": 1, **record})
    return path


def validate_repair_plan(plan: dict, expected_hash: str) -> None:
    body = {k: v for k, v in plan.items() if k != "plan_hash"}
    if (plan.get("kind") != "stock_adj_factor_history_repair"
        or plan.get("version") != 1 or plan.get("plan_hash") != expected_hash
        or repair_hash(body) != expected_hash
        or plan.get("budget") != asdict(RepairBudget())):
        raise FactorRepairError("repair_plan_invalid")
    scopes = [FactorRepairScope(**{**s, "factor_ranges": tuple(tuple(r) for r in s["factor_ranges"])})
              for s in plan["scopes"]]
    if {s.ts_code for s in scopes} != {r[0] for r in APPROVED_FACTOR_RANGES} or len(scopes) != 25:
        raise FactorRepairError("factor_scope_not_approved")
    if next(s for s in scopes if s.ts_code == "688689.SH").daily_basis_start_trade_date != "2021-01-27":
        raise FactorRepairError("daily_basis_scope_not_approved")
    required = {"source_rows", "source_hash", "anchors", "endpoints", "source_fingerprints",
                "target_preimages", "implementation_fingerprints", "units", "lake_root", "run_root"}
    if required - set(plan) or any(not plan[k] for k in required):
        raise FactorRepairError("repair_plan_incomplete")
    check_repair_roots(Path(plan["lake_root"]), Path(plan["run_root"]))
    if repair_hash(plan["source_rows"]) != plan["source_hash"]:
        raise FactorRepairError("repair_source_hash_invalid")
    for scope in scopes:
        normalized_factor_rows(scope, [r for r in plan["source_rows"] if r["ts_code"] == scope.ts_code])
    if len(plan["source_rows"]) != 2489 or len(plan["anchors"]) != 25:
        raise FactorRepairError("repair_plan_source_incomplete")
    endpoints = tuple(AssetRepairEndpoint(**{k: tuple(v) if k in ("expected_dates", "context_times") else v
        for k, v in e.items()}) for e in plan["endpoints"])
    validate_asset_repair_endpoints(scopes, endpoints)
    if {u["asset_key"] for u in plan["units"]} != set(approved_repair_asset_keys()):
        raise FactorRepairError("repair_unit_assets_incomplete")
    validate_price_repair_units(plan)
    validate_indicator_repair_units(plan)
    for unit in plan["units"]:
        validate_repair_target_paths(Path(plan["lake_root"]), unit["asset_key"], unit["target_paths"])


@dataclass(frozen=True)
class AssetRepairEndpoint:
    """Existing coverage for one approved stock/asset, never a default end date."""

    asset_key: str
    ts_code: str
    freq: int | None
    calculation_start_date: str
    end_time: str
    expected_dates: tuple[str, ...]
    calculation_rows: int
    previous_expected_date: str | None = None
    seed_last_trade_time: str | None = None
    context_times: tuple[str, ...] = ()


def approved_repair_asset_keys() -> tuple[str, ...]:
    """The repair scope, checked against the current catalog, not a new registry."""
    from orchestrator.defs.catalog.lake_assets import LAKE_ASSET_CATALOG

    keys = (
        "raw_tushare_adj_factor", "silver_adj_factor", "gold_stock_daily_qfq",
        "gold_stock_daily_trend_channel", "gold_stock_daily_trend_channel_state",
        "gold_stock_daily_qfq_nineturn",
        *(f"gold_stk_mins_qfq_{f}m" for f in (1, 5, 15, 30, 60, 90, 120)),
        *(f"gold_stk_mins_qfq_macd_kdj_{f}m" for f in (1, 5, 15, 30, 60, 90, 120)),
        *(f"gold_stk_mins_qfq_macd_kdj_state_{f}m" for f in (1, 5, 15, 30, 60, 90, 120)),
        *(f"gold_stk_mins_qfq_nineturn_{f}m" for f in (30, 60, 90, 120)),
    )
    catalog = {entry.asset_key for entry in LAKE_ASSET_CATALOG}
    if len(keys) != 31 or set(keys) - catalog:
        raise FactorRepairError("repair_asset_catalog_drift")
    return keys


def validate_asset_repair_endpoints(scopes, endpoints) -> None:
    """Require separate tails; exact expected seeds cannot be substituted."""
    from datetime import datetime

    scope_by_code = {s.ts_code: s for s in scopes}
    assets = set(approved_repair_asset_keys()) - {"raw_tushare_adj_factor", "silver_adj_factor"}
    expected = {(asset, code) for asset in assets for code in scope_by_code}
    observed = {(e.asset_key, e.ts_code) for e in endpoints}
    if observed != expected or len(endpoints) != len(expected):
        raise FactorRepairError("repair_endpoints_incomplete")
    for e in endpoints:
        scope = scope_by_code[e.ts_code]
        try:
            end = datetime.fromisoformat(e.end_time)
            start = date.fromisoformat(e.calculation_start_date)
            dates = tuple(date.fromisoformat(d).isoformat() for d in e.expected_dates)
        except (TypeError, ValueError) as error:
            raise FactorRepairError("repair_endpoint_date_invalid") from error
        if (not dates or tuple(sorted(set(dates))) != dates or dates[0] != start.isoformat()
                or dates[-1] != end.date().isoformat()
                or end.tzinfo is not None or dates[-1] > scope.repair_end_trade_date
                or e.calculation_rows < 0):
            raise FactorRepairError("repair_endpoint_range_invalid")
        freq = next((f for f in (1, 5, 15, 30, 60, 90, 120)
                     if e.asset_key.endswith(f"_{f}m")), None)
        if e.freq != freq:
            raise FactorRepairError("repair_endpoint_frequency_invalid")
        if e.asset_key.startswith("gold_stock_daily") and scope.daily_basis_start_trade_date:
            if dates[0] != scope.daily_basis_start_trade_date:
                raise FactorRepairError("daily_basis_endpoint_invalid")
        elif dates[0] < scope.factor_ranges[0][0]:
            raise FactorRepairError("repair_endpoint_start_not_approved")
        if e.asset_key.startswith("gold_stk_mins_qfq_macd_kdj") and (
                    not e.previous_expected_date or e.previous_expected_date >= dates[0]
                    or not e.seed_last_trade_time or len(e.context_times) != 8
                    or tuple(sorted(set(e.context_times))) != e.context_times
                    or e.context_times[-1] != e.seed_last_trade_time
                    or e.seed_last_trade_time[:10] > e.previous_expected_date
                    or e.context_times[-1][:10] >= dates[0]):
            raise FactorRepairError("repair_seed_context_invalid")
    by_key = {(e.asset_key, e.ts_code): e for e in endpoints}
    for e in endpoints:
        if e.asset_key.startswith("gold_stk_mins_qfq_macd_kdj"):
            price = by_key[(f"gold_stk_mins_qfq_{e.freq}m", e.ts_code)]
            if "_state_" not in e.asset_key and e.end_time > price.end_time:
                raise FactorRepairError("repair_state_price_coverage_missing")


def plan_repair_calculation_windows(trade_date_rows, *, max_rows=None) -> tuple[tuple[str, ...], ...]:
    """Split only on whole-day boundaries; counts are SQL aggregates, not bars."""
    limit = RepairBudget().max_stock_batch_rows if max_rows is None else max_rows
    if type(limit) is not int or not 1 <= limit <= RepairBudget().max_stock_batch_rows:
        raise FactorRepairError("repair_row_budget_invalid")
    previous, total, current, windows = None, 0, [], []
    for day, count in trade_date_rows:
        if (date.fromisoformat(day).isoformat() != day or (previous is not None and day <= previous)
                or type(count) is not int or count < 0):
            raise FactorRepairError("repair_window_counts_invalid")
        if count > limit:
            raise FactorRepairError("repair_single_day_budget_exceeded")
        if current and (total + count > limit or current[-1][:4] != day[:4]):
            windows.append(tuple(current))
            total, current = 0, []
        current.append(day)
        total += count
        previous = day
    if current:
        windows.append(tuple(current))
    return tuple(windows)


def inspect_repair_asset_rows(connection, *, paths, scopes, asset_key: str,
                              expected_dates, starts, freq=None) -> dict:
    """Bounded 64-file aggregate audit, including date gaps and duplicates.

    This intentionally does not perform or advertise an ordinary asset check.
    Whole-file retained rows and business validation belong to candidate audit.
    """
    if asset_key not in approved_repair_asset_keys()[2:]:
        raise FactorRepairError("repair_asset_not_approved")
    codes = [s.ts_code for s in scopes]
    if not codes or len(set(codes)) != len(codes) or set(starts) != set(codes):
        raise FactorRepairError("repair_asset_scope_invalid")
    if tuple(sorted(set(expected_dates))) != tuple(expected_dates):
        raise FactorRepairError("repair_expected_dates_invalid")
    by_code = {code: {} for code in codes}
    inputs = []
    minute = asset_key.startswith("gold_stk_mins_qfq_") and "state" not in asset_key
    time_field = "trade_time" if minute else "trade_date"
    key = "(ts_code,trade_time)" if minute else "(ts_code,trade_date)"
    for offset in range(0, len(paths), 64):
        batch = tuple(paths[offset:offset + 64])
        before = []
        for path in batch:
            p = check_repair_path(Path(path))
            st = p.stat()
            before.append((str(p), st.st_size, st.st_mtime_ns))
        rows = connection.execute(f"""
          SELECT ts_code,CAST(trade_date AS VARCHAR),CAST(min({time_field}) AS VARCHAR),
                 CAST(max({time_field}) AS VARCHAR),count(*),count(DISTINCT {key})
          FROM read_parquet(?,hive_partitioning=false)
          WHERE ts_code=ANY(?) AND CAST(trade_date AS VARCHAR)=ANY(?)
          GROUP BY ts_code,trade_date ORDER BY ts_code,trade_date
        """, [[p[0] for p in before], codes, list(expected_dates)]).fetchall() if batch else []
        for code, day, first, last, count, unique in rows:
            if count != unique or day in by_code[code]:
                raise FactorRepairError("repair_asset_duplicate_key")
            by_code[code][day] = (first, last, int(count))
        for p, size, mtime in before:
            st = Path(p).stat()
            if (size, mtime) != (st.st_size, st.st_mtime_ns):
                raise FactorRepairError("input_drift")
        inputs.extend(before)
    profiles = []
    for code in codes:
        observed = by_code[code]
        dates = tuple(d for d in expected_dates if d >= starts[code])
        if not observed:
            raise FactorRepairError("repair_asset_stock_missing")
        end = max(observed)
        dates = tuple(d for d in dates if d <= end)
        actual = tuple(d for d in dates if d in observed)
        # Daily state must carry suspended dates; bars/results may omit them.
        is_state = "_state" in asset_key
        if is_state and actual != dates:
            raise FactorRepairError("repair_state_expected_date_missing")
        if not actual:
            raise FactorRepairError("repair_asset_window_empty")
        counts = tuple((d, observed[d][2] if d in observed else 0) for d in dates)
        profiles.append({"asset_key": asset_key, "ts_code": code, "freq": freq,
                         "calculation_start_date": dates[0], "end_time": observed[end][1],
                         "expected_dates": dates, "observed_dates": actual,
                         "calculation_rows": sum(n for _, n in counts),
                         "maximum_day_rows": max(n for _, n in counts),
                         "previous_actual_date": max((d for d in observed if d < dates[0]), default=None),
                         "trade_date_rows": counts,
                         "calculation_windows": plan_repair_calculation_windows(counts)})
    return {"profiles": profiles, "inputs": inputs}


def validate_repair_target_paths(lake_root: Path, asset_key: str, target_paths) -> None:
    """Bind targets to the existing asset catalog; raw/other gold cannot be substituted."""
    from orchestrator.defs.catalog.lake_assets import LAKE_ASSET_CATALOG

    entry = next((e for e in LAKE_ASSET_CATALOG if e.asset_key == asset_key), None)
    if entry is None or not entry.path_template or not entry.path_template.startswith("data_lake/"):
        raise FactorRepairError("repair_asset_path_contract_missing")
    pattern = re.escape(entry.path_template.removeprefix("data_lake/"))
    for token, expression in (("partition_key", r"\d{4}-\d{2}-\d{2}"),
                              ("ts_code", r"\d{6}\.(?:SZ|SH|BJ)"), ("year", r"\d{4}")):
        pattern = pattern.replace(re.escape("{" + token + "}"), expression)
    for target in target_paths:
        path = check_repair_path(Path(target))
        if not path.is_relative_to(lake_root) or not re.fullmatch(pattern, path.relative_to(lake_root).as_posix()):
            raise FactorRepairError("repair_target_asset_path_mismatch")


def freeze_stock_factor_repair(*, lake_root: Path, run_root: Path, scopes,
                               source_rows, anchors, endpoints, input_stats,
                               target_paths, units, writer_guard, partition_validation, cancel=None, progress=None) -> dict:
    """Freeze only a complete, idle, unchanged plan; never touch formal data.

    writer_guard is a required runtime read-only assertion supplied by the
    execution adapter. Passing a human confirmation alone is insufficient.
    """
    import shutil
    import uuid

    check_repair_roots(lake_root, run_root)
    try:
        run_id = str(uuid.UUID(run_root.name.removeprefix("run_id=")))
    except ValueError as error:
        raise FactorRepairError("repair_run_id_invalid") from error
    if not callable(writer_guard):
        raise FactorRepairError("repair_writer_guard_required")
    if run_root.exists():
        raise FactorRepairError("repair_freeze_target_conflict")
    if len(scopes) != 25 or {s.ts_code for s in scopes} != {r[0] for r in APPROVED_FACTOR_RANGES}:
        raise FactorRepairError("factor_scope_not_approved")
    if next(s for s in scopes if s.ts_code == "688689.SH").daily_basis_start_trade_date != "2021-01-27":
        raise FactorRepairError("daily_basis_scope_not_approved")
    validate_asset_repair_endpoints(scopes, endpoints)
    source = tuple(r for s in scopes for r in normalized_factor_rows(
        s, [r for r in source_rows if r["ts_code"] == s.ts_code]))
    if len(source) != len(source_rows):
        raise FactorRepairError("factor_source_scope_invalid")
    if {a["ts_code"] for a in anchors} != {s.ts_code for s in scopes} or len(anchors) != 25:
        raise FactorRepairError("repair_anchors_incomplete")
    for anchor in anchors:
        scope = next(s for s in scopes if s.ts_code == anchor["ts_code"])
        value = Decimal(str(anchor["adj_factor"]))
        if (anchor["trade_date"] != scope.as_of_trade_date or not value.is_finite() or value <= 0
                or not math.isfinite(float(value))):
            raise FactorRepairError("repair_anchor_invalid")
    expected_targets = {str(check_repair_path(Path(p))) for p in target_paths}
    if not expected_targets or not units or any(not Path(p).is_relative_to(lake_root) for p in expected_targets):
        raise FactorRepairError("repair_target_inventory_invalid")
    stats = {str(Path(p)): (size, mtime) for p, size, mtime in input_stats}
    if len(stats) != len(input_stats) or expected_targets - set(stats):
        raise FactorRepairError("repair_input_inventory_incomplete")
    for unit in units:
        validate_repair_target_paths(lake_root, unit["asset_key"], unit["target_paths"])
        if (unit["asset_key"] not in approved_repair_asset_keys()
                or not set(unit["target_paths"]) <= expected_targets
                or not set(unit["stock_codes"]) <= {s.ts_code for s in scopes}
                or not unit["stock_codes"]):
            raise FactorRepairError("repair_unit_scope_invalid")
    if {p for u in units for p in u["target_paths"]} != expected_targets:
        raise FactorRepairError("repair_unit_inventory_incomplete")
    if {u["asset_key"] for u in units} != set(approved_repair_asset_keys()):
        raise FactorRepairError("repair_unit_assets_incomplete")
    writer_guard()
    identities = []
    for number, (path, observed) in enumerate(sorted(stats.items()), 1):
        check_repair_cancel(cancel)
        identity = file_identity(Path(path), cancel=cancel)
        if (identity.size, identity.mtime_ns) != observed:
            raise FactorRepairError("input_drift")
        identities.append(asdict(identity))
        if progress:
            progress(number, len(stats))
    staging = Path(DEFAULT_LAKE_STAGING_ROOT)
    if lake_root.stat().st_dev != staging.stat().st_dev:
        raise FactorRepairError("repair_filesystem_mismatch")
    target_bytes = sum(stats[p][0] for p in expected_targets)
    budget = RepairBudget()
    # Conservative existing full-file volume; actual candidates retain their own cap.
    if target_bytes > budget.max_candidate_bytes:
        raise FactorRepairError("repair_candidate_estimate_exceeded")
    required = (target_bytes + sum(s for s, _ in stats.values()) + budget.max_spill) * 6 // 5
    if shutil.disk_usage(staging).free < required:
        raise FactorRepairError("repair_space_insufficient")
    implementation_files = repair_implementation_files()
    implementation = [asdict(file_identity(p, cancel=cancel)) for p in implementation_files]
    plan = {"kind": "stock_adj_factor_history_repair", "version": 1,
            "run_id": run_id, "lake_root": str(lake_root), "run_root": str(run_root),
            "scopes": [asdict(s) for s in scopes], "budget": asdict(budget),
            "source_rows": source, "source_hash": repair_hash(source), "anchors": anchors,
            "endpoints": [asdict(e) for e in endpoints], "source_fingerprints": identities,
            "target_preimages": [i for i in identities if i["path"] in expected_targets],
            "units": units, "implementation_fingerprints": implementation, "space_required_bytes": required,
            "target_inventory_bytes": target_bytes, "partition_validation": partition_validation}
    # Size admission happens before creating any run files, using the same JSON encoding.
    estimate = {**plan,"plan_hash":"0"*64}
    size = 1
    for chunk in json.JSONEncoder(sort_keys=True,separators=(",",":"),allow_nan=False).iterencode(estimate):
        size += len(chunk.encode())
        if size > REPAIR_PLAN_MAX_BYTES:
            raise FactorRepairError("repair_plan_size_exceeded")
    plan["plan_hash"] = repair_hash(plan)
    validate_repair_plan(plan, plan["plan_hash"])
    writer_guard()
    for identity in identities:
        st = Path(identity["path"]).stat()
        if (st.st_size, st.st_mtime_ns) != (identity["size"], identity["mtime_ns"]):
            raise FactorRepairError("input_drift")
    check_repair_cancel(cancel)
    atomic_repair_json(run_root / "plan.json", plan)
    return plan


def inspect_repair_minute_seed(connection, *, ts_code: str, freq: int,
                               first_trade_date: str, expected_dates,
                               price_paths, state_path: Path) -> dict:
    """Read only the exact prior expected date and last eight actual bars."""
    from orchestrator.defs.asset_guards.stk_mins_continuity import (
        previous_expected_trade_date,
    )
    from orchestrator.defs.stk_mins_qfq_macd_kdj import (
        GOLD_STK_MINS_QFQ_MACD_KDJ_PARAMS_KEY,
    )

    previous = previous_expected_trade_date(expected_dates, first_trade_date)
    if previous is None:
        raise FactorRepairError("repair_previous_expected_date_missing")
    state_path = check_repair_path(state_path)
    if not state_path.is_file():
        raise FactorRepairError("repair_exact_seed_file_missing")
    seed = connection.execute("""
      SELECT CAST(last_trade_time AS VARCHAR),params_key,indicator_version,
             macd_ema_fast,macd_ema_slow,macd_dea,kdj_k,kdj_d
      FROM read_parquet(?,hive_partitioning=false)
      WHERE ts_code=? AND freq=? AND trade_date=CAST(? AS DATE)
    """, [str(state_path), ts_code, freq, previous]).fetchall()
    if (len(seed) != 1 or seed[0][1] != GOLD_STK_MINS_QFQ_MACD_KDJ_PARAMS_KEY
            or seed[0][2] != 1 or seed[0][0] is None
            or any(v is None or not math.isfinite(v) for v in seed[0][3:])):
        raise FactorRepairError("repair_exact_seed_invalid")
    context = connection.execute("""
      SELECT CAST(trade_time AS VARCHAR) FROM read_parquet(?,hive_partitioning=false)
      WHERE ts_code=? AND freq=? AND trade_date<CAST(? AS DATE)
      ORDER BY trade_time DESC LIMIT 8
    """, [[str(check_repair_path(Path(p))) for p in price_paths], ts_code, freq,
            first_trade_date]).fetchall()
    times = tuple(sorted(r[0] for r in context))
    if len(times) != 8 or len(set(times)) != 8 or times[-1] != seed[0][0]:
        raise FactorRepairError("repair_seed_context_invalid")
    return {"previous_expected_date": previous, "seed_last_trade_time": seed[0][0],
            "context_times": times}


def inspect_repair_file_inventory(connection, paths, *, cancel=None, progress=None) -> dict:
    """Bounded native footer aggregation; include all retained rows, no dependency install."""
    files, total_bytes, total_rows, largest = [], 0, 0, 0
    unique = sorted({str(check_repair_path(Path(p))) for p in paths})
    for offset in range(0, len(unique), 64):
        batch = unique[offset:offset + 64]
        before = {name: Path(name).stat() for name in batch}
        check_repair_cancel(cancel)
        metadata = dict(connection.execute(
            "SELECT file_name,num_rows FROM parquet_file_metadata(?)", [batch]).fetchall())
        for name in batch:
            check_repair_cancel(cancel)
            path = Path(name)
            after = path.stat()
            if (before[name].st_size, before[name].st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise FactorRepairError("input_drift")
            rows = int(metadata[name])
            files.append((name, after.st_size, after.st_mtime_ns, rows))
            total_bytes += after.st_size
            total_rows += rows
            largest = max(largest, after.st_size)
        if progress:
            progress(offset + len(batch), len(unique))
    return {"files": files, "file_count": len(files), "file_bytes": total_bytes,
            "full_file_rows": total_rows, "largest_file_bytes": largest}


@cache
def _repair_catalog_path_patterns():
    from orchestrator.defs.catalog.lake_assets import LAKE_ASSET_CATALOG

    compiled = []
    for entry in LAKE_ASSET_CATALOG:
        if not entry.path_template or not entry.path_template.startswith("data_lake/"):
            continue
        template = entry.path_template.removeprefix("data_lake/")
        pattern = re.escape(template)
        for token in re.findall(r"\{([a-z_]+)\}", template):
            pattern = pattern.replace(re.escape("{" + token + "}"), "[^/]+")
        compiled.append((entry.asset_key, re.compile(pattern)))
    return tuple(compiled)


def repair_asset_for_path(lake_root: Path, path: Path) -> str:
    """Resolve ownership with compiled static contracts; never cache business state."""
    if path.is_relative_to(lake_root):
        relative = path.relative_to(lake_root).as_posix()
        for key, pattern in _repair_catalog_path_patterns():
            if pattern.fullmatch(relative):
                return key
    raise FactorRepairError("repair_input_asset_unknown")


def inspect_repair_writers(definitions, instance, *, input_paths, lake_root: Path) -> dict:
    """Read actual state; never stop a sensor or claim maintenance from an idle moment."""
    import dagster as dg

    from orchestrator.defs.jobs.gold_stk_mins_qfq_macd_kdj_repair import (
        GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_JOB_NAME,
    )
    from orchestrator.defs.jobs.gold_stock_daily_qfq_factor_repair import (
        GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_JOB_NAME,
    )
    from orchestrator.defs.jobs.gold_stock_daily_trend_channel_repair import (
        GOLD_STOCK_DAILY_TREND_CHANNEL_REPAIR_JOB_NAME,
    )
    from orchestrator.defs.jobs.stock_mins_qfq_factor_repair import (
        STOCK_MINS_QFQ_FACTOR_REPAIR_JOB_NAME,
    )

    assets = set(approved_repair_asset_keys()) | {
        repair_asset_for_path(lake_root, Path(p)) for p in input_paths}
    jobs = {GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_JOB_NAME, GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_JOB_NAME,
            GOLD_STOCK_DAILY_TREND_CHANNEL_REPAIR_JOB_NAME, STOCK_MINS_QFQ_FACTOR_REPAIR_JOB_NAME}
    for job in definitions.resolve_all_job_defs():
        selected = {a.to_user_string() for a in job.asset_layer.selected_asset_keys}
        if selected & assets:
            jobs.add(job.name)
    sensors = {s.name for s in (definitions.sensors or ())
               if {t.job_name for t in s.targets} & jobs}
    schedules = {s.name for s in (definitions.schedules or ()) if s.job_name in jobs}
    names = sensors | schedules
    states = {s.name: s for s in instance.all_instigator_state() if s.name in names}
    # Missing/declared state is not proof that a default-running trigger is stopped.
    definitions_by_name = {d.name: d for d in (*(definitions.sensors or ()), *(definitions.schedules or ()))
                           if d.name in names}
    enabled = sorted(n for n in names if (n in states and states[n].status.value != "STOPPED")
                     or (n not in states and definitions_by_name[n].default_status.value == "RUNNING"))
    active = []
    statuses = [dg.DagsterRunStatus.QUEUED, dg.DagsterRunStatus.NOT_STARTED,
                dg.DagsterRunStatus.MANAGED, dg.DagsterRunStatus.STARTING,
                dg.DagsterRunStatus.STARTED, dg.DagsterRunStatus.CANCELING]
    for name in sorted(jobs):
        for run in instance.get_runs(filters=dg.RunsFilter(job_name=name, statuses=statuses), limit=100):
            selection = {a.to_user_string() for a in run.asset_selection} if run.asset_selection is not None else None
            if name == "__ASSET_JOB" and selection is not None and not selection & assets:
                continue
            active.append({"run_id": run.run_id, "job_name": name, "status": run.status.value})
    return {"writer_jobs": sorted(jobs), "writer_sensors": sorted(sensors),
            "writer_schedules": sorted(schedules), "enabled_triggers": enabled,
            "active_runs": active, "idle": not enabled and not active}


def repair_units_from_inspection(inspection: dict, *, lake_root: Path) -> tuple[dict, ...]:
    """Per-asset computation and unique target ownership; candidate merging stays per file."""
    groups = {asset:[] for asset in approved_repair_asset_keys()}
    for path in inspection["target_paths"]:
        asset = repair_asset_for_path(lake_root, Path(path))
        if asset not in approved_repair_asset_keys():
            raise FactorRepairError("repair_target_asset_not_approved")
        groups.setdefault(asset, []).append(path)
    codes = sorted({p["ts_code"] for p in inspection["profiles"]})
    if set(groups) != set(approved_repair_asset_keys()):
        raise FactorRepairError("repair_unit_assets_incomplete")
    units = []
    for asset, targets in sorted(groups.items()):
        profiles = [p for p in inspection["profiles"] if p["asset_key"] == asset]
        units.append({"asset_key": asset, "stock_codes": codes, "target_paths": sorted(targets),
                      "phase": "factor" if "adj_factor" in asset else
                               "price" if asset == "gold_stock_daily_qfq" or asset in {f"gold_stk_mins_qfq_{f}m" for f in (1,5,15,30,60,90,120)} else "indicator",
                      "validation_paths": inspection.get("validation_paths", {}).get(asset, []),
                      "calendar_dates": inspection["calendar_dates"],
                      "calculation_windows": [{"ts_code": p["ts_code"], "freq": p["freq"],
                          "windows": p["calculation_windows"],
                          "target_dates": p["target_dates"], "observed_dates": p["observed_dates"],
                          "previous_actual_date": p.get("previous_actual_date"),
                          "end_time": p["end_time"], "trade_date_rows": p["trade_date_rows"],
                          **{k:p[k] for k in ("previous_expected_date", "seed_last_trade_time", "context_times",
                              "daily_seed", "full_history_input_rows") if k in p},
                          **({"source_dates": p["source_dates"],
                              "source_inventory_paths": p["source_inventory_paths"]} if asset == "gold_stock_daily_qfq" else {})} for p in profiles]})
    return tuple(units)


def inspect_repair_daily_seed(connection, *, lake_root: Path, ts_code: str,
                              first_trade_date: str, previous_actual_date: str | None,
                              expected_dates) -> dict:
    """Daily trend seed or proven stock-listing initialization, never a missing-state fallback."""
    from orchestrator.defs.asset_guards.stk_mins_continuity import (
        previous_expected_trade_date,
    )
    from orchestrator.defs.paths import (
        gold_stock_daily_trend_channel_state_path,
        silver_stock_lifecycle_path,
    )

    life = connection.execute("""SELECT CAST(list_date AS VARCHAR)
      FROM read_parquet(?,hive_partitioning=false) WHERE ts_code=?""",
      [str(silver_stock_lifecycle_path(lake_root)), ts_code]).fetchall()
    if len(life) != 1:
        raise FactorRepairError("repair_daily_seed_lifecycle_invalid")
    if previous_actual_date is None:
        if life[0][0] != first_trade_date:
            raise FactorRepairError("repair_daily_initialization_not_proven")
        return {"initialized_from_listing": True, "state_path": None}
    previous = previous_expected_trade_date(expected_dates, first_trade_date)
    if previous is None:
        raise FactorRepairError("repair_previous_expected_date_missing")
    state = gold_stock_daily_trend_channel_state_path(lake_root, previous)
    if not state.is_file():
        raise FactorRepairError("repair_daily_seed_file_missing")
    rows = connection.execute("""SELECT CAST(state_source_trade_date AS VARCHAR),
      formula_version,short_upper_raw,short_lower_raw,long_upper_raw,long_lower_raw
      FROM read_parquet(?,hive_partitioning=false)
      WHERE ts_code=? AND trade_date=CAST(? AS DATE)""", [str(state), ts_code, previous]).fetchall()
    if (len(rows) != 1 or rows[0][0] != previous_actual_date
            or rows[0][1] != "stock-daily-trend-channel-v1"
            or any(x is None or not math.isfinite(x) for x in rows[0][2:])):
        raise FactorRepairError("repair_daily_seed_invalid")
    return {"initialized_from_listing": False, "state_path": str(state),
            "previous_expected_date": previous, "state_source_trade_date": rows[0][0]}


def repair_implementation_files() -> tuple[Path, ...]:
    """Explicit factor/price/indicator calculation and validation closure, shared by freeze and load."""
    base = Path(__file__).parents[1]
    return tuple(base / name for name in (
        "bootstrap/stock_adj_factor_history_repair.py",
        "bootstrap/stock_adj_factor_history_repair_cli.py",
        "bootstrap/stock_adj_factor_history_repair_candidates.py",
        "bootstrap/stock_adj_factor_history_repair_execution.py",
        "bootstrap/stock_adj_factor_history_repair_runtime.py",
        "bootstrap/stock_adj_factor_history_repair_indicators.py",
        "stk_mins_qfq_macd_kdj_rules.py", "checks/stk_mins_qfq_macd_kdj_checks.py",
        "qfq_nineturn_integrity.py", "nineturn_formula.py", "run_contracts/qfq_nineturn.py",
        "bootstrap/stk_mins_qfq_derived_history.py", "stock_factor_price_checks.py",
        "paths.py", "duckdb_sql.py", "stock_daily_qfq.py", "stk_mins_qfq.py",
        "stock_daily_trend_channel.py", "stk_mins_qfq_macd_kdj.py", "qfq_nineturn.py",
        "io/cn_a_gold_minute_bars.py", "duckdb_connection.py",
        "run_contracts/asset_column_schemas.py", "run_contracts/column_schema.py",
        "asset_guards/stk_mins_continuity.py", "asset_guards/bounded_continuity.py",
        "run_contracts/cn_a_derived_minute_bars.py",
        "run_contracts/stk_mins.py", "run_contracts/metadata.py", "run_contracts/run_keys.py",
        "partitions.py", "checks/adj_factor_checks.py"))


def repair_price_dates(plan, profile, *, daily: bool) -> tuple[str, ...]:
    """Exact impact on existing Gold records, using frozen actual Silver predecessors."""
    code = profile["ts_code"]
    factors = {r["trade_date"] for r in plan["source_rows"] if r["ts_code"] == code}
    observed = profile["observed_dates"]
    allowed = {d for d in observed if d.replace("-", "") in factors}
    if daily:
        source = profile["source_dates"]
        previous = dict(zip(source[1:], source[:-1], strict=True))
        allowed.update(d for d in observed if previous.get(d, "").replace("-", "") in factors)
        scope = next(s for s in plan["scopes"] if s["ts_code"] == code)
        if scope.get("daily_basis_start_trade_date"):
            allowed.update(d for d in observed if d >= scope["daily_basis_start_trade_date"])
    return tuple(sorted(allowed))


def validate_price_repair_units(plan) -> None:
    try:
        _validate_price_repair_units(plan)
    except (KeyError, TypeError, IndexError) as error:
        raise FactorRepairError("repair_price_contract_incomplete") from error


def _validate_price_repair_units(plan) -> None:
    """Reject omitted windows/files even when the caller recomputes the plan hash."""
    from orchestrator.defs import paths
    from orchestrator.defs.stock_factor_price_checks import (
        ADJ_FACTOR_PARTITION_SET,
        adj_factor_partition_allowed_status,
    )
    assets = ("gold_stock_daily_qfq", *(f"gold_stk_mins_qfq_{f}m" for f in (1,5,15,30,60,90,120)))
    codes = {s["ts_code"] for s in plan["scopes"]}
    implementations = [i["path"] for i in plan["implementation_fingerprints"]]
    if set(implementations) != {str(p) for p in repair_implementation_files()} or len(set(implementations)) != len(implementations):
        raise FactorRepairError("repair_implementation_not_frozen")
    units = plan["units"]
    if len(units) != len(approved_repair_asset_keys()) or len({u["asset_key"] for u in units}) != len(units):
        raise FactorRepairError("repair_unit_assets_incomplete")
    endpoints = {(e["asset_key"], e["ts_code"]): e for e in plan["endpoints"]}
    root = Path(plan["lake_root"])
    inputs = {i["path"] for i in plan["source_fingerprints"]}
    days = {r["trade_date"] for r in plan["source_rows"]}
    for asset,helper in (("raw_tushare_adj_factor",paths.raw_adj_factor_path),("silver_adj_factor",paths.silver_adj_factor_path)):
        expected = {str(helper(root,f"{d[:4]}-{d[4:6]}-{d[6:]}")) for d in days}
        unit = next(u for u in units if u["asset_key"] == asset)
        if set(unit["target_paths"]) != expected or len(unit["target_paths"]) != len(expected):
            raise FactorRepairError("repair_factor_inventory_incomplete")
    for unit in units:
        if set(unit["stock_codes"]) != codes or len(unit["stock_codes"]) != 25:
            raise FactorRepairError("repair_unit_scope_invalid")
        if unit["asset_key"] not in assets:
            continue
        profiles = unit.get("calculation_windows", [])
        if len(profiles) != 25 or {p["ts_code"] for p in profiles} != codes:
            raise FactorRepairError("repair_price_profiles_incomplete")
        expected_targets = set()
        daily = unit["asset_key"] == assets[0]
        for profile in profiles:
            e = endpoints[(unit["asset_key"], profile["ts_code"])]
            counts = profile.get("trade_date_rows", [])
            observed = tuple(d for d, n in counts if n > 0)
            if (tuple(d for d,n in counts) != tuple(e["expected_dates"])
                or any(not isinstance(n,int) or n < 0 or n > RepairBudget().max_stock_batch_rows for d,n in counts)
                or sum(n for d,n in counts) != e["calculation_rows"]
                or tuple(profile["observed_dates"]) != observed or not observed
                or observed[0] != e["calculation_start_date"]
                or observed[-1] != e["end_time"][:10]
                or profile["end_time"] != e["end_time"] or profile["freq"] != e["freq"]):
                raise FactorRepairError("repair_price_endpoint_mismatch")
            windows = profile["windows"]
            if tuple(d for w in windows for d in w) != tuple(e["expected_dates"]):
                raise FactorRepairError("repair_price_windows_incomplete")
            row_counts = dict(counts)
            if any(not w or len({d[:4] for d in w}) != 1 or sum(row_counts[d] for d in w) > RepairBudget().max_stock_batch_rows for w in windows):
                raise FactorRepairError("repair_stock_row_budget_exceeded")
            if daily:
                source = profile.get("source_dates", [])
                inventory = profile.get("source_inventory_paths", [])
                if (not source or tuple(source) != tuple(sorted(set(source)))
                    or not set(observed) <= set(source) or source[-1] > e["end_time"][:10]
                    or not inventory or len(set(inventory)) != len(inventory) or not set(inventory) <= inputs):
                    raise FactorRepairError("repair_daily_source_inventory_invalid")
                for d in source:
                    if str(paths.silver_stock_daily_path(root,d)) not in inventory:
                        raise FactorRepairError("repair_daily_source_inventory_invalid")
                before = max((d for d in source if d < observed[0]),default=None)
                if profile.get("previous_actual_date") != before:
                    raise FactorRepairError("repair_previous_source_date_invalid")
            dates = repair_price_dates(plan, profile, daily=daily)
            if tuple(profile["target_dates"]) != dates:
                raise FactorRepairError("repair_price_dates_not_approved")
            for day in dates:
                target = paths.gold_stock_daily_qfq_path(root,day) if daily else paths.gold_stk_mins_qfq_path(root,profile["freq"],profile["ts_code"],day[:4])
                expected_targets.add(str(target))
        if set(unit["target_paths"]) != expected_targets or len(unit["target_paths"]) != len(expected_targets):
            raise FactorRepairError("repair_price_target_inventory_incomplete")
        if not daily:
            validation = unit.get("validation_paths", [])
            if not set(unit["target_paths"]) <= set(validation) or not set(validation) <= inputs or len(set(validation)) != len(validation):
                raise FactorRepairError("repair_validation_inventory_invalid")
            validate_repair_target_paths(root,unit["asset_key"],validation)
    proof = plan.get("partition_validation", {})
    days = {r["trade_date"] for r in plan["source_rows"]}
    registered = proof.get("registered_keys", [])
    try:
        if date.fromisoformat(proof["checked_on"]).isoformat() != proof["checked_on"]:
            raise ValueError()
    except (KeyError,TypeError,ValueError) as error:
        raise FactorRepairError("repair_partition_evidence_missing") from error
    if proof.get("partition_set") != ADJ_FACTOR_PARTITION_SET or tuple(registered) != tuple(sorted(set(registered))) or not proof.get("checked_on"):
        raise FactorRepairError("repair_partition_evidence_missing")
    for d in days:
        day = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        if not adj_factor_partition_allowed_status(partition_key=day,registered_keys=set(registered),today=proof["checked_on"])["passed"]:
            raise FactorRepairError("repair_factor_partition_not_allowed")


def indicator_repair_assets() -> tuple[str, ...]:
    return tuple(a for a in approved_repair_asset_keys() if a not in (
        "raw_tushare_adj_factor", "silver_adj_factor", "gold_stock_daily_qfq",
        *(f"gold_stk_mins_qfq_{f}m" for f in (1,5,15,30,60,90,120))))


def indicator_repair_target(root, asset, code, freq, day):
    from orchestrator.defs import paths
    if asset == "gold_stock_daily_trend_channel":
        return paths.gold_stock_daily_trend_channel_path(root,day)
    if asset == "gold_stock_daily_trend_channel_state":
        return paths.gold_stock_daily_trend_channel_state_path(root,day)
    if asset == "gold_stock_daily_qfq_nineturn":
        return paths.gold_stock_daily_qfq_nineturn_path(root,day)
    if "nineturn" in asset:
        return paths.gold_stk_mins_qfq_nineturn_path(root,freq,day)
    if "_state_" in asset:
        return paths.gold_stk_mins_qfq_macd_kdj_state_path(root,freq,day)
    return paths.gold_stk_mins_qfq_macd_kdj_path(root,freq,code,day[:4])


def validate_indicator_repair_units(plan) -> None:
    """Complete replay facts, separately from price impact and final replacement keys."""
    try:
        _validate_indicator_repair_units(plan)
    except (KeyError,TypeError,IndexError,ValueError) as error:
        raise FactorRepairError("repair_indicator_contract_incomplete") from error


def _validate_indicator_repair_units(plan) -> None:
    from orchestrator.defs import paths
    units={u["asset_key"]:u for u in plan["units"]}
    endpoints={(e["asset_key"],e["ts_code"]):e for e in plan["endpoints"]}
    codes={s["ts_code"] for s in plan["scopes"]}
    inputs={i["path"] for i in plan["source_fingerprints"]}
    root=Path(plan["lake_root"])
    if not {str(paths.silver_trade_calendar_path(root)),str(paths.silver_stock_lifecycle_path(root))} <= inputs:
        raise FactorRepairError("repair_indicator_reference_missing")
    for asset in indicator_repair_assets():
        u=units[asset]; profiles=u["calculation_windows"];calendar=u["calendar_dates"]
        if (len(profiles)!=25 or {p["ts_code"] for p in profiles}!=codes
            or not calendar or tuple(calendar)!=tuple(sorted(set(calendar)))
            or any(date.fromisoformat(d).isoformat()!=d for d in calendar)):
            raise FactorRepairError("repair_indicator_profiles_incomplete")
        targets=set()
        partition_set=("cn_a_stock_daily_trend_channel_trade_days" if "trend_channel" in asset
            else "cn_a_stock_trade_days" if asset.startswith("gold_stock_daily") else "cn_a_stock_mins_silver_trade_days")
        registered=plan["partition_validation"]["indicator_sets"][partition_set]
        if tuple(registered) != tuple(sorted(set(registered))):
            raise FactorRepairError("repair_indicator_partition_evidence_invalid")
        for p in profiles:
            e=endpoints[asset,p["ts_code"]];counts=p["trade_date_rows"]
            expected=tuple(e["expected_dates"]); observed=tuple(d for d,n in counts if n>0)
            if (p["freq"]!=e["freq"] or p["end_time"]!=e["end_time"]
                or tuple(d for d,n in counts)!=expected or sum(n for d,n in counts)!=e["calculation_rows"]
                or any(type(n) is not int or n<0 for d,n in counts)
                or tuple(p["observed_dates"])!=observed
                or expected != tuple(d for d in calendar if e["calculation_start_date"]<=d<=e["end_time"][:10])
                or not set(expected)<=set(registered)):
                raise FactorRepairError("repair_indicator_endpoint_mismatch")
            state="_state" in asset
            if state and observed!=expected:
                raise FactorRepairError("repair_state_expected_date_missing")
            wanted=expected if state else observed
            if tuple(p["target_dates"])!=wanted or not wanted:
                raise FactorRepairError("repair_indicator_dates_invalid")
            if tuple(d for w in p["windows"] for d in w)!=expected:
                raise FactorRepairError("repair_indicator_windows_incomplete")
            rows=dict(counts)
            context=8 if "macd_kdj" in asset else 0
            if any(not w or sum(rows[d] for d in w)+context>RepairBudget().max_stock_batch_rows for w in p["windows"]):
                raise FactorRepairError("repair_stock_row_budget_exceeded")
            first=e["calculation_start_date"]
            price_asset="gold_stock_daily_qfq" if p["freq"] is None else f"gold_stk_mins_qfq_{p['freq']}m"
            price=endpoints[price_asset,p["ts_code"]]
            if first!=price["calculation_start_date"]:
                raise FactorRepairError("repair_indicator_start_invalid")
            if "macd_kdj" in asset:
                for k in ("previous_expected_date","seed_last_trade_time","context_times"):
                    if (tuple(p[k])!=tuple(e[k]) if k=="context_times" else p[k]!=e[k]):raise FactorRepairError("repair_seed_context_invalid")
                previous=max((d for d in calendar if d<first),default=None)
                seed=paths.gold_stk_mins_qfq_macd_kdj_state_path(root,p["freq"],previous or "invalid")
                if p["previous_expected_date"]!=previous or str(seed) not in inputs:
                    raise FactorRepairError("repair_exact_seed_invalid")
            elif "trend_channel" in asset:
                seed=p["daily_seed"]
                if seed["initialized_from_listing"]:
                    if p["ts_code"]!="688689.SH" or first!="2021-01-27" or seed["state_path"] is not None:
                        raise FactorRepairError("repair_daily_initialization_not_proven")
                else:
                    previous=max((d for d in calendar if d<first),default=None)
                    if (seed["previous_expected_date"]!=previous or seed["state_path"]!=str(paths.gold_stock_daily_trend_channel_state_path(root,previous))
                        or seed["state_path"] not in inputs or seed["state_source_trade_date"]>=first):
                        raise FactorRepairError("repair_daily_seed_invalid")
            if "nineturn" in asset and (type(p["full_history_input_rows"]) is not int or p["full_history_input_rows"]<=0):
                raise FactorRepairError("repair_nineturn_history_incomplete")
            targets.update(str(indicator_repair_target(root,asset,p["ts_code"],p["freq"],d)) for d in wanted)
        if set(u["target_paths"])!=targets or len(u["target_paths"])!=len(targets):
            raise FactorRepairError("repair_indicator_target_inventory_incomplete")
        validation=u["validation_paths"]
        if not targets<=set(validation) or not set(validation)<=inputs or len(validation)!=len(set(validation)):
            raise FactorRepairError("repair_validation_inventory_invalid")
        validate_repair_target_paths(root,asset,validation)
