"""Market Raw candidates and source receipts; no formal promotion or events."""

import hashlib
import json
import os
from pathlib import Path

from orchestrator.defs.checks.moneyflow import audit_market_moneyflow_file
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_MONEYFLOW_MKT_DC_SCHEMA,
)
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_DUCKDB_MEMORY_LIMIT,
    MONEYFLOW_DUCKDB_THREADS,
    MoneyflowContractError,
    market_moneyflow_day,
)
from orchestrator.defs.source_readiness.moneyflow import collect_market_moneyflow


def market_candidate_directory(
    staging_root: Path, operation_id: str, trade_date: str
) -> Path:
    market_moneyflow_day(trade_date)
    if not staging_root.is_absolute() or ".." in staging_root.parts:
        raise MoneyflowContractError("staging_root")
    if any(p.is_symlink() for p in (staging_root, *staging_root.parents)):
        raise MoneyflowContractError("staging_symlink")
    if not operation_id or any(
        c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        for c in operation_id
    ):
        raise MoneyflowContractError("operation_id")
    resolved = staging_root.resolve()
    if (
        resolved == Path(DEFAULT_LAKE_ROOT)
        or Path(DEFAULT_LAKE_ROOT) in resolved.parents
    ):
        raise MoneyflowContractError("formal_lake_is_not_staging")
    if (resolved == Path("/Volumes") or Path("/Volumes") in resolved.parents) and not (
        resolved == Path(DEFAULT_LAKE_STAGING_ROOT)
        or Path(DEFAULT_LAKE_STAGING_ROOT) in resolved.parents
    ):
        raise MoneyflowContractError("staging_volume_root")
    directory = resolved / "moneyflow" / operation_id / "moneyflow_mkt_dc" / trade_date
    if any(p.is_symlink() for p in (directory, *directory.parents)):
        raise MoneyflowContractError("staging_symlink")
    return directory


def market_candidate_connection(directory: Path):
    return connect_configured_duckdb(
        DuckDBConnectionSettings(
            temp_directory=directory,
            memory_limit=MONEYFLOW_DUCKDB_MEMORY_LIMIT,
            threads=MONEYFLOW_DUCKDB_THREADS,
        ),
        temp_policy="existing_no_spill",
    )


def candidate_file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_market_receipt(directory: Path, receipt: dict) -> None:
    candidate = directory / "receipt.json.tmp"
    candidate.write_text(json.dumps(receipt, sort_keys=True))
    os.replace(candidate, directory / "receipt.json")


def build_market_moneyflow_raw_candidate(
    *,
    tushare,
    staging_root: Path,
    operation_id: str,
    trade_date: str,
    **collection_options,
) -> Path:
    directory = market_candidate_directory(staging_root, operation_id, trade_date)
    target = directory / "raw.parquet"
    try:
        directory.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise MoneyflowContractError("operation_conflict") from error
    write_market_receipt(directory, {"stage": "collecting", "trade_date": trade_date})

    def persist_first(row):
        source = directory / "source.json"
        source.write_text(json.dumps([row]))
        projection = ", ".join(
            f'CAST("{c.name}" AS {c.type}) AS "{c.name}"'
            for c in RAW_TUSHARE_MONEYFLOW_MKT_DC_SCHEMA
        )
        with market_candidate_connection(directory) as connection:
            connection.execute(
                f"COPY (SELECT {projection} FROM read_json($source,format='array')) TO $target (FORMAT PARQUET)",
                {"source": str(source), "target": str(target)},
            )
            audit_market_moneyflow_file(connection, target, trade_date)

    stable = collect_market_moneyflow(
        tushare=tushare,
        trade_date=trade_date,
        on_first_round=persist_first,
        **collection_options,
    )
    write_market_receipt(
        directory,
        {
            "stage": "raw_candidate_ready",
            "trade_date": trade_date,
            "source": "tushare",
            "row_count": 1,
            "row_hash": stable.row_hash,
            "raw_sha256": candidate_file_hash(target),
            "request_count": stable.request_count,
            "retry_count": stable.retry_count,
            "elapsed_ms": stable.elapsed_ms,
            "stability_gap_seconds": stable.stability_gap_seconds,
        },
    )
    return target
