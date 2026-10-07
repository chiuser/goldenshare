"""Date-only independent daily moneyflow Silver conversion from proven stable Raw candidates."""

import json
from pathlib import Path
from time import perf_counter

from orchestrator.defs.checks.moneyflow_daily import (
    audit_daily_moneyflow_equality,
    audit_daily_moneyflow_file,
    audit_daily_moneyflow_standardization,
    daily_file_scope_counts,
)
from orchestrator.defs.io.moneyflow_candidates import (
    candidate_file_hash,
    moneyflow_candidate_connection,
    moneyflow_candidate_directory,
    write_moneyflow_receipt,
)
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_MAX_ELAPSED_SECONDS,
    MONEYFLOW_STABILITY_SECONDS,
    MoneyflowContractError,
    assert_moneyflow_memory_budget,
    market_moneyflow_day,
    moneyflow_peak_rss_bytes,
)
from orchestrator.defs.run_contracts.moneyflow_daily import (
    daily_key_fields,
    daily_schema,
)


def build_daily_moneyflow_silver_candidate(
    raw: Path, trade_date: str, *, dataset: str
) -> Path:
    daily_schema(dataset)
    started = perf_counter()
    assert_moneyflow_memory_budget()
    market_moneyflow_day(trade_date)
    if not raw.is_absolute() or raw.name != "raw.parquet" or len(raw.parents) < 5:
        raise MoneyflowContractError("raw_candidate_path")
    expected = moneyflow_candidate_directory(
        raw.parents[4], raw.parents[2].name, trade_date, dataset=dataset
    )
    if raw.parent != expected:
        raise MoneyflowContractError("raw_candidate_path")
    directory = raw.parent
    receipt = json.loads((directory / "receipt.json").read_text())
    verification = directory / "verification.parquet"
    if (
        receipt.get("stage") != "raw_candidate_ready"
        or receipt.get("dataset") != dataset
        or receipt.get("trade_date") != trade_date
        or receipt.get("source") != "tushare"
        or receipt.get("stability_gap_seconds", 0) < MONEYFLOW_STABILITY_SECONDS
        or receipt.get("raw_sha256") != candidate_file_hash(raw)
        or receipt.get("verification_sha256") != candidate_file_hash(verification)
    ):
        raise MoneyflowContractError("raw_source_proof")
    silver = directory / "silver.parquet"
    if silver.exists():
        raise MoneyflowContractError("operation_conflict")

    def elapsed_ms():
        return receipt["elapsed_ms"] + (perf_counter() - started) * 1000

    if elapsed_ms() >= MONEYFLOW_MAX_ELAPSED_SECONDS * 1000:
        raise MoneyflowContractError("request_budget_exceeded")
    with moneyflow_candidate_connection(directory) as connection:
        count = audit_daily_moneyflow_file(connection, raw, trade_date, dataset=dataset)
        if (
            count != receipt.get("row_count")
            or audit_daily_moneyflow_file(
                connection, verification, trade_date, dataset=dataset
            )
            != count
        ):
            raise MoneyflowContractError("raw_source_count")
        if receipt.get("scope_row_counts") != daily_file_scope_counts(
            connection, raw, dataset=dataset
        ):
            raise MoneyflowContractError("raw_source_scope_count")
        audit_daily_moneyflow_equality(connection, raw, verification, dataset=dataset)
        key_sql = ",".join(daily_key_fields(dataset))
        connection.execute(
            "COPY (SELECT * REPLACE(strptime(trade_date,'%Y%m%d')::DATE AS trade_date) "
            f"FROM read_parquet($source,hive_partitioning=false) ORDER BY {key_sql}) TO $target (FORMAT PARQUET)",
            {"source": str(raw), "target": str(silver)},
        )
        if audit_daily_moneyflow_standardization(
            connection, raw, silver, trade_date, dataset=dataset
        ) != receipt.get("row_count"):
            raise MoneyflowContractError("raw_source_count")
    assert_moneyflow_memory_budget()
    if elapsed_ms() >= MONEYFLOW_MAX_ELAPSED_SECONDS * 1000:
        raise MoneyflowContractError("request_budget_exceeded")
    write_moneyflow_receipt(
        directory,
        {
            **receipt,
            "stage": "silver_candidate_ready",
            "silver_sha256": candidate_file_hash(silver),
            "peak_rss_bytes": moneyflow_peak_rss_bytes(),
            "elapsed_ms": elapsed_ms(),
        },
    )
    return silver
