"""Market moneyflow daily publication from proven candidates, one file at a time."""

from pathlib import Path
from time import perf_counter

from orchestrator.defs.checks.moneyflow import (
    audit_market_moneyflow_file,
    audit_market_moneyflow_standardization,
)
from orchestrator.defs.io.moneyflow_candidates import (
    candidate_file_hash,
    moneyflow_candidate_connection,
    moneyflow_candidate_directory,
    moneyflow_writer_lock,
)
from orchestrator.defs.io.moneyflow_raw_writer import (
    build_market_moneyflow_raw_candidate,
)
from orchestrator.defs.io.moneyflow_update_publication import (
    assert_moneyflow_update_path,
    assert_moneyflow_update_roots,
    publish_moneyflow_update_file,
    read_moneyflow_update_control,
)
from orchestrator.defs.paths import (
    raw_moneyflow_path,
    silver_moneyflow_path,
)
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_MAX_ELAPSED_SECONDS,
    MONEYFLOW_MAX_REQUESTS,
    MONEYFLOW_MKT_DC_FIELDS,
    MONEYFLOW_STABILITY_SECONDS,
    MoneyflowContractError,
    assert_moneyflow_memory_budget,
    market_moneyflow_row_hash,
    normalize_market_moneyflow_row,
)

DATASET = "moneyflow_mkt_dc"


def update_market_moneyflow_raw(
    *,
    tushare,
    lake_root: Path,
    staging_root: Path,
    operation_id: str,
    trade_date: str,
    check_cancel=lambda: None,
    **collection_options,
) -> dict:
    directory = moneyflow_candidate_directory(
        staging_root, operation_id, trade_date, dataset=DATASET
    )
    assert_moneyflow_update_roots(lake_root, staging_root)
    namespace = staging_root / "moneyflow"
    namespace.mkdir(exist_ok=True)
    started = perf_counter()
    with moneyflow_writer_lock(namespace):
        check_cancel()
        receipt_path = directory / "receipt.json"
        if not receipt_path.exists():
            build_market_moneyflow_raw_candidate(
                tushare=tushare,
                staging_root=staging_root,
                operation_id=operation_id,
                trade_date=trade_date,
                check_cancel=check_cancel,
                **collection_options,
            )
        receipt = read_moneyflow_update_control(receipt_path)
        if (
            receipt.get("stage") != "raw_candidate_ready"
            or receipt.get("source") != "tushare"
            or receipt.get("trade_date") != trade_date
            or receipt.get("row_count") != 1
            or not 2 <= receipt.get("request_count", 0) <= MONEYFLOW_MAX_REQUESTS
            or receipt.get("stability_gap_seconds", 0) < MONEYFLOW_STABILITY_SECONDS
            or not 0
            <= receipt.get("elapsed_ms", -1)
            < MONEYFLOW_MAX_ELAPSED_SECONDS * 1000
        ):
            raise MoneyflowContractError("raw_source_proof")
        raw = directory / "raw.parquet"
        target = raw_moneyflow_path(lake_root, DATASET, trade_date)
        assert_moneyflow_update_path(target)
        proof_file = raw if raw.exists() else target
        checkpoint = directory / "promotion-raw.json"
        if not checkpoint.exists() and (
            not raw.exists() or candidate_file_hash(raw) != receipt.get("raw_sha256")
        ):
            raise MoneyflowContractError("raw_source_proof")
        with moneyflow_candidate_connection(directory) as connection:
            audit_market_moneyflow_file(connection, proof_file, trade_date)
            values = connection.execute(
                "SELECT * FROM read_parquet(?,hive_partitioning=false)",
                [str(proof_file)],
            ).fetchone()
            row = normalize_market_moneyflow_row(
                dict(zip(MONEYFLOW_MKT_DC_FIELDS, values, strict=True)), trade_date
            )
            if market_moneyflow_row_hash(row) != receipt.get("row_hash"):
                raise MoneyflowContractError("raw_source_proof")
            assert_moneyflow_memory_budget()
            if (perf_counter() - started) >= MONEYFLOW_MAX_ELAPSED_SECONDS:
                raise MoneyflowContractError("request_budget_exceeded")
            state = publish_moneyflow_update_file(
                connection,
                raw,
                target,
                dataset=DATASET,
                audit_file=audit_market_moneyflow_file,
                day=trade_date,
                layer="raw",
                checkpoint=checkpoint,
                check_cancel=check_cancel,
            )
        return {
            **receipt,
            "target": str(target),
            "file_sha256": state["published_sha256"],
            "promotion_mode": state["mode"],
            "source_proof_path": str(receipt_path),
        }


def update_market_moneyflow_silver(
    *,
    lake_root: Path,
    staging_root: Path,
    operation_id: str,
    trade_date: str,
    expected_raw_hash: str,
    check_cancel=lambda: None,
) -> dict:
    directory = moneyflow_candidate_directory(
        staging_root, operation_id, trade_date, dataset=DATASET
    )
    assert_moneyflow_update_roots(lake_root, staging_root)
    namespace = staging_root / "moneyflow"
    namespace.mkdir(exist_ok=True)
    with moneyflow_writer_lock(namespace):
        check_cancel()
        raw = raw_moneyflow_path(lake_root, DATASET, trade_date)
        assert_moneyflow_update_path(raw)
        if not raw.is_file() or candidate_file_hash(raw) != expected_raw_hash:
            raise MoneyflowContractError("raw_materialization_file_changed")
        directory.mkdir(parents=True, exist_ok=True)
        candidate = directory / "silver.parquet"
        target = silver_moneyflow_path(lake_root, DATASET, trade_date)
        assert_moneyflow_update_path(candidate)
        assert_moneyflow_update_path(target)
        checkpoint = directory / "promotion-silver.json"
        with moneyflow_candidate_connection(directory) as connection:
            audit_market_moneyflow_file(connection, raw, trade_date)
            if not checkpoint.exists():
                if candidate.exists():
                    audit_market_moneyflow_standardization(
                        connection, raw, candidate, trade_date
                    )
                else:
                    connection.execute(
                        "COPY (SELECT * REPLACE(strptime(trade_date,'%Y%m%d')::DATE AS trade_date) "
                        "FROM read_parquet($source,hive_partitioning=false)) TO $target (FORMAT PARQUET)",
                        {"source": str(raw), "target": str(candidate)},
                    )
                audit_market_moneyflow_standardization(
                    connection, raw, candidate, trade_date
                )
            assert_moneyflow_memory_budget()
            if candidate_file_hash(raw) != expected_raw_hash:
                raise MoneyflowContractError("raw_materialization_file_changed")
            state = publish_moneyflow_update_file(
                connection,
                candidate,
                target,
                dataset=DATASET,
                audit_file=audit_market_moneyflow_file,
                day=trade_date,
                layer="silver",
                raw_hash=expected_raw_hash,
                checkpoint=checkpoint,
                check_cancel=check_cancel,
            )
            audit_market_moneyflow_standardization(connection, raw, target, trade_date)
        return {
            "target": str(target),
            "row_count": 1,
            "raw_sha256": expected_raw_hash,
            "file_sha256": state["published_sha256"],
            "promotion_mode": state["mode"],
        }
