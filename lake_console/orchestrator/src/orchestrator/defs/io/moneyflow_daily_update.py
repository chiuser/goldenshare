"""Daily moneyflow publication from proven candidates, one file at a time."""

from functools import partial
from pathlib import Path
from time import perf_counter

from orchestrator.defs.asset_guards.moneyflow_row_count import (
    moneyflow_row_count_baseline,
    moneyflow_row_count_decision,
)
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
    write_moneyflow_receipt,
)
from orchestrator.defs.io.moneyflow_daily_raw_writer import (
    build_daily_moneyflow_raw_candidate,
)
from orchestrator.defs.io.moneyflow_ths_raw_merge import (
    assert_moneyflow_ths_file_budget,
    assert_moneyflow_ths_source_coverage,
    merge_moneyflow_ths_raw_candidate,
    moneyflow_ths_raw_connection,
    moneyflow_ths_raw_metadata,
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
from orchestrator.defs.source_readiness.moneyflow_ths import load_moneyflow_ths_universe


def _assert_daily_update_dataset(dataset: str) -> None:
    # Only explicitly onboarded daily sources may publish through this helper.
    if dataset not in {
        "moneyflow_ind_ths",
        "moneyflow_cnt_ths",
        "moneyflow_ind_dc",
        "moneyflow_dc",
        "moneyflow_ths",
        "moneyflow",
    }:
        raise MoneyflowContractError("daily_update_dataset")


def update_daily_moneyflow_raw(
    *,
    instance,
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

    def check_budget():
        check_cancel()
        assert_moneyflow_memory_budget()
        if perf_counter() - started >= MONEYFLOW_MAX_ELAPSED_SECONDS:
            raise MoneyflowContractError("request_budget_exceeded")

    with moneyflow_writer_lock(namespace):
        check_cancel()
        ths = dataset == "moneyflow_ths"
        deadline = started + MONEYFLOW_MAX_ELAPSED_SECONDS
        if ths:
            try:
                expected, suspended = load_moneyflow_ths_universe(
                    instance, lake_root, trade_date, deadline=deadline
                )
            except MoneyflowContractError:
                check_budget()
                raise
            check_budget()
        receipt_path = directory / "receipt.json"
        if not receipt_path.exists():
            build_daily_moneyflow_raw_candidate(
                tushare=tushare,
                dataset=dataset,
                staging_root=staging_root,
                operation_id=operation_id,
                trade_date=trade_date,
                check_cancel=check_cancel,
                raw_deadline=started + MONEYFLOW_MAX_ELAPSED_SECONDS,
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
        proof_file = raw if ths or raw.exists() else target
        checkpoint = directory / "promotion-raw.json"
        if (ths or not checkpoint.exists()) and (
            not raw.exists() or candidate_file_hash(raw) != receipt.get("raw_sha256")
        ):
            raise MoneyflowContractError("raw_source_proof")
        with (
            moneyflow_ths_raw_connection(directory, deadline, check_budget)
            if ths else moneyflow_candidate_connection(directory)
        ) as connection:
            verification = directory / "verification.parquet"
            assert_moneyflow_update_path(verification)
            if not verification.is_file() or candidate_file_hash(
                verification
            ) != receipt.get("verification_sha256"):
                raise MoneyflowContractError("raw_source_proof")
            if ths:
                for path in (raw, verification):
                    assert_moneyflow_ths_file_budget(path)
                if target.exists():
                    assert_moneyflow_ths_file_budget(target)
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
            final_metadata = {}
            candidate = raw
            if ths:
                check_budget()
                assert_moneyflow_ths_source_coverage(
                    connection, raw, expected, suspended
                )
                check_budget()
                candidate = directory / "raw-merged.parquet"
                assert_moneyflow_update_path(candidate)
                if checkpoint.exists():
                    published = read_moneyflow_update_control(checkpoint)
                    final = (
                        target if target.is_file()
                        and candidate_file_hash(target) == published.get("published_sha256")
                        else candidate
                    )
                else:
                    merge_moneyflow_ths_raw_candidate(connection, raw, target, candidate)
                    final = candidate
                check_budget()
                assert_moneyflow_ths_file_budget(final)
                final_metadata = moneyflow_ths_raw_metadata(connection, final, expected)
                check_budget()
            else:
                try:
                    baseline = moneyflow_row_count_baseline(
                        instance=instance,
                        connection=connection,
                        lake_root=lake_root,
                        dataset=dataset,
                        trade_date=trade_date,
                        check=check_budget,
                    )
                    decision = moneyflow_row_count_decision(
                        baseline, receipt["scope_row_counts"]
                    )
                except MoneyflowContractError as error:
                    receipt["row_count_guard"] = {
                        "passed": False,
                        "reason_code": str(error),
                    }
                    write_moneyflow_receipt(directory, receipt)
                    raise
                receipt["row_count_guard"] = decision
                write_moneyflow_receipt(directory, receipt)
                if not decision["passed"]:
                    raise MoneyflowContractError(
                        "row_count_drop:" + ",".join(decision["declined_scopes"])
                    )
            assert_moneyflow_memory_budget()
            if (perf_counter() - started) >= MONEYFLOW_MAX_ELAPSED_SECONDS:
                raise MoneyflowContractError("request_budget_exceeded")
            state = publish_moneyflow_update_file(
                connection,
                candidate,
                target,
                dataset=dataset,
                audit_file=audit_file,
                day=trade_date,
                layer="raw",
                checkpoint=checkpoint,
                check_cancel=check_budget if ths else check_cancel,
            )
            if ths:
                check_budget()
        return {
            **receipt,
            **final_metadata,
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
