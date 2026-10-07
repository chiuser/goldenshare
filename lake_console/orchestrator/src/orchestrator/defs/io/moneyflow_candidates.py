"""Shared moneyflow candidate paths, isolated connections and receipts."""

import hashlib
import json
import os
from pathlib import Path

from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_DUCKDB_MEMORY_LIMIT,
    MONEYFLOW_DUCKDB_THREADS,
    MoneyflowContractError,
    market_moneyflow_day,
)


def moneyflow_candidate_directory(
    staging_root: Path, operation_id: str, trade_date: str, *, dataset: str
) -> Path:
    market_moneyflow_day(trade_date)
    if dataset not in {
        "moneyflow",
        "moneyflow_dc",
        "moneyflow_mkt_dc",
        "moneyflow_ind_ths",
        "moneyflow_cnt_ths",
        "moneyflow_ind_dc",
    }:
        raise MoneyflowContractError("candidate_dataset")
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
    directory = resolved / "moneyflow" / operation_id / dataset / trade_date
    if any(p.is_symlink() for p in (directory, *directory.parents)):
        raise MoneyflowContractError("staging_symlink")
    return directory


def moneyflow_candidate_connection(directory: Path):
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


def write_moneyflow_receipt(directory: Path, receipt: dict) -> None:
    candidate = directory / "receipt.json.tmp"
    candidate.write_text(json.dumps(receipt, sort_keys=True))
    os.replace(candidate, directory / "receipt.json")
