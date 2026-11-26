"""Freeze the approved Prod fund daily projection for one historical operation."""

from __future__ import annotations

import csv
import os
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from orchestrator.defs.bootstrap.etf_daily_bootstrap_plan import (
    HISTORY_START,
    EtfDailyBootstrapPlanError,
    EtfDailyRawBootstrapPlan,
    file_sha256,
    hash_payload,
    load_json,
    write_immutable_json,
)
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.etf_daily import FUND_DAILY_SOURCE_COLUMNS

PROD_FUND_DAILY_TABLE = "raw_tushare.fund_daily"
_REPO_ROOT = Path(__file__).resolve().parents[6]


@dataclass(frozen=True)
class EtfDailyHistorySource:
    path: Path
    fingerprint: str
    row_counts: dict[str, int]
    tushare_dates: frozenset[str]
    fetched_at: str


def _source_directory(staging_root: Path, plan: EtfDailyRawBootstrapPlan) -> Path:
    if not plan.historical:
        raise EtfDailyBootstrapPlanError(
            "Prod fund daily is only available for 2023–2024"
        )
    return staging_root / "etf_daily" / f"operation_id={plan.operation_id}-prod-source"


def _export_prod_csv(path: Path, timeout_seconds: int) -> None:
    if timeout_seconds <= 0:
        raise EtfDailyBootstrapPlanError("Prod export timeout must be positive")
    columns = ", ".join(FUND_DAILY_SOURCE_COLUMNS)
    query = f"""
        BEGIN READ ONLY;
        SET LOCAL statement_timeout = '{timeout_seconds}s';
        SET LOCAL max_parallel_workers_per_gather = 0;
        COPY (
            SELECT {columns} FROM {PROD_FUND_DAILY_TABLE}
            WHERE trade_date >= DATE '{HISTORY_START}' AND trade_date < DATE '2025-01-01'
        ) TO STDOUT WITH CSV HEADER;
        ROLLBACK;
    """
    try:
        with path.open("wb") as output:
            result = subprocess.run(
                ["bash", "scripts/psql-remote.sh", "--", "-q"],
                cwd=_REPO_ROOT,
                env={**os.environ, "PGCONNECT_TIMEOUT": "8"},
                input=query.encode(),
                stdout=output,
                stderr=subprocess.PIPE,
                timeout=timeout_seconds + 8,
                check=False,
            )
    except subprocess.TimeoutExpired as error:
        raise EtfDailyBootstrapPlanError(
            "Prod fund daily export exceeded its approved timeout"
        ) from error
    if result.returncode:
        raise EtfDailyBootstrapPlanError(
            f"Prod fund daily export failed ({result.returncode})"
        )


def _convert_prod_source(
    csv_path: Path, parquet_path: Path, duckdb: DuckDBResource, dates: tuple[str, ...]
) -> dict[str, int]:
    with csv_path.open(newline="") as handle:
        if tuple(next(csv.reader(handle), ())) != FUND_DAILY_SOURCE_COLUMNS:
            raise EtfDailyBootstrapPlanError(
                "Prod fund daily column projection differs"
            )
    csv_sql = f"read_csv({duckdb_string(csv_path)}, header=true, all_varchar=true)"
    with duckdb.connect() as connection:
        rows = connection.execute(f"""
            SELECT CAST(CAST(trade_date AS DATE) AS VARCHAR), count(*),
                   count(DISTINCT ts_code), count(*) FILTER (WHERE trim(ts_code) = '' OR ts_code IS NULL)
            FROM {csv_sql} GROUP BY 1
        """).fetchall()
        counts = {day: count for day, count, _, _ in rows}
        if (
            not counts
            or set(counts) - set(dates)
            or any(count != distinct or invalid for _, count, distinct, invalid in rows)
        ):
            raise EtfDailyBootstrapPlanError(
                "Prod fund daily has invalid dates or business keys"
            )
        numeric = ", ".join(
            f'CAST("{name}" AS DOUBLE) AS "{name}"'
            for name in FUND_DAILY_SOURCE_COLUMNS[2:]
        )
        connection.execute(f"""
            COPY (SELECT ts_code, strftime(CAST(trade_date AS DATE), '%Y%m%d') AS trade_date,
                         {numeric} FROM {csv_sql} ORDER BY trade_date, ts_code)
            TO {duckdb_string(parquet_path)} (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 2048)
        """)
    return counts


def prepare_history_source(
    *,
    staging_root: Path,
    plan: EtfDailyRawBootstrapPlan,
    duckdb: DuckDBResource,
    tushare_dates: Sequence[str],
    timeout_seconds: int,
) -> EtfDailyHistorySource:
    directory = _source_directory(staging_root, plan)
    if set(tushare_dates) - set(plan.trade_dates):
        raise EtfDailyBootstrapPlanError(
            "Tushare fallback date is outside the historical plan"
        )
    if not directory.exists():
        directory.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(
            prefix=f".{directory.name}-", dir=directory.parent
        ) as temp:
            work = Path(temp)
            csv_path = work / "prod.csv"
            parquet = work / "fund_daily.parquet"
            _export_prod_csv(csv_path, timeout_seconds)
            fetched_at = datetime.now().astimezone().isoformat()
            counts = _convert_prod_source(csv_path, parquet, duckdb, plan.trade_dates)
            csv_path.unlink()
            payload = {
                "raw_plan_hash": plan.raw_plan_hash,
                "source_table": PROD_FUND_DAILY_TABLE,
                "fetched_at": fetched_at,
                "row_counts": counts,
                "confirmed_fallback_dates": sorted(set(tushare_dates)),
                "file_sha256": file_sha256(parquet),
            }
            write_immutable_json(
                work / "source.json", {**payload, "fingerprint": hash_payload(payload)}
            )
            work.rename(directory)
    result = load_history_source(staging_root, plan)
    if not set(tushare_dates) <= result.tushare_dates:
        raise EtfDailyBootstrapPlanError(
            "confirmed fallback dates differ from the frozen source"
        )
    return result


def load_history_source(
    staging_root: Path, plan: EtfDailyRawBootstrapPlan
) -> EtfDailyHistorySource:
    directory = _source_directory(staging_root, plan)
    manifest = load_json(directory / "source.json", label="ETF historical Prod source")
    parquet = directory / "fund_daily.parquet"
    fingerprint = manifest.pop("fingerprint", None)
    if (
        manifest.get("raw_plan_hash") != plan.raw_plan_hash
        or manifest.get("source_table") != PROD_FUND_DAILY_TABLE
        or fingerprint != hash_payload(manifest)
        or manifest.get("file_sha256") != file_sha256(parquet)
    ):
        raise EtfDailyBootstrapPlanError(
            "ETF historical Prod source fingerprint differs"
        )
    counts = manifest["row_counts"]
    return EtfDailyHistorySource(
        parquet,
        fingerprint,
        counts,
        frozenset(
            set(plan.trade_dates) - counts.keys()
            | set(manifest["confirmed_fallback_dates"])
        ),
        manifest["fetched_at"],
    )
