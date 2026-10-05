"""Durable, bounded primary month delivery; Raw values never come from daily bars."""

import os
import re
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

from orchestrator.defs.bootstrap.stock_monthly_files import (
    check_monthly_cancel,
    check_monthly_free_space,
    check_monthly_path,
    check_monthly_root,
    monthly_file_hash,
    monthly_file_lock,
    read_monthly_json,
    sync_monthly_directory,
    sync_monthly_file,
    write_monthly_json,
)
from orchestrator.defs.bootstrap.stock_weekly_capture import WeeklyCaptureError
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.io.stock_monthly_raw import (
    canonical_month_hashes,
    load_monthly_csv,
    load_monthly_parquets,
    validate_month_relation,
)
from orchestrator.defs.paths import DEFAULT_LAKE_STAGING_ROOT, raw_stock_monthly_path
from orchestrator.defs.run_contracts.stock_monthly import (
    MONTHLY_UPDATE_POLICY,
    MonthlyBootstrapIOPolicy,
    MonthlyProdUnit,
    StockMonthlyPolicy,
    StockMonthlySource,
    month_window,
    monthly_column_specs,
    monthly_contract_hash,
    monthly_point_request,
    monthly_source_api,
)
from orchestrator.defs.source_readiness.stock_monthly import (
    assert_month_references_unchanged,
    freeze_month_references,
    verify_month_completion,
)
from orchestrator.defs.stock_monthly_update import monthly_update_intent
from orchestrator.defs.stock_weekly_source import (
    copy_source_diagnostic,
    fetch_weekly_request_supervised,
)


@dataclass(frozen=True)
class StockMonthlyPointWorker:
    token: str = field(repr=False)
    source: StockMonthlySource

    def __call__(self, params, fields, max_rows):
        from orchestrator.defs.resources import TushareResource

        result = TushareResource(token=self.token).call(
            monthly_source_api(self.source), params, fields
        )
        return pd.DataFrame(result.rows, columns=result.columns, dtype=object)


def monthly_connection(directory, *, readonly=False):
    io = MonthlyBootstrapIOPolicy()
    settings = DuckDBConnectionSettings(
        temp_directory=directory,
        memory_limit=f"{io.duckdb_memory_mb}MB",
        threads=io.duckdb_threads,
        max_temp_directory_size=f"{io.duckdb_temp_mb}MB",
    )
    return connect_configured_duckdb(
        settings, temp_policy="existing_no_spill" if readonly else "managed"
    )


def _write(path, payload):
    write_monthly_json(path, payload, MonthlyBootstrapIOPolicy().control_max_bytes)


def _read(path):
    return read_monthly_json(path, MonthlyBootstrapIOPolicy().control_max_bytes)


def _hash(path, *, max_bytes=None):
    return monthly_file_hash(
        path,
        max_bytes=max_bytes
        if max_bytes is not None
        else MonthlyBootstrapIOPolicy().prod_csv_max_bytes,
    )


def _fingerprint(path):
    return _hash(path) if path.exists() else None


def _page_unit(source, month, frame, policy):
    first, upper = month_window(month)
    codes = tuple(sorted(set(frame["ts_code"]))) or ("000001.SZ",)
    return MonthlyProdUnit(
        monthly_contract_hash({"source": source.value, "month": month, "codes": codes}),
        source,
        codes,
        first.isoformat(),
        upper.isoformat(),
        policy.page_limit,
    )


def _validate_page(connection, csv_path, source, month, policy, rows, codes):
    first, upper = month_window(month)
    if (
        not codes
        or len(codes) > policy.max_codes
        or any(
            not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", code)
            for code in codes
        )
        or tuple(codes) != tuple(sorted(set(codes)))
    ):
        raise ValueError("monthly_receipt_codes_invalid")
    unit = MonthlyProdUnit(
        monthly_contract_hash({"month": month, "codes": codes}),
        source,
        tuple(codes),
        first.isoformat(),
        upper.isoformat(),
        policy.page_limit,
    )
    load_monthly_csv(connection, csv_path, unit, policy, rows)
    # Bootstrap allows the explicitly excluded version; point delivery never does.
    validate_month_relation(
        connection, "monthly_capture", source, policy, max_rows=policy.page_limit
    )
    observed = canonical_month_hashes(connection, "monthly_capture", source)
    if observed and set(observed) != {month}:
        raise ValueError("monthly_source_coordinate_mismatch")


def _read_page(connection, path, source, month, index, policy):
    receipt = _read(path)
    csv_path, parquet = path.parent / "source.csv", path.parent / "capture.parquet"
    if (
        receipt["source"] != source.value
        or receipt["month"] != month
        or receipt["params"] != monthly_point_request(month, index, policy)
        or receipt["fields"] != [n for n, _ in monthly_column_specs(source)]
        or not 0 <= receipt["rows"] <= policy.page_limit
        or receipt["csv_hash"] != _hash(csv_path)
        or receipt["parquet_hash"] != _hash(parquet)
    ):
        raise ValueError("monthly_page_receipt_changed")
    _validate_page(
        connection, csv_path, source, month, policy, receipt["rows"], receipt["codes"]
    )
    if (
        connection.execute(
            "SELECT count(*) FROM (SELECT 1 FROM read_parquet(?,hive_partitioning=false) LIMIT ?)",
            [str(parquet), policy.page_limit + 1],
        ).fetchone()[0]
        != receipt["rows"]
    ):
        raise ValueError("monthly_page_parquet_row_budget_invalid")
    load_monthly_parquets(connection, "monthly_candidate", [parquet], source)
    if connection.execute(
        "SELECT count(*) FROM ((SELECT * FROM monthly_capture EXCEPT ALL SELECT * FROM monthly_candidate) UNION ALL (SELECT * FROM monthly_candidate EXCEPT ALL SELECT * FROM monthly_capture))"
    ).fetchone()[0]:
        raise ValueError("monthly_page_values_changed")
    return receipt, parquet


def _verify_source_proof(connection, proof, directory, source, month):
    policy = StockMonthlyPolicy(**proof["policy"])
    if policy.max_pages > 4 or policy.max_retries > 2 or policy.max_update_rows > 10000:
        raise ValueError("monthly_proof_budget_exceeded")
    if (
        monthly_contract_hash({k: v for k, v in proof.items() if k != "proof_hash"})
        != proof["proof_hash"]
        or _hash(directory / "intent.json") != proof["intent_hash"]
    ):
        raise ValueError("monthly_proof_identity_changed")
    page_files, total, previous = [], 0, None
    pages = proof["pages"]
    if not pages or len(pages) > policy.max_pages:
        raise ValueError("monthly_proof_page_budget_invalid")
    for index, item in enumerate(pages):
        path = directory / f"page-{index}" / "receipt.json"
        if item["path"] != str(path) or item["sha256"] != _hash(path):
            raise ValueError("monthly_page_evidence_changed")
        if previous is not None and previous < policy.page_limit:
            raise ValueError("monthly_page_after_closed_tail")
        receipt, parquet = _read_page(connection, path, source, month, index, policy)
        previous = receipt["rows"]
        total += previous
        page_files.append(parquet)
    if previous == policy.page_limit or total == 0 or total > policy.max_update_rows:
        raise ValueError("monthly_page_cap_or_empty")
    load_monthly_parquets(connection, "monthly_capture", page_files, source)
    validate_month_relation(
        connection, "monthly_capture", source, policy, max_rows=policy.max_update_rows
    )
    hashes = canonical_month_hashes(connection, "monthly_capture", source)
    if (
        hashes
        != {month: {"rows": proof["rows"], "logical_hash": proof["logical_hash"]}}
        or total != proof["source_rows"]
    ):
        raise ValueError("monthly_source_reconciliation_failed")
    if proof["ledger_hash"] != _hash(directory / "requests.json"):
        raise ValueError("monthly_request_ledger_changed")
    ledger = _read(directory / "requests.json")
    if (
        ledger["calls"] != proof["requests"]
        or ledger["calls"] != sum(ledger["attempts"].values())
        or ledger["calls"] > policy.max_pages * (policy.max_retries + 1)
        or any(
            type(n) is not int or not 1 <= n <= policy.max_retries + 1
            for n in ledger["attempts"].values()
        )
    ):
        raise ValueError("monthly_request_ledger_invalid")
    reference_path = directory / "reference.json"
    if proof["reference_hash"] != _hash(reference_path):
        raise ValueError("monthly_reference_proof_changed")
    reference = _read(reference_path)
    if (
        reference["month"] != month
        or verify_month_completion(connection, reference) != proof["completion"]
    ):
        raise ValueError("monthly_completion_proof_invalid")
    return reference


def read_month_delivery(delivery, root, source, month, *, connection=None):
    """Local proof audit, no source requests; bounded to one month's captured pages."""
    source = StockMonthlySource(source)
    if delivery.get("delivery_method") == "prod_month_bootstrap":
        from orchestrator.defs.bootstrap.stock_monthly_delivery import (
            read_month_bootstrap_delivery,
        )

        return read_month_bootstrap_delivery(
            delivery, root, source, month, connection=connection
        )
    path = Path(delivery["proof_path"])
    check_monthly_path(path)
    allowed = (
        Path(DEFAULT_LAKE_STAGING_ROOT),
        Path("/private/tmp"),
        Path(tempfile.gettempdir()).resolve(),
    )
    if not any(path.is_relative_to(p) for p in allowed) or path.name != "delivery.json":
        raise ValueError("monthly_delivery_path_forbidden")
    proof = _read(path)
    unsigned = {k: v for k, v in proof.items() if k != "proof_hash"}
    target = raw_stock_monthly_path(root, source, month)
    if (
        monthly_contract_hash(unsigned) != proof["proof_hash"]
        or proof["proof_hash"] != delivery["proof_hash"]
        or proof["source"] != source.value
        or proof["month"] != month
        or proof["target"] != str(target)
        or proof["method"] != "tushare_month_point"
        or proof["schema_hash"] != monthly_contract_hash(monthly_column_specs(source))
        or delivery["rows"] != proof["rows"]
        or _fingerprint(target) != proof["target_hash"]
    ):
        raise ValueError("monthly_delivery_identity_changed")
    if connection is not None:
        _verify_source_proof(connection, proof, path.parent, source, month)
        load_monthly_parquets(connection, "monthly_candidate", [target], source)
        validate_month_relation(
            connection,
            "monthly_candidate",
            source,
            StockMonthlyPolicy(),
            max_rows=StockMonthlyPolicy().max_update_rows,
        )
        if canonical_month_hashes(connection, "monthly_candidate", source) != {
            month: {"rows": proof["rows"], "logical_hash": proof["logical_hash"]}
        }:
            raise ValueError("monthly_formal_values_changed")
    return proof


def _delivery(proof, path):
    return {
        "path": proof["target"],
        "rows": proof["rows"],
        "source_rows": proof["source_rows"],
        "proof_path": str(path),
        "proof_hash": proof["proof_hash"],
        "source": proof["source"],
        "month": proof["month"],
        "requests": proof["requests"],
        "delivery_method": proof["method"],
    }


def deliver_month_intent(
    source,
    month,
    *,
    target_root,
    staging_root,
    worker,
    execution_id,
    upstream_bindings,
    automatic_intent_date=None,
    cancel=lambda: False,
    progress=lambda payload: None,
    fetch=fetch_weekly_request_supervised,
    policy=None,
):
    source = StockMonthlySource(source)
    policy = policy or StockMonthlyPolicy()
    if (
        policy.max_pages > 4
        or policy.max_retries > 2
        or policy.max_update_rows > 10000
        or policy.max_codes > 10000
    ):
        raise ValueError("monthly_update_budget_exceeded")
    io = MonthlyBootstrapIOPolicy()
    check_monthly_root(target_root, staging=False)
    check_monthly_root(staging_root, staging=True)
    if (
        target_root == staging_root
        or target_root.is_relative_to(staging_root)
        or staging_root.is_relative_to(target_root)
    ):
        raise ValueError("monthly_roots_overlap")
    if not execution_id or len(execution_id) > 128:
        raise ValueError("monthly_execution_identity_invalid")
    intent = {
        "source": source.value,
        "month": month,
        "policy": asdict(policy),
        "io_policy": asdict(io),
        "update_policy": asdict(MONTHLY_UPDATE_POLICY),
        "schema_hash": monthly_contract_hash(monthly_column_specs(source)),
        "execution_id": execution_id,
        "target_root": str(target_root),
    }
    if automatic_intent_date is not None:
        intent["automatic"] = monthly_update_intent(
            source, month, automatic_intent_date
        )
        intent["execution_id"] = intent["automatic"]["unit_id"]
    target = raw_stock_monthly_path(target_root, source, month)
    directory = (
        staging_root / "stock_monthly_raw" / "updates" / monthly_contract_hash(intent)
    )
    check_monthly_path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    lock_dir = staging_root / "stock_monthly_raw" / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    # Execution lock serializes downloads; target lock is shared with bootstrap.
    with (
        monthly_file_lock(directory.parent / "writer.lock"),
        monthly_file_lock(directory / "execution.lock"),
    ):
        return _deliver(
            source,
            month,
            target,
            directory,
            lock_dir,
            intent,
            worker,
            upstream_bindings,
            policy,
            cancel,
            progress,
            fetch,
        )


def _deliver(
    source,
    month,
    target,
    directory,
    lock_dir,
    intent,
    worker,
    upstream_bindings,
    policy,
    cancel,
    progress,
    fetch,
):
    io = MonthlyBootstrapIOPolicy()
    check_monthly_free_space(
        directory,
        io.duckdb_temp_mb * 1024**2 + 2 * io.prod_csv_max_bytes + io.control_max_bytes,
    )
    intent_path = directory / "intent.json"
    if intent_path.exists():
        if _read(intent_path) != intent:
            raise ValueError("monthly_intent_changed")
    else:
        _write(intent_path, intent)
    proof_path = directory / "delivery.json"
    if proof_path.exists():
        proof = _read(proof_path)
        if (
            proof["source"] != source.value
            or proof["month"] != month
            or proof["target"] != str(target)
        ):
            raise ValueError("monthly_proof_identity_changed")
        delivery = _delivery(proof, proof_path)
        with monthly_connection(directory / "spill") as connection:
            if _fingerprint(target) == proof["target_hash"]:
                read_month_delivery(
                    delivery,
                    Path(intent["target_root"]),
                    source,
                    month,
                    connection=connection,
                )
                return delivery
            reference = _verify_source_proof(
                connection, proof, directory, source, month
            )
            candidate = directory / "candidate.parquet"
            if _hash(candidate) != proof["candidate_hash"]:
                raise ValueError("monthly_candidate_changed")
            _promote(
                proof,
                proof_path,
                target,
                candidate,
                reference,
                upstream_bindings,
                lock_dir,
                cancel,
            )
        return delivery
    baseline_path = directory / "baseline.json"
    if not baseline_path.exists():
        _write(baseline_path, {"sha256": _fingerprint(target)})
    baseline = _read(baseline_path)["sha256"]
    with monthly_connection(directory / "spill") as connection:
        connection.execute("SET autoinstall_known_extensions=false")
        connection.execute("SET autoload_known_extensions=false")
        reference_path = directory / "reference.json"
        if reference_path.exists():
            reference = _read(reference_path)
            assert_month_references_unchanged(reference["references"])
            if (
                reference["month"] != month
                or upstream_bindings(reference["open_dates"]) != reference["bindings"]
            ):
                raise ValueError("monthly_upstream_events_changed")
        else:
            reference = freeze_month_references(
                connection,
                Path(intent["target_root"]),
                month,
                upstream_bindings=upstream_bindings,
            )
            _write(reference_path, reference)
        ledger_path = directory / "requests.json"
        ledger = (
            _read(ledger_path)
            if ledger_path.exists()
            else {"calls": 0, "attempts": {}, "next_request_at": 0}
        )
        paths, pages, total = [], [], 0
        for index in range(policy.max_pages):
            check_monthly_cancel(cancel)
            page_dir = directory / f"page-{index}"
            page_dir.mkdir(exist_ok=True)
            receipt_path = page_dir / "receipt.json"
            if not receipt_path.exists():
                params = monthly_point_request(month, index, policy)
                attempts = ledger["attempts"].get(str(index), 0)
                last_source_error = None
                while True:
                    check_monthly_cancel(cancel)
                    if attempts >= policy.max_retries + 1 or ledger[
                        "calls"
                    ] >= policy.max_pages * (policy.max_retries + 1):
                        raise copy_source_diagnostic(
                            last_source_error,
                            ValueError("monthly_request_budget_exhausted"),
                        ) from None
                    while time.time() < ledger["next_request_at"]:
                        check_monthly_cancel(cancel)
                        time.sleep(0.05)
                    attempts += 1
                    ledger["calls"] += 1
                    ledger["attempts"][str(index)] = attempts
                    ledger["next_request_at"] = (
                        time.time()
                        + MONTHLY_UPDATE_POLICY.call_timeout_seconds
                        + MONTHLY_UPDATE_POLICY.minimum_interval_seconds
                    )
                    _write(ledger_path, ledger)
                    payload = {
                        "stage": "requesting",
                        "month": month,
                        "source": source.value,
                        "page": index,
                        "request": ledger["calls"],
                        "captured_rows": total,
                        "eta": "暂无法估算",
                    }
                    progress(payload)
                    last_emit = [time.monotonic()]

                    def heartbeat(last_emit=last_emit, payload=payload):
                        if time.monotonic() - last_emit[0] >= 10:
                            progress(payload)
                            last_emit[0] = time.monotonic()

                    try:
                        frame = fetch(
                            worker,
                            params,
                            tuple(n for n, _ in monthly_column_specs(source)),
                            policy.page_limit,
                            MONTHLY_UPDATE_POLICY,
                            cancel,
                            heartbeat,
                        )
                        break
                    except WeeklyCaptureError as error:
                        last_source_error = error
                        if str(error) not in ("source_failed", "source_timeout"):
                            raise copy_source_diagnostic(
                                error, ValueError("monthly_" + str(error))
                            ) from None
                    finally:
                        ledger["next_request_at"] = (
                            time.time() + MONTHLY_UPDATE_POLICY.minimum_interval_seconds
                        )
                        _write(ledger_path, ledger)
                check_monthly_cancel(cancel)
                if (
                    not isinstance(frame, pd.DataFrame)
                    or tuple(frame.columns)
                    != tuple(n for n, _ in monthly_column_specs(source))
                    or len(frame) > policy.page_limit
                ):
                    raise ValueError("monthly_source_schema_or_row_budget_invalid")
                unit = _page_unit(source, month, frame, policy)
                csv_path = page_dir / "source.csv"
                frame.to_csv(csv_path, index=False, na_rep=r"\N")
                sync_monthly_file(csv_path)
                _hash(csv_path, max_bytes=io.prod_csv_max_bytes)
                _validate_page(
                    connection,
                    csv_path,
                    source,
                    month,
                    policy,
                    len(frame),
                    unit.sorted_codes,
                )
                parquet = page_dir / "capture.parquet"
                connection.execute(
                    "COPY (SELECT * FROM monthly_capture ORDER BY ts_code,trade_date,freq) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
                    [str(parquet)],
                )
                sync_monthly_file(parquet)
                _write(
                    receipt_path,
                    {
                        "source": source.value,
                        "month": month,
                        "params": params,
                        "fields": list(frame.columns),
                        "codes": list(unit.sorted_codes),
                        "rows": len(frame),
                        "csv_hash": _hash(csv_path),
                        "parquet_hash": _hash(parquet),
                    },
                )
            receipt, parquet = _read_page(
                connection, receipt_path, source, month, index, policy
            )
            total += receipt["rows"]
            if total > policy.max_update_rows:
                raise ValueError("monthly_update_row_budget_exceeded")
            paths.append(parquet)
            pages.append({"path": str(receipt_path), "sha256": _hash(receipt_path)})
            progress(
                {
                    "stage": "captured",
                    "month": month,
                    "page": index,
                    "captured_rows": total,
                }
            )
            if receipt["rows"] < policy.page_limit:
                break
        else:
            raise ValueError("monthly_page_cap_exceeded")
        if not total:
            raise ValueError("monthly_source_not_ready")
        load_monthly_parquets(connection, "monthly_capture", paths, source)
        validate_month_relation(
            connection,
            "monthly_capture",
            source,
            policy,
            max_rows=policy.max_update_rows,
        )
        completion = verify_month_completion(connection, reference)
        hashes = canonical_month_hashes(connection, "monthly_capture", source)
        if set(hashes) != {month}:
            raise ValueError("monthly_partition_mismatch")
        if baseline is not None:
            load_monthly_parquets(connection, "monthly_candidate", [target], source)
            validate_month_relation(
                connection,
                "monthly_candidate",
                source,
                policy,
                max_rows=policy.max_update_rows,
            )
            if (
                canonical_month_hashes(connection, "monthly_candidate", source)
                != hashes
            ):
                _write(
                    directory / "revision_required.json",
                    {
                        "reason_code": "revision_required",
                        "source": source.value,
                        "month": month,
                        "automatic_overwrite": False,
                        "next_action": "审阅本月全字段差异，再另行批准修订；不要启用备用源自动覆盖。",
                    },
                )
                raise ValueError("revision_required")
        candidate = directory / "candidate.parquet"
        connection.execute(
            "COPY (SELECT * FROM monthly_capture ORDER BY ts_code,trade_date,freq) TO ? (FORMAT PARQUET,COMPRESSION ZSTD)",
            [str(candidate)],
        )
        sync_monthly_file(candidate)
        load_monthly_parquets(connection, "monthly_candidate", [candidate], source)
        if connection.execute(
            "SELECT count(*) FROM ((SELECT * FROM monthly_capture EXCEPT ALL SELECT * FROM monthly_candidate) UNION ALL (SELECT * FROM monthly_candidate EXCEPT ALL SELECT * FROM monthly_capture))"
        ).fetchone()[0]:
            raise ValueError("monthly_candidate_values_changed")
        proof = {
            "method": "tushare_month_point",
            "source": source.value,
            "month": month,
            "target": str(target),
            "baseline": baseline,
            "candidate_hash": _hash(candidate),
            "target_hash": baseline or _hash(candidate),
            "rows": total,
            "source_rows": total,
            "logical_hash": hashes[month]["logical_hash"],
            "schema_hash": monthly_contract_hash(monthly_column_specs(source)),
            "policy": asdict(policy),
            "pages": pages,
            "reference_hash": _hash(reference_path),
            "completion": completion,
            "intent_hash": _hash(intent_path),
            "requests": ledger["calls"],
            "ledger_hash": _hash(ledger_path),
        }
        proof["proof_hash"] = monthly_contract_hash(proof)
        _write(proof_path, proof)
        _verify_source_proof(connection, proof, directory, source, month)
        _promote(
            proof,
            proof_path,
            target,
            candidate,
            reference,
            upstream_bindings,
            lock_dir,
            cancel,
        )
    progress({"stage": "promoted", "month": month, "rows": total, "completed_files": 1})
    return _delivery(proof, proof_path)


def _promote(
    proof, proof_path, target, candidate, reference, upstream_bindings, lock_dir, cancel
):
    check_monthly_cancel(cancel)
    assert_month_references_unchanged(reference["references"])
    if upstream_bindings(reference["open_dates"]) != reference["bindings"]:
        raise ValueError("monthly_upstream_events_changed")
    lock = lock_dir / f"{proof['source']}-{proof['month']}.lock"
    with monthly_file_lock(lock):
        check_monthly_cancel(cancel)
        current = _fingerprint(target)
        if current == proof["target_hash"]:
            return
        if current != proof["baseline"]:
            raise ValueError("monthly_target_changed")
        check_monthly_path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        check_monthly_free_space(
            target.parent, MonthlyBootstrapIOPolicy().control_max_bytes + 4096
        )
        if candidate.stat().st_dev != target.parent.stat().st_dev:
            raise ValueError("monthly_cross_device_promotion")
        if _hash(candidate) != proof["candidate_hash"]:
            raise ValueError("monthly_candidate_changed")
        os.replace(candidate, target)
        sync_monthly_directory(target.parent)
        # Observation/checkpoint failure must not undo the committed business file.
        _write(
            proof_path.parent / "promoted.json",
            {"target": str(target), "sha256": proof["target_hash"]},
        )
