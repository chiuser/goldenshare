"""Recoverable, explicit market-history registration; native events are truth."""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

import dagster as dg
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation,
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.bootstrap.moneyflow_history_candidates import _read_json
from orchestrator.defs.bootstrap.moneyflow_history_cohort import _large_json
from orchestrator.defs.bootstrap.moneyflow_history_plan import history_schema
from orchestrator.defs.bootstrap.moneyflow_history_promote import _check_path
from orchestrator.defs.bootstrap.moneyflow_mkt_dc_event_plan import (
    market_moneyflow_instance_identity,
    validate_market_moneyflow_event_plan,
)
from orchestrator.defs.bootstrap.moneyflow_mkt_dc_event_preview import (
    read_market_moneyflow_event_state,
)
from orchestrator.defs.checks.moneyflow import audit_market_moneyflow_standardization
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.io.moneyflow_candidates import (
    candidate_file_hash,
    moneyflow_writer_lock,
)
from orchestrator.defs.partitions import cn_a_moneyflow_mkt_dc_trade_days
from orchestrator.defs.paths import raw_moneyflow_path, silver_moneyflow_path
from orchestrator.defs.run_contracts.metadata import (
    CheckScope,
    build_check_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_DUCKDB_MEMORY_LIMIT,
    MONEYFLOW_DUCKDB_THREADS,
    MONEYFLOW_EVENT_DATE_BATCH,
    MONEYFLOW_EVENT_MAX_METADATA_READS,
    MONEYFLOW_EVENT_MAX_SECONDS,
    MONEYFLOW_HISTORY_MAX_BUFFER_BYTES,
    MONEYFLOW_HISTORY_SQL_TIMEOUT_SECONDS,
    MONEYFLOW_MKT_DC_RAW_CHECK,
    MONEYFLOW_MKT_DC_SILVER_CHECK,
    MoneyflowContractError,
    assert_moneyflow_memory_budget,
)

ACTIVE = [
    dg.DagsterRunStatus.QUEUED,
    dg.DagsterRunStatus.NOT_STARTED,
    dg.DagsterRunStatus.STARTING,
    dg.DagsterRunStatus.STARTED,
    dg.DagsterRunStatus.CANCELING,
]
LOGGER = logging.getLogger(__name__)


def _atomic_json(path, payload, *, limit=256 * 1024):
    _check_path(path)
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode()
    if len(encoded) > limit:
        raise MoneyflowContractError("history_event_checkpoint_budget")
    partial = path.with_name(path.name + ".partial")
    _check_path(partial)
    descriptor = os.open(
        partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(partial, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _path(plan, entry, layer):
    path = (raw_moneyflow_path if layer == "raw" else silver_moneyflow_path)(
        Path(plan["lake_root"]), "moneyflow_mkt_dc", entry["day"]
    )
    _check_path(path)
    if not path.is_file() or candidate_file_hash(path) != entry[layer + "_sha256"]:
        raise MoneyflowContractError("history_formal_changed")
    checkpoint = Path(entry["checkpoint"]["path"])
    _check_path(checkpoint)
    if candidate_file_hash(checkpoint) != entry["checkpoint"]["sha256"]:
        raise MoneyflowContractError("history_event_controls_changed")
    return path


def _materialization(plan, entry, layer, path):
    extra = {
        "file_sha256": entry[layer + "_sha256"],
        "cohort_hash": plan["cohort_hash"],
        "history_checkpoint_sha256": entry["checkpoint"]["sha256"],
        "event_plan_hash": plan["plan_hash"],
        "bootstrap_cutoff": plan["cutoff"],
        "source_row_count": 1,
        "rejected_row_count": 0,
    }
    if layer == "silver":
        extra["raw_sha256"] = entry["raw_sha256"]
    return dg.AssetMaterialization(
        asset_key="raw_tushare_moneyflow_mkt_dc"
        if layer == "raw"
        else "silver_moneyflow_mkt_dc",
        partition=entry["day"],
        metadata=build_materialization_metadata(
            uri=path,
            row_count=1,
            observed_columns=tuple(
                c.name
                for c in history_schema("moneyflow_mkt_dc", silver=layer == "silver")
            ),
            extra_metadata=extra,
        ),
    )


def _evaluation(plan, entry, layer, path, mat):
    return AssetCheckEvaluation(
        asset_key=mat.asset_key,
        check_name=MONEYFLOW_MKT_DC_RAW_CHECK
        if layer == "raw"
        else MONEYFLOW_MKT_DC_SILVER_CHECK,
        passed=True,
        partition=entry["day"],
        blocking=True,
        severity=dg.AssetCheckSeverity.ERROR,
        target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
            storage_id=mat.storage_id,
            run_id=mat.event_log_entry.run_id,
            timestamp=mat.timestamp,
        ),
        metadata=build_check_metadata(
            check_scope=CheckScope.SCHEMA
            if layer == "raw"
            else CheckScope.RECONCILIATION,
            checked_row_count=1,
            failed_row_count=0,
            file_path=path,
            extra_metadata={
                "file_sha256": entry[layer + "_sha256"],
                "event_plan_hash": plan["plan_hash"],
                "partition_key": entry["day"],
            },
        ),
    )


def report_market_moneyflow_history_events(
    *, instance, plan, apply=False, cancel=lambda: False, progress=lambda _: None
):
    if type(apply) is not bool:
        raise MoneyflowContractError("history_event_apply")
    started = monotonic()
    batch_started = started
    reads = written = registered_new = completed = 0
    stage, current_day, current_layer = "preflight", None, None
    checkpoint_path = None

    def guard():
        if cancel():
            raise MoneyflowContractError("history_event_cancelled")
        if (
            monotonic() - started > MONEYFLOW_EVENT_MAX_SECONDS
            or monotonic() - batch_started > MONEYFLOW_HISTORY_SQL_TIMEOUT_SECONDS
        ):
            raise MoneyflowContractError("history_event_time_budget")
        assert_moneyflow_memory_budget()

    def before_read():
        nonlocal reads
        guard()
        if reads >= MONEYFLOW_EVENT_MAX_METADATA_READS:
            raise MoneyflowContractError("history_event_read_budget")
        reads += 1
        # A bounded native read is actual work; surface it before a potentially slow API.
        if checkpoint_path:
            notify(observe())

    def observe():
        return {
            "plan_hash": plan["plan_hash"],
            "stage": stage,
            "current_date": current_day,
            "layer": current_layer,
            "completed": completed,
            "total": plan["total_work_items"],
            "percent": round(completed * 100 / plan["total_work_items"], 2),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": monotonic() - started,
            "metadata_reads": reads,
            "written_events_this_attempt": written,
            "registered_keys_this_attempt": registered_new,
        }

    def notify(item):
        try:
            progress(item)
        except Exception:
            LOGGER.exception("资金流登记进度输出失败；已提交事件保留")

    def save():
        item = observe()
        if checkpoint_path:
            _atomic_json(checkpoint_path, item)
        notify(item)

    def active_guard():
        for job in (
            "raw_tushare_moneyflow_mkt_dc_update_job",
            "silver_moneyflow_mkt_dc_update_job",
        ):
            before_read()
            active = instance.get_runs(
                filters=dg.RunsFilter(job_name=job, statuses=ACTIVE), limit=1
            )
            guard()
            if active:
                raise MoneyflowContractError("history_event_active_run")

    def state(entries):
        result = read_market_moneyflow_event_state(
            instance, entries, plan["recent_check_dates"], before_read=before_read
        )
        guard()
        return result

    validate_market_moneyflow_event_plan(plan, instance, check=guard)
    active_guard()
    current = state(plan["entries"])
    dates = {e["day"] for e in plan["entries"]}
    completed = (
        len(dates & current["registered"])
        + len(current["mats"])
        + len(current["checks"])
    )
    if not apply:
        return {
            **observe(),
            "stage": "read_only_preview",
            "missing_partition_keys": len(dates - current["registered"]),
            "missing_materializations": 2 * len(dates) - len(current["mats"]),
            "missing_checks": 2 * len(plan["recent_check_dates"])
            - len(current["checks"]),
            "formal_writes": 0,
        }
    namespace = Path(plan["staging_root"]) / "moneyflow"
    _check_path(namespace)
    # Source cohort already exists; no namespace creation in dry-run or here.
    with moneyflow_writer_lock(namespace):
        guard()
        validate_market_moneyflow_event_plan(plan, instance, check=guard)
        directory = namespace / plan["operation_id"] / "events" / plan["plan_hash"]
        _check_path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        frozen = directory / "plan.json"
        if frozen.exists():
            if _large_json(frozen) != plan:
                raise MoneyflowContractError("history_event_plan_changed")
        else:
            _atomic_json(frozen, plan, limit=MONEYFLOW_HISTORY_MAX_BUFFER_BYTES)
        checkpoint_path = directory / "checkpoint.json"
        current = state(plan["entries"])
        completed = (
            len(dates & current["registered"])
            + len(current["mats"])
            + len(current["checks"])
        )
        if checkpoint_path.exists():
            old = _read_json(checkpoint_path)
            if (
                old.get("plan_hash") != plan["plan_hash"]
                or type(old.get("completed")) is not int
                or not 0 <= old["completed"] <= completed
                or old.get("total") != plan["total_work_items"]
                or old.get("stage")
                not in {
                    "preflight",
                    "partitions",
                    "materializations",
                    "checks",
                    "audit",
                    "complete",
                    "cancelled",
                    "interrupted",
                    "failed",
                }
            ):
                raise MoneyflowContractError("history_event_checkpoint_changed")
        try:
            # Re-read after acquiring the writer, never skip based on checkpoint.
            save()
            for phase in ("partitions", "materializations", "checks"):
                selected = (
                    plan["entries"]
                    if phase != "checks"
                    else [
                        e
                        for e in plan["entries"]
                        if e["day"] in plan["recent_check_dates"]
                    ]
                )
                for offset in range(0, len(selected), MONEYFLOW_EVENT_DATE_BATCH):
                    batch_started = monotonic()
                    batch = selected[offset : offset + MONEYFLOW_EVENT_DATE_BATCH]
                    stage = phase
                    current_day, current_layer = batch[0]["day"], None
                    guard()
                    active_guard()
                    if (
                        market_moneyflow_instance_identity(
                            instance, Path(plan["lake_root"])
                        )
                        != plan["instance_identity"]
                    ):
                        raise MoneyflowContractError("history_event_instance_changed")
                    actual = state(batch)
                    if phase == "partitions":
                        missing = [
                            e["day"]
                            for e in batch
                            if e["day"] not in actual["registered"]
                        ]
                        if missing:
                            guard()
                            instance.add_dynamic_partitions(
                                cn_a_moneyflow_mkt_dc_trade_days.name, missing
                            )
                            completed += len(missing)
                            registered_new += len(missing)
                            save()
                            guard()
                    else:
                        for entry in batch:
                            current_day = entry["day"]
                            if phase == "checks":
                                guard()
                                with connect_configured_duckdb(
                                    DuckDBConnectionSettings(
                                        temp_directory=Path("/private/tmp"),
                                        memory_limit=MONEYFLOW_DUCKDB_MEMORY_LIMIT,
                                        threads=MONEYFLOW_DUCKDB_THREADS,
                                    ),
                                    temp_policy="existing_no_spill",
                                ) as connection:
                                    audit_market_moneyflow_standardization(
                                        connection,
                                        _path(plan, entry, "raw"),
                                        _path(plan, entry, "silver"),
                                        entry["day"],
                                    )
                            for layer in ("raw", "silver"):
                                current_layer = layer
                                guard()
                                path = _path(plan, entry, layer)
                                key = (entry["day"], layer)
                                if (
                                    key
                                    in actual[
                                        "mats"
                                        if phase == "materializations"
                                        else "checks"
                                    ]
                                ):
                                    continue
                                if phase == "checks" and key not in actual["mats"]:
                                    raise MoneyflowContractError(
                                        "history_event_materialization_missing"
                                    )
                                event = (
                                    _materialization(plan, entry, layer, path)
                                    if phase == "materializations"
                                    else _evaluation(
                                        plan, entry, layer, path, actual["mats"][key]
                                    )
                                )
                                guard()
                                instance.report_runless_asset_event(event)
                                completed += 1
                                written += 1
                                save()
                                guard()
                    after = state(batch)
                    if phase == "partitions":
                        valid = {e["day"] for e in batch}.issubset(after["registered"])
                    else:
                        valid = len(
                            after["mats" if phase == "materializations" else "checks"]
                        ) == 2 * len(batch)
                    if not valid:
                        raise MoneyflowContractError("history_event_readback")
                    save()
            batch_started = monotonic()
            stage, current_day, current_layer = "audit", None, None
            validate_market_moneyflow_event_plan(plan, instance, check=guard)
            final = state(plan["entries"])
            complete = (
                len(dates & final["registered"])
                + len(final["mats"])
                + len(final["checks"])
            )
            if complete != plan["total_work_items"]:
                raise MoneyflowContractError("history_event_readback")
            completed, stage = complete, "complete"
            save()
            return observe()
        except BaseException as error:
            stage = (
                "cancelled"
                if str(error) == "history_event_cancelled"
                else "interrupted"
                if isinstance(error, (KeyboardInterrupt, SystemExit))
                else "failed"
            )
            try:
                save()
            except Exception:
                LOGGER.exception("资金流终态进度保存失败；续跑以原生事件为准")
            raise
