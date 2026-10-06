"""Market Silver candidate normalization, verified against its stable Raw."""

import json
from pathlib import Path

from orchestrator.defs.checks.moneyflow import (
    audit_market_moneyflow_file,
    audit_market_moneyflow_standardization,
)
from orchestrator.defs.io.moneyflow_raw_writer import (
    candidate_file_hash,
    market_candidate_connection,
    market_candidate_directory,
    write_market_receipt,
)
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_STABILITY_SECONDS,
    MoneyflowContractError,
    market_moneyflow_day,
)


def build_market_moneyflow_silver_candidate(raw: Path, trade_date: str) -> Path:
    market_moneyflow_day(trade_date)
    if not raw.is_absolute() or raw.name != "raw.parquet" or len(raw.parents) < 5:
        raise MoneyflowContractError("raw_candidate_path")
    expected = market_candidate_directory(
        raw.parents[4], raw.parents[2].name, trade_date
    )
    if raw.parent != expected:
        raise MoneyflowContractError("raw_candidate_path")
    directory = raw.parent
    receipt = json.loads((directory / "receipt.json").read_text())
    if (
        receipt.get("stage") != "raw_candidate_ready"
        or receipt.get("trade_date") != trade_date
        or receipt.get("source") != "tushare"
        or receipt.get("row_count") != 1
        or receipt.get("stability_gap_seconds", 0) < MONEYFLOW_STABILITY_SECONDS
        or receipt.get("raw_sha256") != candidate_file_hash(raw)
    ):
        raise MoneyflowContractError("raw_source_proof")
    target = directory / "silver.parquet"
    if target.exists():
        raise MoneyflowContractError("operation_conflict")
    with market_candidate_connection(directory) as connection:
        audit_market_moneyflow_file(connection, raw, trade_date)
        connection.execute(
            "COPY (SELECT * REPLACE(strptime(trade_date,'%Y%m%d')::DATE AS trade_date) "
            "FROM read_parquet($source,hive_partitioning=false)) TO $target (FORMAT PARQUET)",
            {"source": str(raw), "target": str(target)},
        )
        audit_market_moneyflow_standardization(connection, raw, target, trade_date)
    write_market_receipt(
        directory,
        {
            **receipt,
            "stage": "silver_candidate_ready",
            "silver_sha256": candidate_file_hash(target),
        },
    )
    return target
