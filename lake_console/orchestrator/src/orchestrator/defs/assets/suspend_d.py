import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import dagster as dg

from orchestrator.defs import stock_suspend_confirmed_contract as confirmed_contract
from orchestrator.defs.corrections.suspend_timing import (
    SUSPEND_TIMING_CORRECTION_VERSION,
    suspend_timing_correction_samples,
    suspend_timing_corrections_values_sql,
)
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import (
    SUSPEND_D_RAW_REQUIRED_COLUMNS,
    copy_query_to_parquet,
    describe_parquet_query,
    read_parquet,
    silver_stock_suspend_daily_select,
    stock_suspend_confirmed_conflicts_select,
    stock_suspend_confirmed_stats_select,
    suspend_d_normalized_select,
)
from orchestrator.defs.partitions import cn_a_stock_trade_days
from orchestrator.defs.paths import (
    DEFAULT_LAKE_STAGING_ROOT,
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    lake_path_template,
    raw_suspend_d_path,
    silver_stock_suspend_confirmed_path,
    silver_stock_suspend_daily_path,
    silver_stock_suspend_daily_staging_path,
)
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    TushareResource,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_STOCK_SUSPEND_DAILY_SCHEMA,
    SILVER_STOCK_SUSPEND_DAILY_SCHEMA,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.metadata import (
    CONFIRMED_FACT_LOGICAL_SHA256_METADATA_KEY,
    CONFIRMED_FACT_STATS_METADATA_KEY,
    CONFIRMED_FACT_VERSION_METADATA_KEY,
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.tushare_api_io import fetch_tushare_partition_to_raw
from orchestrator.utils.dg_log_helper import DgStdoutLogger

SUSPEND_D_RAW_COLUMN_TYPES = {
    column.name: column.type for column in RAW_TUSHARE_STOCK_SUSPEND_DAILY_SCHEMA
}


def _human_materialization_metadata(
    *,
    summary: str,
    next_action: str,
    result_status: str,
    input_summary: dict[str, Any] | None = None,
    filter_summary: dict[str, Any] | None = None,
    diagnostic_ref: str,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "goldenshare/summary": summary,
        "goldenshare/next_action": next_action,
        "goldenshare/result_status": result_status,
        "goldenshare/diagnostic_ref": diagnostic_ref,
    }
    if input_summary:
        metadata["goldenshare/input_summary"] = input_summary
    if filter_summary:
        metadata["goldenshare/filter_summary"] = filter_summary
    return metadata



# One-file state only: no backup, global lock, instance or cross-run discovery.
_SUSPEND_CHECKPOINT_MAX_BYTES = 1024 * 1024
_SUSPEND_STATS = (
    "selected_fact_keys", "add_missing_inserted_keys", "add_missing_reused_keys",
    "replace_confirmed_keys", "replace_confirmed_matched_raw_keys", "removed_raw_rows",
    "conflict_rows", "output_rows",
)
_SUSPEND_RELATIONS = {
    "normalized_relation": "suspend_normalized", "confirmed_relation": "suspend_confirmed",
    "dates_relation": "suspend_dates",
}


@dataclass(frozen=True)
class SuspendDailyWriteResult:
    target_path: Path
    status: str
    output: dict
    confirmed_version: str
    confirmed_logical_sha256: str


def _writer_failure(reason: str, details: Any = None) -> None:
    raise confirmed_contract.ConfirmedFactsError(
        f"停牌 Silver 未完成：{reason}；{details}", reason, 4,
    )


def _identity_or_absent(path: Path) -> dict | None:
    # Missing is distinct from broken, symlink, or inaccessible.
    try:
        return asdict(confirmed_contract.suspend_file_identity(path))
    except FileNotFoundError:
        return None


def _file_evidence(path: Path, expected_identity: dict | None = None) -> dict:
    identity = asdict(confirmed_contract.suspend_file_identity(path))
    if expected_identity is not None and identity != expected_identity:
        _writer_failure("input_drift", path)
    digest = confirmed_contract.suspend_file_sha256(path)
    if identity != asdict(confirmed_contract.suspend_file_identity(path)):
        _writer_failure("input_drift", path)
    return {"path": str(path), "file_identity": identity, "physical_sha256": digest}


def _verify_evidence(evidence: dict) -> None:
    actual = _file_evidence(Path(evidence["path"]), evidence["file_identity"])
    if actual["physical_sha256"] != evidence["physical_sha256"]:
        _writer_failure("input_drift", evidence["path"])


def _silver_schema() -> list[list[str]]:
    return [[column.name, column.type] for column in SILVER_STOCK_SUSPEND_DAILY_SCHEMA]


def _load_silver_file(connection, path: Path) -> tuple[dict, int]:
    before = asdict(confirmed_contract.suspend_file_identity(path))
    columns = connection.execute(describe_parquet_query(path, hive_partitioning=False)).fetchall()
    if [[row[0], row[1]] for row in columns] != _silver_schema():
        _writer_failure("silver_schema_mismatch", path)
    # Full decode once, no casts to hide a corrupt physical contract.
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE suspend_verified AS SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
    )
    count = connection.execute("SELECT count(*) FROM suspend_verified").fetchone()[0]
    return _file_evidence(path, before), count


def _silver_matches_output(connection) -> bool:
    return connection.execute("""
        SELECT NOT EXISTS (SELECT * FROM suspend_verified EXCEPT ALL SELECT * FROM suspend_output)
           AND NOT EXISTS (SELECT * FROM suspend_output EXCEPT ALL SELECT * FROM suspend_verified)
    """).fetchone()[0]


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _save_suspend_checkpoint(path: Path, checkpoint: dict) -> None:
    checkpoint["updated_at"] = datetime.now(UTC).isoformat()
    payload = json.dumps(checkpoint, ensure_ascii=False, allow_nan=False, sort_keys=True).encode("utf-8")
    if len(payload) > _SUSPEND_CHECKPOINT_MAX_BYTES:
        _writer_failure("checkpoint_size_exceeded")
    confirmed_contract.assert_suspend_path(path, root=path.parent)
    # Failed temporary JSON is evidence; a retry never overwrites it.
    temporary = path.with_name(f"checkpoint.{uuid4().hex}.tmp")
    with temporary.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    _sync_directory(path.parent)


def _checkpoint_keys(value: Any, keys: set[str]) -> None:
    if type(value) is not dict or set(value) != keys:
        raise ValueError("checkpoint fields mismatch")


def _checkpoint_identity(value: Any, path: Path) -> None:
    _checkpoint_keys(value, {"path", "device", "inode", "size", "mtime_ns"})
    if value["path"] != str(path):
        raise ValueError("checkpoint identity path mismatch")
    if any(type(value[key]) is not int or value[key] < 0 for key in ("device", "inode", "size", "mtime_ns")):
        raise ValueError("checkpoint identity type mismatch")


def _checkpoint_hash(value: Any) -> None:
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value):
        raise ValueError("checkpoint hash mismatch")


def _unique_json_object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate checkpoint key")
        result[key] = value
    return result


def _read_suspend_checkpoint(path: Path, paths: dict, run_id: str, trade_date: str) -> dict:
    try:
        before = confirmed_contract.suspend_file_identity(path)
        if before.size > _SUSPEND_CHECKPOINT_MAX_BYTES:
            raise ValueError("oversized checkpoint")
        with path.open("rb") as stream:
            payload = stream.read(_SUSPEND_CHECKPOINT_MAX_BYTES + 1)
        if len(payload) > _SUSPEND_CHECKPOINT_MAX_BYTES or before != confirmed_contract.suspend_file_identity(path):
            raise ValueError("checkpoint changed during read")
        value = json.loads(payload, object_pairs_hook=_unique_json_object)
        _checkpoint_keys(value, {"schema_version", "run_id", "trade_date", "raw", "confirmed",
                                 "candidate", "target", "output", "stage", "updated_at", "error"})
        if (type(value["schema_version"]) is not int or value["schema_version"] != 1
                or value["run_id"] != run_id or value["trade_date"] != trade_date
                or value["stage"] not in ("prepared", "committed")):
            raise ValueError("checkpoint run/day/stage mismatch")
        datetime.fromisoformat(value["updated_at"])
        if value["error"] is not None:
            _checkpoint_keys(value["error"], {"reason_code", "message"})
            if any(not isinstance(v, str) for v in value["error"].values()):
                raise ValueError("checkpoint diagnostic mismatch")
        for key in ("raw", "confirmed", "candidate"):
            entry = value[key]
            fields = {"path", "file_identity", "physical_sha256"}
            if key == "confirmed":
                fields |= {"version", "logical_sha256"}
            _checkpoint_keys(entry, fields)
            if entry["path"] != str(paths[key]):
                raise ValueError("checkpoint input path mismatch")
            _checkpoint_identity(entry["file_identity"], paths[key])
            _checkpoint_hash(entry["physical_sha256"])
        if (value["confirmed"]["version"] != confirmed_contract.STOCK_SUSPEND_CONFIRMED_VERSION
                or value["confirmed"]["logical_sha256"]
                != confirmed_contract.STOCK_SUSPEND_CONFIRMED_APPROVED_LOGICAL_SHA256):
            raise ValueError("checkpoint approval mismatch")
        target_fields = {"path", "before"}
        if value["stage"] == "committed":
            target_fields.add("committed_identity")
        _checkpoint_keys(value["target"], target_fields)
        if value["target"]["path"] != str(paths["target"]):
            raise ValueError("checkpoint target mismatch")
        for key in target_fields - {"path"}:
            identity = value["target"][key]
            if key == "before" and identity is None:
                continue
            _checkpoint_identity(identity, paths["target"])
        output = value["output"]
        _checkpoint_keys(output, {"schema", "row_count", "stats", "timing_count", "timing_version", "timing_samples"})
        if output["schema"] != _silver_schema():
            raise ValueError("checkpoint output schema mismatch")
        for key in ("row_count", "timing_count"):
            if type(output[key]) is not int or output[key] < 0:
                raise ValueError("checkpoint output count mismatch")
        stats = output["stats"]
        _checkpoint_keys(stats, {*_SUSPEND_STATS, "samples"})
        if any(type(stats[key]) is not int or stats[key] < 0 for key in _SUSPEND_STATS):
            raise ValueError("checkpoint statistics type mismatch")
        if (stats["conflict_rows"] != 0 or stats["output_rows"] != output["row_count"]
                or output["timing_count"] > output["row_count"]
                or stats["selected_fact_keys"] != sum(stats[key] for key in _SUSPEND_STATS[1:4])
                or stats["replace_confirmed_matched_raw_keys"] > stats["replace_confirmed_keys"]):
            raise ValueError("checkpoint statistics mismatch")
        if type(stats["samples"]) is not list or len(stats["samples"]) > 20:
            raise ValueError("checkpoint sample budget mismatch")
        for sample in stats["samples"]:
            _checkpoint_keys(sample, {"category", "ts_code", "trade_date"})
            if (sample["category"] not in ("add_missing_inserted", "add_missing_reused", "replace_confirmed")
                    or not isinstance(sample["ts_code"], str) or sample["trade_date"] != trade_date):
                raise ValueError("checkpoint sample mismatch")
        if not isinstance(output["timing_version"], str) or not output["timing_version"]:
            raise ValueError("checkpoint timing version mismatch")
        if type(output["timing_samples"]) is not list or len(output["timing_samples"]) > 20:
            raise ValueError("checkpoint timing sample budget mismatch")
        for sample in output["timing_samples"]:
            _checkpoint_keys(sample, {"trade_date", "ts_code", "suspend_timing"})
            if any(not isinstance(v, str) for v in sample.values()):
                raise ValueError("checkpoint timing sample mismatch")
        return value
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise confirmed_contract.ConfirmedFactsError(
            f"checkpoint损坏或不属于本次操作：{exc}", "checkpoint_invalid", 4,
        ) from exc


def _write_result(checkpoint: dict, status: str) -> SuspendDailyWriteResult:
    return SuspendDailyWriteResult(
        Path(checkpoint["target"]["path"]), status, checkpoint["output"],
        checkpoint["confirmed"]["version"], checkpoint["confirmed"]["logical_sha256"],
    )


def _finish_suspend_commit(connection, checkpoint_path: Path, checkpoint: dict) -> SuspendDailyWriteResult:
    target = Path(checkpoint["target"]["path"])
    _sync_directory(target.parent)
    actual, count = _load_silver_file(connection, target)
    if (actual["physical_sha256"] != checkpoint["candidate"]["physical_sha256"]
            or count != checkpoint["output"]["row_count"]):
        _writer_failure("committed_target_mismatch", target)
    checkpoint["stage"] = "committed"
    checkpoint["target"]["committed_identity"] = actual["file_identity"]
    checkpoint["error"] = None
    _save_suspend_checkpoint(checkpoint_path, checkpoint)
    try:
        _verify_evidence(checkpoint["raw"])
        _verify_evidence(checkpoint["confirmed"])
    except (OSError, confirmed_contract.ConfirmedFactsError) as exc:
        checkpoint["error"] = {"reason_code": "committed_input_drift", "message": str(exc)}
        _save_suspend_checkpoint(checkpoint_path, checkpoint)
        _writer_failure("committed_input_drift", "文件已提交；当前输入已变化，须用新run重新计算")
    return _write_result(checkpoint, "written")


def _promote_suspend_candidate(connection, checkpoint_path: Path, checkpoint: dict) -> SuspendDailyWriteResult:
    target, candidate = Path(checkpoint["target"]["path"]), Path(checkpoint["candidate"]["path"])
    _verify_evidence(checkpoint["raw"])
    _verify_evidence(checkpoint["confirmed"])
    _verify_evidence(checkpoint["candidate"])
    if _identity_or_absent(target) != checkpoint["target"]["before"]:
        _writer_failure("target_drift", target)
    target.parent.mkdir(parents=True, exist_ok=True)
    confirmed_contract.assert_suspend_path(target, root=target.parent)
    if candidate.stat().st_dev != target.parent.stat().st_dev:
        _writer_failure("cross_device")
    with candidate.open("rb") as stream:
        os.fsync(stream.fileno())
    _save_suspend_checkpoint(checkpoint_path, checkpoint)
    # Checkpoint fsync can take time; reject drift during it before file promotion.
    _verify_evidence(checkpoint["raw"])
    _verify_evidence(checkpoint["confirmed"])
    _verify_evidence(checkpoint["candidate"])
    if _identity_or_absent(target) != checkpoint["target"]["before"]:
        _writer_failure("target_drift", target)
    # No pre-delete and no claimed compare-and-swap guarantee.
    os.replace(candidate, target)
    return _finish_suspend_commit(connection, checkpoint_path, checkpoint)


def _resume_suspend_write(connection, checkpoint_path: Path, checkpoint: dict) -> SuspendDailyWriteResult:
    target = Path(checkpoint["target"]["path"])
    observed = _identity_or_absent(target)
    if observed is not None:
        actual = _file_evidence(target, observed)
        if actual["physical_sha256"] == checkpoint["candidate"]["physical_sha256"]:
            return _finish_suspend_commit(connection, checkpoint_path, checkpoint)
    if checkpoint["stage"] == "committed":
        _writer_failure("committed_target_mismatch", target)
    candidate, count = _load_silver_file(connection, Path(checkpoint["candidate"]["path"]))
    if candidate != checkpoint["candidate"] or count != checkpoint["output"]["row_count"]:
        _writer_failure("candidate_drift")
    return _promote_suspend_candidate(connection, checkpoint_path, checkpoint)


def write_silver_stock_suspend_daily_partition(
    connection, *, lake_root: Path, staging_root: Path, trade_date: str, run_id: str,
) -> SuspendDailyWriteResult:
    """Write one day under manual same-day exclusion; LLD §5 is the contract."""
    candidate = silver_stock_suspend_daily_staging_path(staging_root, run_id, trade_date)
    for root in (lake_root, staging_root):
        confirmed_contract.assert_suspend_path(root, root=root)
    if lake_root.is_relative_to(staging_root) or staging_root.is_relative_to(lake_root):
        _writer_failure("overlapping_roots")
    if lake_root.stat().st_dev != staging_root.stat().st_dev:
        _writer_failure("cross_device")
    paths = {
        "raw": raw_suspend_d_path(lake_root, trade_date),
        "confirmed": silver_stock_suspend_confirmed_path(lake_root),
        "target": silver_stock_suspend_daily_path(lake_root, trade_date),
        "candidate": candidate,
    }
    for key, path in paths.items():
        confirmed_contract.assert_suspend_path(path, root=staging_root if key == "candidate" else lake_root)
    checkpoint_path = candidate.with_name("checkpoint.json")
    confirmed_contract.assert_suspend_path(checkpoint_path, root=staging_root)
    if checkpoint_path.exists():
        checkpoint = _read_suspend_checkpoint(checkpoint_path, paths, run_id, trade_date)
        return _resume_suspend_write(connection, checkpoint_path, checkpoint)
    if candidate.exists():
        _writer_failure("unprepared_candidate", candidate)
    before = _identity_or_absent(paths["target"])
    inspection = confirmed_contract.inspect_confirmed_file(connection, paths["confirmed"])
    confirmed_contract.load_confirmed_relation(connection, inspection, relation_name="suspend_confirmed")
    validation = confirmed_contract.validate_confirmed_content(connection, "suspend_confirmed")
    if not validation.passed:
        _writer_failure(validation.reason_code, validation.samples)
    fixed = _file_evidence(paths["confirmed"], asdict(inspection.file_identity))
    fixed.update(version=confirmed_contract.STOCK_SUSPEND_CONFIRMED_VERSION, logical_sha256=validation.logical_sha256)
    raw_identity = asdict(confirmed_contract.suspend_file_identity(paths["raw"]))
    connection.execute(f"CREATE OR REPLACE TEMP TABLE suspend_normalized AS {suspend_d_normalized_select(paths['raw'])}")
    raw = _file_evidence(paths["raw"], raw_identity)
    connection.execute("CREATE OR REPLACE TEMP TABLE suspend_dates AS SELECT ?::DATE AS trade_date", [trade_date])
    misplaced = "SELECT * FROM suspend_normalized WHERE trade_date IS NULL OR trade_date <> ?::DATE"
    misplaced_count = connection.execute(f"SELECT count(*) FROM ({misplaced})", [trade_date]).fetchone()[0]
    if misplaced_count:
        samples = connection.execute(f"SELECT * FROM ({misplaced}) ORDER BY ts_code LIMIT 20", [trade_date]).fetchall()
        _writer_failure("raw_partition_date_mismatch", {"count": misplaced_count, "samples": samples})
    conflicts = stock_suspend_confirmed_conflicts_select(**_SUSPEND_RELATIONS)
    conflict_count = connection.execute(f"SELECT count(*) FROM ({conflicts})").fetchone()[0]
    if conflict_count:
        samples = connection.execute(f"SELECT * FROM ({conflicts}) ORDER BY ts_code LIMIT 20").fetchall()
        _writer_failure("confirmed_raw_conflict", {"count": conflict_count, "samples": samples})
    connection.execute(f"CREATE OR REPLACE TEMP TABLE suspend_output AS {silver_stock_suspend_daily_select(**_SUSPEND_RELATIONS)}")
    stats_row = connection.execute(stock_suspend_confirmed_stats_select(**_SUSPEND_RELATIONS)).fetchone()
    stats = dict(zip(_SUSPEND_STATS, stats_row[:8], strict=True))
    stats["samples"] = [{**sample, "trade_date": sample["trade_date"].isoformat()} for sample in stats_row[8]]
    count = connection.execute("SELECT count(*) FROM suspend_output").fetchone()[0]
    if count != stats["output_rows"]:
        _writer_failure("output_count_mismatch")
    timing_count = connection.execute(f"""
        WITH corrections(ts_code, trade_date, corrected_suspend_timing) AS (
          {suspend_timing_corrections_values_sql()}
        )
        SELECT count(*) FROM suspend_output silver JOIN corrections
          ON silver.ts_code=corrections.ts_code AND silver.trade_date=corrections.trade_date
         AND silver.suspend_timing=corrections.corrected_suspend_timing
    """).fetchone()[0]
    checkpoint = {
        "schema_version": 1, "run_id": run_id, "trade_date": trade_date, "raw": raw, "confirmed": fixed,
        "target": {"path": str(paths["target"]), "before": before},
        "output": {"schema": _silver_schema(), "row_count": count, "stats": stats,
                   "timing_count": timing_count, "timing_version": SUSPEND_TIMING_CORRECTION_VERSION,
                   "timing_samples": suspend_timing_correction_samples()},
        "stage": "prepared", "updated_at": datetime.now(UTC).isoformat(), "error": None,
    }
    if before is not None:
        target_evidence, _ = _load_silver_file(connection, paths["target"])
        if target_evidence["file_identity"] != before:
            _writer_failure("target_drift")
        if _silver_matches_output(connection):
            _verify_evidence(raw)
            _verify_evidence(fixed)
            _verify_evidence(target_evidence)
            return _write_result(checkpoint, "reused")
    candidate.parent.mkdir(parents=True, exist_ok=True)
    confirmed_contract.assert_suspend_path(candidate, root=staging_root)
    connection.execute(copy_query_to_parquet("SELECT * FROM suspend_output", candidate))
    evidence, candidate_count = _load_silver_file(connection, candidate)
    if candidate_count != count or not _silver_matches_output(connection):
        _writer_failure("candidate_mismatch")
    checkpoint["candidate"] = evidence
    return _promote_suspend_candidate(connection, checkpoint_path, checkpoint)


@dg.asset(
    name="raw_tushare_suspend_d",
    partitions_def=cn_a_stock_trade_days,
    group_name="quote",
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.QUOTE_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id="suspend_d",
        source_system=SourceSystem.TUSHARE,
        source_api="suspend_d",
        source_category_path="股票数据 / 行情数据",
        source_doc="docs/sources/tushare/股票数据/行情数据/0214_每日停复牌信息.md",
        data_contract="source_mirror",
        column_schema=RAW_TUSHARE_STOCK_SUSPEND_DAILY_SCHEMA,
        path_template=lake_path_template(
            raw_suspend_d_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)
        ),
        extra_metadata={
            "raw_contract": (
                "Tushare suspend_d source mirror: trade_date YYYYMMDD string, "
                "suspend_timing nullable string."
            ),
            "write_summary": (
                "Tushare API rows written to raw parquet with explicit source contract fields."
            ),
        },
    ),
    description="Tushare 每日停复牌 raw 源镜像，按股票交易日保存停牌、复牌类型和时段，供停复牌 silver 标准事实使用。",
)
def raw_tushare_suspend_d(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    tushare: TushareResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    partition_key = context.partition_key
    target_path = raw_suspend_d_path(lake_root.root(), partition_key)
    log = DgStdoutLogger("suspend_d")
    log.stdout(
        "raw_suspend_d_started",
        partition_key=partition_key,
        allow_empty=True,
    )
    metadata = fetch_tushare_partition_to_raw(
        tushare=tushare,
        duckdb=duckdb,
        api_name="suspend_d",
        api_params={"trade_date": partition_key.replace("-", "")},
        fields=SUSPEND_D_RAW_REQUIRED_COLUMNS,
        column_types=SUSPEND_D_RAW_COLUMN_TYPES,
        target_path=target_path,
        partition_key=partition_key,
        allow_empty=True,
    )
    metadata.update(
        _human_materialization_metadata(
            summary="已写入停复牌 raw 源镜像分区。",
            next_action="等待 raw blocking checks 全部通过；通过后 silver_stock_suspend_daily 才能消费。",
            result_status="written",
            input_summary={
                "source": "Tushare suspend_d",
                "partition_key": partition_key,
                "allow_empty": True,
                "target_path_exists": target_path.exists(),
            },
            diagnostic_ref="完整诊断看 raw suspend_d checks、materialization metadata 和 run stdout。",
        )
    )
    log.stdout(
        "raw_suspend_d_completed",
        partition_key=partition_key,
        output_row_count=metadata.get("dagster/row_count"),
        page_count=metadata.get("goldenshare/page_count"),
    )

    return dg.MaterializeResult(metadata=metadata)


@dg.asset(
    name="silver_stock_suspend_daily",
    deps=[raw_tushare_suspend_d, dg.AssetKey(confirmed_contract.STOCK_SUSPEND_CONFIRMED_ASSET_KEY)],
    partitions_def=cn_a_stock_trade_days,
    group_name="quote",
    tags=build_asset_tags(layer=AssetLayer.SILVER, data_domain=DataDomain.QUOTE_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id="suspend_d",
        source_system=SourceSystem.DERIVED,
        data_contract="standardized_stock_suspend_daily",
        column_schema=SILVER_STOCK_SUSPEND_DAILY_SCHEMA,
        path_template=lake_path_template(
            silver_stock_suspend_daily_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        extra_metadata={
            "correction_policy": "Apply timing corrections and the approved fixed Silver suspension facts."
        },
    ),
    description="股票日频停复牌 silver 标准事实，按交易日记录停牌类型和停牌时段，并应用已确认的停牌时段修正和全日停牌补充规则。",
)
def silver_stock_suspend_daily(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    partition_key = context.partition_key
    root = lake_root.root()
    log = DgStdoutLogger("suspend_d")
    log.stdout("silver_suspend_d_started", partition_key=partition_key)
    with connect_configured_duckdb() as connection:
        try:
            result = write_silver_stock_suspend_daily_partition(
                connection, lake_root=root, staging_root=Path(DEFAULT_LAKE_STAGING_ROOT),
                trade_date=partition_key, run_id=context.run_id,
            )
        except confirmed_contract.ConfirmedFactsError as error:
            log.stdout("silver_suspend_d_validation_failed", partition_key=partition_key,
                       reason_code=error.reason_code)
            raise
    output = result.output
    log.stdout(
        "silver_suspend_d_completed", partition_key=partition_key, result_status=result.status,
        output_row_count=output["row_count"], timing_correction_count=output["timing_count"],
        selected_fact_keys=output["stats"]["selected_fact_keys"],
    )
    return dg.MaterializeResult(metadata=build_materialization_metadata(
        uri=result.target_path, row_count=output["row_count"],
        observed_columns=[column[0] for column in output["schema"]],
        extra_metadata={
            **_human_materialization_metadata(
                summary="已核验并完成停复牌 Silver 分区；等价已有文件不重复覆盖。",
                next_action="等待原三个 Silver blocking checks；通过后本地日线/分钟链可消费。",
                result_status=result.status,
                input_summary={"source_asset": "raw_tushare_suspend_d", "partition_key": partition_key,
                               "confirmed_asset": confirmed_contract.STOCK_SUSPEND_CONFIRMED_ASSET_KEY},
                filter_summary=output["stats"],
                diagnostic_ref="失败时查看本run staging checkpoint；最终质量查看Silver checks。",
            ),
            "raw_file_path": str(raw_suspend_d_path(root, partition_key)), "partition_key": partition_key,
            "suspend_timing_correction_count": output["timing_count"],
            "suspend_timing_correction_version": output["timing_version"],
            "suspend_timing_correction_sample_rows": output["timing_samples"],
            CONFIRMED_FACT_VERSION_METADATA_KEY: result.confirmed_version,
            CONFIRMED_FACT_LOGICAL_SHA256_METADATA_KEY: result.confirmed_logical_sha256,
            CONFIRMED_FACT_STATS_METADATA_KEY: output["stats"],
        },
    ))
