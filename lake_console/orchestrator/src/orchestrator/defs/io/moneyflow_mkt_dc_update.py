"""Market moneyflow daily publication from proven candidates, one file at a time."""

import json
import os
import shutil
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
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    raw_moneyflow_path,
    silver_moneyflow_path,
)
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_HISTORY_MIN_FREE_BYTES,
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


def _safe_path(path: Path) -> None:
    if (
        not path.is_absolute()
        or ".." in path.parts
        or any(p.is_symlink() for p in (path, *path.parents))
    ):
        raise MoneyflowContractError("update_path")


def _roots(lake_root: Path, staging_root: Path) -> None:
    for path in (lake_root, staging_root):
        _safe_path(path)
        if not path.is_dir() or not os.access(path, os.R_OK | os.W_OK | os.X_OK):
            raise MoneyflowContractError("update_root_unavailable")
    if (
        lake_root == staging_root
        or lake_root in staging_root.parents
        or staging_root in lake_root.parents
    ):
        raise MoneyflowContractError("update_root_overlap")
    if any(Path("/Volumes") in p.parents for p in (lake_root, staging_root)):
        if lake_root != Path(DEFAULT_LAKE_ROOT) or staging_root != Path(
            DEFAULT_LAKE_STAGING_ROOT
        ):
            raise MoneyflowContractError("update_volume_root")
        if not lake_root.parent.is_mount():
            raise MoneyflowContractError("update_mount")
    if lake_root.stat().st_dev != staging_root.stat().st_dev:
        raise MoneyflowContractError("update_device")
    if shutil.disk_usage(staging_root).free < MONEYFLOW_HISTORY_MIN_FREE_BYTES:
        raise MoneyflowContractError("update_free_space")


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _checkpoint(path: Path, value: dict) -> None:
    _safe_path(path)
    temporary = path.with_suffix(".json.tmp")
    _safe_path(temporary)
    with temporary.open("w") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _read_control(path: Path) -> dict:
    _safe_path(path)
    if not path.is_file() or path.stat().st_size > 64 * 1024:
        raise MoneyflowContractError("update_control")
    try:
        value = json.loads(path.read_text())
    except (ValueError, UnicodeError) as error:
        raise MoneyflowContractError("update_control") from error
    if not isinstance(value, dict):
        raise MoneyflowContractError("update_control")
    return value


def _publish(
    connection,
    candidate: Path,
    target: Path,
    *,
    day: str,
    layer: str,
    checkpoint: Path,
    raw_hash: str | None = None,
    check_cancel=lambda: None,
) -> dict:
    """Persist intent before replace; recover a moved file without recreating it."""
    _safe_path(candidate)
    _safe_path(target)
    identity = {
        "revision": "moneyflow_mkt_dc_daily_v1",
        "layer": layer,
        "trade_date": day,
        "candidate": str(candidate),
        "target": str(target),
        "raw_sha256": raw_hash,
    }
    silver = layer == "silver"
    if checkpoint.exists():
        state = _read_control(checkpoint)
        if any(state.get(k) != v for k, v in identity.items()) or state.get(
            "stage"
        ) not in {"intent", "complete"}:
            raise MoneyflowContractError("update_intent")
    else:
        audit_market_moneyflow_file(connection, candidate, day, silver=silver)
        new_hash = candidate_file_hash(candidate)
        old_hash = None
        unchanged = False
        if target.exists():
            audit_market_moneyflow_file(connection, target, day, silver=silver)
            old_hash = candidate_file_hash(target)
            unchanged = (
                connection.execute(
                    "SELECT count(*) FROM ((SELECT * FROM read_parquet($a,hive_partitioning=false) EXCEPT "
                    "SELECT * FROM read_parquet($b,hive_partitioning=false)) UNION ALL "
                    "(SELECT * FROM read_parquet($b,hive_partitioning=false) EXCEPT "
                    "SELECT * FROM read_parquet($a,hive_partitioning=false)))",
                    {"a": str(candidate), "b": str(target)},
                ).fetchone()[0]
                == 0
            )
        state = {
            **identity,
            "candidate_sha256": new_hash,
            "prior_sha256": old_hash,
            "published_sha256": old_hash if unchanged else new_hash,
            "mode": "reuse" if unchanged else "replace",
            "stage": "intent",
        }
        _checkpoint(checkpoint, state)
    check_cancel()
    actual = candidate_file_hash(target) if target.is_file() else None
    if actual != state["published_sha256"]:
        if (
            state["stage"] == "complete"
            or state["mode"] != "replace"
            or actual != state["prior_sha256"]
        ):
            raise MoneyflowContractError("update_target_changed")
        if (
            not candidate.is_file()
            or candidate_file_hash(candidate) != state["candidate_sha256"]
        ):
            raise MoneyflowContractError("update_candidate_changed")
        audit_market_moneyflow_file(connection, candidate, day, silver=silver)
        target.parent.mkdir(parents=True, exist_ok=True)
        _safe_path(target)
        if candidate.stat().st_dev != target.parent.stat().st_dev:
            raise MoneyflowContractError("update_device")
        check_cancel()
        # Recheck immediately before replacing. The namespace lock serializes writers.
        if (candidate_file_hash(target) if target.is_file() else None) != state[
            "prior_sha256"
        ]:
            raise MoneyflowContractError("update_target_changed")
        with candidate.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(candidate, target)
        _fsync_directory(target.parent)
    audit_market_moneyflow_file(connection, target, day, silver=silver)
    if candidate_file_hash(target) != state["published_sha256"]:
        raise MoneyflowContractError("update_readback")
    if state["stage"] != "complete":
        state = {**state, "stage": "complete"}
        _checkpoint(checkpoint, state)
    return state


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
    _roots(lake_root, staging_root)
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
        receipt = _read_control(receipt_path)
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
        _safe_path(target)
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
            state = _publish(
                connection,
                raw,
                target,
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
    _roots(lake_root, staging_root)
    namespace = staging_root / "moneyflow"
    namespace.mkdir(exist_ok=True)
    with moneyflow_writer_lock(namespace):
        check_cancel()
        raw = raw_moneyflow_path(lake_root, DATASET, trade_date)
        _safe_path(raw)
        if not raw.is_file() or candidate_file_hash(raw) != expected_raw_hash:
            raise MoneyflowContractError("raw_materialization_file_changed")
        directory.mkdir(parents=True, exist_ok=True)
        candidate = directory / "silver.parquet"
        target = silver_moneyflow_path(lake_root, DATASET, trade_date)
        _safe_path(candidate)
        _safe_path(target)
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
            state = _publish(
                connection,
                candidate,
                target,
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
