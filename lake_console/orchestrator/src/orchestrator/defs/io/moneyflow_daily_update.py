"""Daily moneyflow publication from proven candidates, one file at a time."""

from functools import partial
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
    moneyflow_writer_lock,
)
from orchestrator.defs.io.moneyflow_daily_raw_writer import (
    build_daily_moneyflow_raw_candidate,
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
    MONEYFLOW_MAX_ROWS_PER_ROUND,
    MONEYFLOW_STABILITY_SECONDS,
    MoneyflowContractError,
    assert_moneyflow_memory_budget,
)
from orchestrator.defs.run_contracts.moneyflow_daily import daily_key_fields


def _assert_daily_update_dataset(dataset: str) -> None:
    # Only explicitly onboarded daily sources may publish through this helper.
    if dataset not in {"moneyflow_ind_ths", "moneyflow_cnt_ths", "moneyflow_ind_dc", "moneyflow_dc", "moneyflow_ths"}:
        raise MoneyflowContractError("daily_update_dataset")


def update_daily_moneyflow_raw(
    *,
    dataset: str,
    tushare,
    lake_root: Path,
    staging_root: Path,
    operation_id: str,
    trade_date: str,
    check_cancel=lambda: None,
    **collection_options,
) -> dict:
    _assert_daily_update_dataset(dataset)
    audit_file = partial(audit_daily_moneyflow_file, dataset=dataset)
    directory = moneyflow_candidate_directory(
        staging_root, operation_id, trade_date, dataset=dataset
    )
    assert_moneyflow_update_roots(lake_root, staging_root)
    namespace = staging_root / "moneyflow"
    namespace.mkdir(exist_ok=True)
    started = perf_counter()
    with moneyflow_writer_lock(namespace):
        check_cancel()
        receipt_path = directory / "receipt.json"
        if not receipt_path.exists():
            build_daily_moneyflow_raw_candidate(
                tushare=tushare,
                dataset=dataset,
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
            or receipt.get("dataset") != dataset
            or type(receipt.get("row_count")) is not int
            or not 0 < receipt["row_count"] <= MONEYFLOW_MAX_ROWS_PER_ROUND
            or not 2 <= receipt.get("request_count", 0) <= MONEYFLOW_MAX_REQUESTS
            or receipt.get("stability_gap_seconds", 0) < MONEYFLOW_STABILITY_SECONDS
            or not 0
            <= receipt.get("elapsed_ms", -1)
            < MONEYFLOW_MAX_ELAPSED_SECONDS * 1000
        ):
            raise MoneyflowContractError("raw_source_proof")
        raw = directory / "raw.parquet"
        target = raw_moneyflow_path(lake_root, dataset, trade_date)
        assert_moneyflow_update_path(target)
        proof_file = raw if raw.exists() else target
        checkpoint = directory / "promotion-raw.json"
        if not checkpoint.exists() and (
            not raw.exists() or candidate_file_hash(raw) != receipt.get("raw_sha256")
        ):
            raise MoneyflowContractError("raw_source_proof")
        with moneyflow_candidate_connection(directory) as connection:
            verification = directory / "verification.parquet"
            assert_moneyflow_update_path(verification)
            if not verification.is_file() or candidate_file_hash(
                verification
            ) != receipt.get("verification_sha256"):
                raise MoneyflowContractError("raw_source_proof")
            count = audit_file(connection, proof_file, trade_date)
            if (
                count != receipt["row_count"]
                or audit_file(connection, verification, trade_date) != count
            ):
                raise MoneyflowContractError("raw_source_count")
            if receipt.get("scope_row_counts") != daily_file_scope_counts(
                connection, proof_file, dataset=dataset
            ):
                raise MoneyflowContractError("raw_source_scope_count")
            audit_daily_moneyflow_equality(
                connection, proof_file, verification, dataset=dataset
            )
            assert_moneyflow_memory_budget()
            if (perf_counter() - started) >= MONEYFLOW_MAX_ELAPSED_SECONDS:
                raise MoneyflowContractError("request_budget_exceeded")
            state = publish_moneyflow_update_file(
                connection,
                raw,
                target,
                dataset=dataset,
                audit_file=audit_file,
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


def update_daily_moneyflow_silver(
    *,
    dataset: str,
    lake_root: Path,
    staging_root: Path,
    operation_id: str,
    trade_date: str,
    expected_raw_hash: str,
    check_cancel=lambda: None,
) -> dict:
    _assert_daily_update_dataset(dataset)
    audit_file = partial(audit_daily_moneyflow_file, dataset=dataset)
    directory = moneyflow_candidate_directory(
        staging_root, operation_id, trade_date, dataset=dataset
    )
    assert_moneyflow_update_roots(lake_root, staging_root)
    namespace = staging_root / "moneyflow"
    namespace.mkdir(exist_ok=True)
    with moneyflow_writer_lock(namespace):
        check_cancel()
        raw = raw_moneyflow_path(lake_root, dataset, trade_date)
        assert_moneyflow_update_path(raw)
        if not raw.is_file() or candidate_file_hash(raw) != expected_raw_hash:
            raise MoneyflowContractError("raw_materialization_file_changed")
        directory.mkdir(parents=True, exist_ok=True)
        candidate = directory / "silver.parquet"
        target = silver_moneyflow_path(lake_root, dataset, trade_date)
        assert_moneyflow_update_path(candidate)
        assert_moneyflow_update_path(target)
        checkpoint = directory / "promotion-silver.json"
        with moneyflow_candidate_connection(directory) as connection:
            audit_standardization = partial(
                audit_daily_moneyflow_standardization, dataset=dataset
            )
            count = audit_file(connection, raw, trade_date)
            if not checkpoint.exists():
                if candidate.exists():
                    audit_standardization(connection, raw, candidate, trade_date)
                else:
                    connection.execute(
                        "COPY (SELECT * REPLACE(strptime(trade_date,'%Y%m%d')::DATE AS trade_date) "
                        f"FROM read_parquet($source,hive_partitioning=false) ORDER BY {','.join(daily_key_fields(dataset))}) TO $target (FORMAT PARQUET)",
                        {"source": str(raw), "target": str(candidate)},
                    )
                audit_standardization(connection, raw, candidate, trade_date)
            assert_moneyflow_memory_budget()
            if candidate_file_hash(raw) != expected_raw_hash:
                raise MoneyflowContractError("raw_materialization_file_changed")
            state = publish_moneyflow_update_file(
                connection,
                candidate,
                target,
                dataset=dataset,
                audit_file=audit_file,
                day=trade_date,
                layer="silver",
                raw_hash=expected_raw_hash,
                checkpoint=checkpoint,
                check_cancel=check_cancel,
            )
            audit_standardization(connection, raw, target, trade_date)
        return {
            "target": str(target),
            "row_count": count,
            "raw_sha256": expected_raw_hash,
            "file_sha256": state["published_sha256"],
            "promotion_mode": state["mode"],
        }
