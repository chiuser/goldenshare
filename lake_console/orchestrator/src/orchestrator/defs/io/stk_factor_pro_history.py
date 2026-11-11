"""Closed historical records and current-run source verification on one connection."""

from __future__ import annotations

import json
import os
import shutil
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import fields, replace
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

import dagster as dg
import pandas as pd
from duckdb import Error as DuckDBError

from orchestrator.defs.checks.stk_factor_pro import (
    factor_file_identity,
    factor_file_sha,
    factor_known_file_sha,
    relation_identifier,
)
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.io.stk_factor_pro_candidates import (
    require_stk_factor_pro_safe_path,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_STAGING_ROOT,
    raw_adj_factor_path,
    raw_stk_factor_pro_path,
    silver_stock_factor_pro_path,
    silver_stock_lifecycle_path,
    stk_factor_pro_record_path,
    stk_factor_pro_run_staging_root,
)
from orchestrator.defs.run_contracts import stk_factor_pro as C
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_ADJ_FACTOR_SCHEMA,
    SILVER_STOCK_LIFECYCLE_SCHEMA,
)
from orchestrator.defs.run_contracts.stk_factor_pro import (
    STK_FACTOR_PRO_PROCESSING_VERSION,
    STK_FACTOR_PRO_TIMEZONE,
    ContractIdentity,
    FactorFileRef,
    HistoryEligibilityRecord,
    HistoryOriginRef,
    HistoryPlanReason,
    HistoryPlanRecord,
    HistoryRange,
    PublicationCompleteRecord,
    RecordRef,
    RunIdentity,
    SourceCompleteRecord,
    SourceFileRecord,
    StkFactorProHistoryStart,
    StkFactorProRawCoverage,
    StkFactorProRecordedResults,
    StkFactorProTargetSilver,
    UnitProjection,
    VerifiedSource,
    parse_stk_factor_pro_record,
    stk_factor_pro_history_input_digest,
    stk_factor_pro_history_plan_digest,
    stk_factor_pro_history_ranges_digest,
    stk_factor_pro_record_to_dict,
    stk_factor_pro_unit_key,
)
from orchestrator.tushare_download.contract_registry import content_digest
from orchestrator.tushare_download.contracts.stk_factor_pro import (
    STK_FACTOR_PRO_CONTRACT,
)

HISTORY_RANGE_SCHEMA = (
    ("ts_code", "VARCHAR"),
    ("t_present", "BOOLEAN"),
    ("p_present", "BOOLEAN"),
    ("t_value", "DOUBLE"),
    ("p_value", "DOUBLE"),
    ("start_date", "DATE"),
    ("end_date", "DATE"),
    ("plan_reasons", "INTEGER[]"),
    ("origin_target_dates", "DATE[]"),
    ("origin_record_refs", "VARCHAR"),
    ("earliest_basis_kind", "INTEGER"),
    ("earliest_basis_date", "DATE"),
)
SOURCE_FILE_SCHEMA = (
    ("phase", "VARCHAR"),
    ("unit_key", "VARCHAR"),
    ("component_unit_id", "VARCHAR"),
    ("ordinal", "BIGINT"),
    ("mode", "INTEGER"),
    ("object_code", "VARCHAR"),
    ("point", "DATE"),
    ("start_date", "DATE"),
    ("end_date", "DATE"),
    ("source_row_count", "BIGINT"),
    ("saved_row_count", "BIGINT"),
    ("file_relative_path", "VARCHAR"),
    ("file_sha256", "VARCHAR"),
    ("file_rows", "BIGINT"),
    ("schema_content_digest", "VARCHAR"),
    ("contract_content_digest", "VARCHAR"),
    ("verified_at", "TIMESTAMP WITH TIME ZONE"),
)


@contextmanager
def _history_resource_cleanup(*releases: Callable[[], object]) -> Iterator[None]:
    """Attempt every owned DuckDB cleanup without replacing the body error."""
    primary = None
    try:
        yield
    except BaseException as error:
        primary = error
        raise
    finally:
        failures = []
        for release in releases:
            try:
                release()
            except (DuckDBError, OSError) as cleanup:
                failures.append(cleanup)
        if failures:
            reported = primary if primary is not None else failures[0]
            for cleanup in failures:
                reported.add_note(f"历史记录清理同时失败：{type(cleanup).__name__}")
            if primary is None:
                raise reported


def _run_root(root: Path, *, run_id: str, target: date) -> None:
    require_stk_factor_pro_safe_path(root)
    staging = root.parent.parent.parent
    if stk_factor_pro_run_staging_root(staging, run_id, target.isoformat()) != root:
        raise ValueError("历史根目录不对应已核run/T固定路径")
    if (root == Path("/Volumes") or Path("/Volumes") in root.parents) and (
        staging != Path(DEFAULT_LAKE_STAGING_ROOT) or not staging.parent.is_mount()
    ):
        raise ValueError("历史记录只能使用已挂载的正式staging根")


def _path(root: Path, identity: RunIdentity, relative: str) -> Path:
    _run_root(root, run_id=identity.creator_run_id, target=identity.target_trade_date)
    result = stk_factor_pro_record_path(
        root,
        RecordRef(identity.creator_run_id, relative, "0" * 64),
        expected_run_id=identity.creator_run_id,
    )
    require_stk_factor_pro_safe_path(result)
    return result


def _ref_path(
    root: Path, identity: RunIdentity, reference: RecordRef, *, known_records: dict
) -> Path:
    if reference.creator_run_id != identity.creator_run_id:
        raise ValueError("历史源引用必须属于当前run")
    path = _path(root, identity, reference.relative_path)
    if path not in known_records:
        if not path.is_file():
            known_records[path] = (None, None, None)
        elif path.suffix == ".json":
            payload = path.read_bytes()
            known_records[path] = (
                payload,
                sha256(payload).hexdigest(),
                factor_file_identity(path),
            )
        else:
            known_records[path] = (
                None,
                factor_file_sha(path),
                factor_file_identity(path),
            )
    if known_records[path][1] != reference.file_sha256:
        raise ValueError("历史引用文件缺失或字节SHA不符")
    return path


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("历史JSON不得包含重复字段")
        result[key] = value
    return result


def _json_read(path: Path, record_type, *, known_records: dict):
    require_stk_factor_pro_safe_path(path)
    if path in known_records:
        record, digest, identity = known_records[path]
        if isinstance(record, record_type):
            return record
        if record is None:
            raise ValueError("历史JSON文件缺失")
        if type(record) is not bytes:
            raise TypeError("历史记录已登记为其他记录类型")
        payload = record
    else:
        try:
            payload = path.read_bytes()
        except FileNotFoundError as error:
            known_records[path] = (None, None, None)
            raise ValueError("历史JSON文件缺失") from error
        digest, identity = sha256(payload).hexdigest(), factor_file_identity(path)
    value = json.loads(payload, object_pairs_hook=_pairs)
    record = parse_stk_factor_pro_record(record_type, value)
    if stk_factor_pro_record_to_dict(record) != value:
        raise ValueError("历史JSON表示不规范")
    known_records[path] = (record, digest, identity)
    return record


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _prepare(path: Path) -> Path:
    require_stk_factor_pro_safe_path(path)
    temporary = path.with_name(path.name + ".tmp")
    require_stk_factor_pro_safe_path(temporary)
    if path.exists() or temporary.exists():
        raise ValueError("历史记录已存在，不接受覆盖或跨次续写")
    path.parent.mkdir(parents=True, exist_ok=True)
    require_stk_factor_pro_safe_path(path)
    require_stk_factor_pro_safe_path(temporary)
    return temporary


def _promote(temporary: Path, path: Path) -> None:
    for value in (temporary, path):
        require_stk_factor_pro_safe_path(value)
    if path.exists():
        raise ValueError("历史记录目标在写入时已改变")
    if temporary.stat().st_dev != path.parent.stat().st_dev:
        raise ValueError("历史记录必须同文件系统原子保存")
    with temporary.open("rb") as stream:
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _json_write(
    root: Path,
    identity: RunIdentity,
    relative: str,
    record,
    *,
    known_records: dict,
    check_space: Callable | None,
):
    path = _path(root, identity, relative)
    if check_space is not None:
        check_space("历史记录保存前", path=path)
    payload = json.dumps(
        stk_factor_pro_record_to_dict(record),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    payload = payload.encode("utf-8")
    digest = sha256(payload).hexdigest()
    temporary = _prepare(path)
    with temporary.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    _promote(temporary, path)
    known_records[path] = (record, digest, factor_file_identity(path))
    if check_space is not None:
        check_space("历史记录已保存", path=path, event="record_saved")
    return RecordRef(identity.creator_run_id, relative, digest)


def _record_order(schema) -> str:
    if schema == HISTORY_RANGE_SCHEMA:
        return "ts_code"
    if schema == SOURCE_FILE_SCHEMA:
        return "unit_key"
    raise ValueError("未知历史记录schema")


def _read_rows(connection, path: Path, schema, *, known_records: dict):
    if path in known_records and known_records[path][0] is not None:
        return known_records[path][0]
    digest = known_records[path][1] if path in known_records else factor_file_sha(path)
    relation = "stk_factor_pro_record_read"
    with _history_resource_cleanup(
        lambda: connection.execute(f"DROP TABLE IF EXISTS {relation}")
    ):
        connection.execute(
            f"CREATE TEMP TABLE {relation} AS SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
        )
        observed = tuple(
            (row[0], row[1])
            for row in connection.execute(f"DESCRIBE {relation}").fetchall()
        )
        if observed != schema:
            raise ValueError("历史Parquet列名/顺序/类型与完整合同不符")
        columns = ", ".join(f'"{name}"' for name, _ in schema)
        rows = tuple(
            connection.execute(
                f"SELECT {columns} FROM {relation} ORDER BY {_record_order(schema)}"
            ).fetchall()
        )
    known_records[path] = (rows, digest, factor_file_identity(path))
    return rows


def _write_rows(
    connection,
    root: Path,
    identity: RunIdentity,
    relative: str,
    schema,
    rows,
    decode,
    *,
    known_records: dict,
    check_space: Callable | None,
):
    path = _path(root, identity, relative)
    if check_space is not None:
        check_space("历史范围或清单保存前", path=path)
    temporary = _prepare(path)
    relation, registered = "stk_factor_pro_record_rows", "stk_factor_pro_record_frame"
    definitions = ", ".join(f'"{name}" {kind}' for name, kind in schema)
    with _history_resource_cleanup(
        lambda: connection.unregister(registered),
        lambda: connection.execute(f"DROP TABLE IF EXISTS {relation}"),
    ):
        if rows:
            frame = pd.DataFrame(
                {
                    name: pd.Series([row[index] for row in rows], dtype=object)
                    for index, (name, _) in enumerate(schema)
                }
            )
            connection.register(registered, frame)
            projection = ", ".join(
                f'CAST("{name}" AS {kind}) AS "{name}"' for name, kind in schema
            )
            connection.execute(
                f"CREATE TEMP TABLE {relation} AS SELECT {projection} FROM {registered}"
            )
        else:
            connection.execute(f"CREATE TEMP TABLE {relation} ({definitions})")
        connection.execute(
            copy_query_to_parquet(
                f"SELECT * FROM {relation} ORDER BY {_record_order(schema)}", temporary
            )
        )
        observed = tuple(
            decode(values)
            for values in _read_rows(
                connection, temporary, schema, known_records=known_records
            )
        )
        expected = tuple(decode(values) for values in rows)
        if observed != expected:
            raise ValueError("历史Parquet候选内容与输入不符")
        _promote(temporary, path)
        digest = known_records.pop(temporary)[1]
        known_records[path] = (observed, digest, factor_file_identity(path))
        if check_space is not None:
            check_space("历史范围或清单已保存", path=path, event="record_saved")
        return RecordRef(identity.creator_run_id, relative, digest)


def read_stk_factor_pro_history_plan(
    root: Path, *, expected_target: date, expected_run_id: str, known_records: dict
) -> HistoryPlanRecord:
    _run_root(root, run_id=expected_run_id, target=expected_target)
    result = _json_read(
        root / "history-plan.json", HistoryPlanRecord, known_records=known_records
    )
    if (
        result.identity.target_trade_date != expected_target
        or result.identity.creator_run_id != expected_run_id
    ):
        raise ValueError("历史计划不对应原T/run")
    return result


def read_stk_factor_pro_referenced_history_plan(
    *, staging_root, target, contract, reference, known_records
):
    if reference.relative_path != "history-plan.json":
        raise ValueError("原历史计划引用必须是固定history-plan.json")
    root = stk_factor_pro_run_staging_root(
        staging_root, reference.creator_run_id, target.isoformat()
    )
    record = read_stk_factor_pro_history_plan(
        root,
        expected_target=target,
        expected_run_id=reference.creator_run_id,
        known_records=known_records,
    )
    _ref_path(root, record.identity, reference, known_records=known_records)
    if record.contract != contract:
        raise ValueError("原历史计划不属于本次完整契约")
    return record


def _range_row(record: HistoryRange):
    return tuple(
        json.dumps(
            stk_factor_pro_record_to_dict(record.origin_record_refs),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        if field.name == "origin_record_refs"
        else getattr(record, field.name)
        for field in fields(HistoryRange)
    )


def _decode_range(values) -> HistoryRange:
    row = dict(zip((name for name, _ in HISTORY_RANGE_SCHEMA), values, strict=True))
    origins = json.loads(row["origin_record_refs"], object_pairs_hook=_pairs)
    if type(origins) is not list:
        raise ValueError("历史来源引用必须是规范JSON数组")
    row["origin_record_refs"] = tuple(
        parse_stk_factor_pro_record(HistoryOriginRef, value) for value in origins
    )
    if (
        json.dumps(
            stk_factor_pro_record_to_dict(row["origin_record_refs"]),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        != values[9]
    ):
        raise ValueError("历史来源引用JSON表示不规范")
    row["plan_reasons"] = tuple(row["plan_reasons"])
    row["origin_target_dates"] = tuple(row["origin_target_dates"])
    return HistoryRange(**row)


def _validate_ranges(plan: HistoryPlanRecord, ranges: tuple[HistoryRange, ...]) -> None:
    if type(ranges) is not tuple or any(
        not isinstance(row, HistoryRange) for row in ranges
    ):
        raise TypeError("历史范围必须为冻结记录tuple")
    codes = tuple(row.ts_code for row in ranges)
    if codes != tuple(sorted(set(codes))) or len(codes) != plan.full_code_count:
        raise ValueError("历史范围必须按唯一代码升序且数量与完整名单一致")
    if any(
        row.end_date is not None and row.end_date != plan.identity.target_trade_date
        for row in ranges
    ):
        raise ValueError("历史范围结束日必须为原T")
    ranges_digest = stk_factor_pro_history_ranges_digest(ranges)
    if ranges_digest != plan.history_ranges_digest or (
        stk_factor_pro_history_plan_digest(
            plan.identity, plan.contract, ranges, ranges_digest=ranges_digest
        )
        != plan.history_plan_digest
    ):
        raise ValueError("历史计划/范围业务摘要读回不符")


def read_stk_factor_pro_history_ranges(
    connection, *, root: Path, plan: HistoryPlanRecord, known_records: dict
) -> tuple[HistoryRange, ...]:
    path = _ref_path(root, plan.identity, plan.ranges_ref, known_records=known_records)
    if known_records[path][0] is not None:
        return known_records[path][0]
    result = tuple(
        _decode_range(row)
        for row in _read_rows(
            connection, path, HISTORY_RANGE_SCHEMA, known_records=known_records
        )
    )
    _validate_ranges(plan, result)
    known_records[path] = (result, *known_records[path][1:])
    return result


def write_stk_factor_pro_history_plan(
    root: Path,
    record: HistoryPlanRecord,
    ranges: tuple[HistoryRange, ...],
    *,
    connection,
    known_records: dict,
) -> tuple[HistoryPlanRecord, str]:
    _validate_ranges(record, ranges)
    return _write_verified_history_plan(
        root, record, ranges, connection=connection, known_records=known_records
    )


def _write_verified_history_plan(
    root: Path,
    record: HistoryPlanRecord,
    ranges: tuple[HistoryRange, ...],
    *,
    connection,
    known_records: dict,
) -> tuple[HistoryPlanRecord, str]:
    """Save the already validated plan without repeating its business digests."""
    # Check both names before writing a new immutable plan; no old range reuse.
    for relative in ("history-plan.json", "history-ranges.parquet"):
        path = _path(root, record.identity, relative)
        if path.exists():
            raise ValueError("历史计划或范围已存在，不接受覆盖")
    reference = _write_rows(
        connection,
        root,
        record.identity,
        "history-ranges.parquet",
        HISTORY_RANGE_SCHEMA,
        tuple(_range_row(row) for row in ranges),
        _decode_range,
        known_records=known_records,
        check_space=None,
    )
    saved = replace(record, ranges_ref=reference)
    known_records[root / reference.relative_path] = (
        ranges,
        *known_records[root / reference.relative_path][1:],
    )
    plan_ref = _json_write(
        root,
        record.identity,
        "history-plan.json",
        saved,
        known_records=known_records,
        check_space=None,
    )
    return saved, plan_ref.file_sha256


def _decode_source_file(values) -> SourceFileRecord:
    row = dict(zip((name for name, _ in SOURCE_FILE_SCHEMA), values, strict=True))
    if row["verified_at"] is not None:
        row["verified_at"] = row["verified_at"].astimezone(
            ZoneInfo(STK_FACTOR_PRO_TIMEZONE)
        )
    return SourceFileRecord(**row)


def _validate_source_files(
    identity: RunIdentity,
    contract: ContractIdentity,
    files: tuple[SourceFileRecord, ...],
) -> None:
    if type(files) is not tuple or any(
        not isinstance(row, SourceFileRecord) for row in files
    ):
        raise TypeError("历史manifest必须为冻结记录tuple")
    keys = tuple(row.unit_key for row in files)
    if keys != tuple(sorted(set(keys))):
        raise ValueError("历史manifest必须按唯一unit_key排序")
    if any(
        row.end_date != identity.target_trade_date
        or row.contract_content_digest != contract.contract_content_digest
        for row in files
    ):
        raise ValueError("历史manifest日期/合同身份不符")


def write_stk_factor_pro_source_files(
    root: Path,
    *,
    connection,
    identity: RunIdentity,
    contract: ContractIdentity,
    files: tuple[SourceFileRecord, ...],
    known_records: dict,
    check_space: Callable,
) -> RecordRef:
    _validate_source_files(identity, contract, files)
    rows = tuple(
        tuple(getattr(row, field.name) for field in fields(SourceFileRecord))
        for row in files
    )
    return _write_rows(
        connection,
        root,
        identity,
        "source/history/source-files.parquet",
        SOURCE_FILE_SCHEMA,
        rows,
        _decode_source_file,
        known_records=known_records,
        check_space=check_space,
    )


def read_stk_factor_pro_source_files(
    root: Path,
    reference: RecordRef,
    *,
    connection,
    identity: RunIdentity,
    contract: ContractIdentity,
    known_records: dict,
) -> tuple[SourceFileRecord, ...]:
    if reference.relative_path != "source/history/source-files.parquet":
        raise ValueError("历史manifest必须使用固定相对路径")
    path = _ref_path(root, identity, reference, known_records=known_records)
    if known_records[path][0] is not None:
        return known_records[path][0]
    result = tuple(
        _decode_source_file(row)
        for row in _read_rows(
            connection, path, SOURCE_FILE_SCHEMA, known_records=known_records
        )
    )
    _validate_source_files(identity, contract, result)
    known_records[path] = (result, *known_records[path][1:])
    return result


def write_stk_factor_pro_source_complete(
    root: Path,
    record: SourceCompleteRecord,
    *,
    known_records: dict,
    check_space: Callable,
) -> tuple[SourceCompleteRecord, str]:
    reference = _json_write(
        root,
        record.identity,
        "source/history/source-complete.json",
        record,
        known_records=known_records,
        check_space=check_space,
    )
    return record, reference.file_sha256


def verify_stk_factor_pro_current_source(
    root: Path,
    record: SourceCompleteRecord,
    *,
    connection,
    current_run_id: str,
    expected_units: tuple[UnitProjection, ...],
    source_complete_ref: RecordRef,
    known_records: dict,
    source_relation: str,
    verified_files: tuple[SourceFileRecord, ...],
    file_identities: tuple[tuple[str, tuple[int, int, int, int, int]], ...],
) -> VerifiedSource:
    """Assemble first audited unit facts; never re-open source data or records."""
    if (
        not isinstance(record, SourceCompleteRecord)
        or record.identity.creator_run_id != current_run_id
        or record.expected_units != expected_units
        or source_relation != "stk_factor_pro_history_source"
    ):
        raise ValueError("历史源必须属于当前run且逐项覆盖本次expected_units")
    if record.contract != ContractIdentity(
        "stk_factor_pro",
        "1",
        content_digest(STK_FACTOR_PRO_CONTRACT),
        STK_FACTOR_PRO_PROCESSING_VERSION,
    ):
        raise ValueError("历史源与当前登记契约不符")
    verified = VerifiedSource(
        record.identity,
        record.contract,
        record,
        source_complete_ref,
        source_relation,
        verified_files,
        file_identities,
    )
    for reference, expected in (
        (source_complete_ref, record),
        (record.files_manifest_ref, verified_files),
    ):
        path = _path(root, record.identity, reference.relative_path)
        fact = known_records.get(path)
        if (
            reference.creator_run_id != current_run_id
            or fact is None
            or fact[0] != expected
            or fact[1] != reference.file_sha256
        ):
            raise ValueError("历史源完整记录或manifest未交接首次保存事实")
    if source_complete_ref.relative_path != "source/history/source-complete.json":
        raise ValueError("历史源完整引用不是当前run固定路径")
    plan_fact = known_records.get(root / "history-plan.json")
    if plan_fact is None or plan_fact[1] != record.history_plan_ref.file_sha256:
        raise ValueError("历史源计划未交接首次摘要")
    plan = plan_fact[0]
    if (
        not isinstance(plan, HistoryPlanRecord)
        or plan.identity != record.identity
        or plan.contract != record.contract
        or (
            plan.history_plan_digest,
            plan.revision,
            plan.origin_history_plan_digest,
            plan.origin_history_ranges_digest,
        )
        != (
            record.history_plan_digest,
            record.history_plan_revision,
            record.origin_history_plan_digest,
            record.origin_history_ranges_digest,
        )
    ):
        raise ValueError("历史源与原完整计划的身份/版本/授权不符")
    range_fact = known_records.get(root / plan.ranges_ref.relative_path)
    if range_fact is None or range_fact[1] != plan.ranges_ref.file_sha256:
        raise ValueError("历史源范围未交接首次事实")
    by_key = {stk_factor_pro_unit_key(unit): unit for unit in expected_units}
    if (
        type(verified_files) is not tuple
        or len(verified_files) != record.completed_unit_count
        or {file.unit_key for file in verified_files} != set(by_key)
    ):
        raise ValueError("历史manifest没有逐项覆盖全部expected_units")
    if tuple(value[0] for value in file_identities) != tuple(
        file.file_relative_path for file in verified_files
    ):
        raise ValueError("历史manifest文件identity没有逐项对应")
    for file, (_, identity) in zip(verified_files, file_identities, strict=True):
        unit = UnitProjection(
            file.mode, file.object_code, file.point, file.start_date, file.end_date
        )
        fact = known_records.get(root / file.file_relative_path)
        if unit != by_key[file.unit_key] or fact != (file, file.file_sha256, identity):
            raise ValueError("历史unit未交接当前run首次审计事实")
        path = _path(root, record.identity, file.file_relative_path)
        if factor_file_identity(path) != identity:
            raise ValueError("历史unit源文件identity在首次保存后改变")
    return verified


def resolve_stk_factor_pro_history_starts(
    connection,
    *,
    lake_root: Path,
    target_trade_date: date,
    codes: tuple[str, ...],
    known_starts: tuple[StkFactorProHistoryStart, ...],
    approved_raw_dates: tuple[date, ...],
    check_cancel,
    known_records: dict,
) -> tuple[StkFactorProHistoryStart, ...]:
    """Resolve only missing boundaries, within the caller's trusted date set."""
    if type(target_trade_date) is not date or type(codes) is not tuple:
        raise ValueError("历史起点必须使用DATE和明确代码tuple")
    if len(set(codes)) != len(codes):
        raise ValueError("历史起点请求代码重复")
    for code in codes:
        StkFactorProHistoryStart(code, None, None, None)
    if type(known_starts) is not tuple or any(
        not isinstance(item, StkFactorProHistoryStart) for item in known_starts
    ):
        raise TypeError("可信历史起点必须为冻结记录tuple")
    if len({item.ts_code for item in known_starts}) != len(known_starts):
        raise ValueError("可信历史起点代码重复")
    if any(
        item.start_date is not None and item.start_date > target_trade_date
        for item in known_starts
    ):
        raise ValueError("可信历史起点不得晚于原目标日")
    if (
        type(approved_raw_dates) is not tuple
        or any(
            type(day) is not date or day > target_trade_date
            for day in approved_raw_dates
        )
        or len(set(approved_raw_dates)) != len(approved_raw_dates)
    ):
        raise ValueError("已批准Raw日期必须为不晚于原T的唯一DATE集合")
    require_stk_factor_pro_safe_path(lake_root)
    known = {item.ts_code: item for item in known_starts}
    unknown = tuple(
        sorted(
            code
            for code in codes
            if code not in known or known[code].start_date is None
        )
    )
    check_cancel()
    # Trusted earlier boundaries never depend on a newer/irrelevant file set.
    if unknown and approved_raw_dates:
        dates = tuple(sorted(approved_raw_dates))
        paths = tuple(
            raw_stk_factor_pro_path(lake_root, day.isoformat()) for day in dates
        )
        unverified_paths = []
        for day, path in zip(dates, paths, strict=True):
            require_stk_factor_pro_safe_path(path)
            if not path.is_file():
                raise ValueError("已批准可信Raw文件缺失，不能据剩余文件推算最早日期")
            fact = known_records.get(path)
            audit = fact[0] if fact is not None else None
            if (
                isinstance(audit, C.StkFactorProFileAudit)
                and audit.passed
                and audit.layer == "raw"
                and audit.trade_date == day
                and audit.path == path
            ):
                if factor_file_identity(path) != fact[2]:
                    raise ValueError("可信Raw文件在任务内改变，不能计算历史起点")
            else:
                unverified_paths.append(str(path))
        if unverified_paths:
            schemas = connection.execute(
                "SELECT file_name,list(name ORDER BY name),list(duckdb_type ORDER BY name) "
                "FROM parquet_schema(?) WHERE column_id>0 "
                "AND name IN ('trade_date','ts_code') GROUP BY file_name",
                [unverified_paths],
            ).fetchall()
            if {row[0] for row in schemas} != set(unverified_paths) or any(
                names != ["trade_date", "ts_code"] or types != ["VARCHAR", "VARCHAR"]
                for _, names, types in schemas
            ):
                raise ValueError("可信Raw主键字段类型不符合源表示")
        check_cancel()
        # One column-pruned, code-bounded aggregate for all unresolved stocks.
        rows = connection.execute(
            "WITH approved_files AS (SELECT unnest(?::VARCHAR[]) AS filename, "
            "unnest(?::VARCHAR[]) AS wanted_date), scoped AS ("
            "SELECT r.ts_code,r.trade_date,a.wanted_date FROM "
            "read_parquet(?,filename=true,hive_partitioning=false) r "
            "LEFT JOIN approved_files a USING(filename) WHERE r.ts_code=ANY(?)) "
            "SELECT ts_code,min(CAST(try_strptime(trade_date,'%Y%m%d') AS DATE)), "
            "count(*) FILTER (WHERE trade_date IS NULL OR "
            "NOT regexp_full_match(trade_date,'[0-9]{8}') OR "
            "try_strptime(trade_date,'%Y%m%d') IS NULL OR wanted_date IS NULL OR "
            "trade_date IS DISTINCT FROM replace(wanted_date,'-','')) "
            "FROM scoped GROUP BY ts_code ORDER BY ts_code",
            [
                [str(path) for path in paths],
                [day.isoformat() for day in dates],
                [str(path) for path in paths],
                list(unknown),
            ],
        ).fetchall()
        if any(bad for _, _, bad in rows):
            raise ValueError("可信Raw日期非法或与批准文件日期不符，不能计算历史起点")
        for code, first, _ in rows:
            if first is not None:
                known[code] = StkFactorProHistoryStart(code, first, 1, first)
        check_cancel()
    return tuple(
        known.get(code, StkFactorProHistoryStart(code, None, None, None))
        for code in sorted(codes)
    )


def _read_history_factor(connection, *, lake_root, reference, relation, known_records):
    if not isinstance(reference, FactorFileRef):
        raise TypeError("历史规划必须使用权威因子引用")
    path = raw_adj_factor_path(lake_root, reference.trade_date.isoformat())
    require_stk_factor_pro_safe_path(path)
    if (
        factor_known_file_sha(path, known_records=known_records)
        != reference.file_sha256
    ):
        raise ValueError("历史规划权威因子文件缺失或SHA不符")
    prior = known_records[path][0]
    if type(prior) is tuple and len(prior) == 3:
        if prior[1] != reference.rows:
            raise ValueError("历史规划权威因子行数不符")
        return prior[0]
    connection.execute(
        f"CREATE TEMP TABLE {relation} AS SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
    )
    schema = tuple(
        (row[0], row[1])
        for row in connection.execute(f"DESCRIBE {relation}").fetchall()
    )
    if schema != tuple((c.name, c.type) for c in RAW_TUSHARE_ADJ_FACTOR_SCHEMA):
        raise ValueError("历史规划权威因子列名/顺序/类型与完整合同不符")
    count, bad = connection.execute(
        f"SELECT count(*),count(*) FILTER (WHERE ts_code IS NULL OR NOT regexp_full_match(ts_code,'[0-9]{{6}}\\.(SH|SZ|BJ)') "
        "OR trade_date IS DISTINCT FROM ? OR adj_factor IS NULL OR NOT isfinite(adj_factor) OR adj_factor<=0) "
        f"FROM {relation}",
        [reference.trade_date.strftime("%Y%m%d")],
    ).fetchone()
    duplicates = connection.execute(
        f"SELECT count(*) FROM (SELECT ts_code FROM {relation} GROUP BY ts_code HAVING count(*)>1)"
    ).fetchone()[0]
    if count != reference.rows or count == 0 or bad or duplicates:
        raise ValueError("历史规划权威因子行数/非空/股票/日期/正值/唯一键检查不符")
    if factor_file_identity(path) != known_records[path][2]:
        raise ValueError("历史规划权威因子文件在读取期间改变")
    known_records[path] = (
        (relation, count, schema),
        reference.file_sha256,
        known_records[path][2],
    )
    return relation


def release_stk_factor_pro_history_inputs(connection, primary=None):
    failures = []
    for relation in (
        "stk_factor_pro_history_factor_t",
        "stk_factor_pro_history_factor_p",
        "stk_factor_pro_history_lifecycle",
    ):
        try:
            connection.execute(f"DROP TABLE IF EXISTS {relation}")
        except BaseException as error:  # noqa: BLE001 -- release all owned inputs, preserving the initial task failure.
            failures.append(error)
    if failures:
        reported = primary if primary is not None else failures[0]
        for error in failures:
            reported.add_note(f"历史输入关系清理同时失败：{type(error).__name__}")
        if primary is None:
            raise reported


def prepare_stk_factor_pro_history_inputs(
    connection, *, identity, lake_root, factor_t, factor_p, known_records, check_cancel
):
    """First local input read; callers keep these relations through their last use."""
    if (
        not isinstance(identity, RunIdentity)
        or not isinstance(factor_t, FactorFileRef)
        or not isinstance(factor_p, FactorFileRef)
    ):
        raise TypeError("历史输入准备必须接收原执行身份及权威因子引用")
    if (factor_t.trade_date, factor_p.trade_date) != (
        identity.target_trade_date,
        identity.previous_trade_date,
    ):
        raise ValueError("历史规划权威因子不是原T/P")
    try:
        check_cancel()
        t_relation = _read_history_factor(
            connection,
            lake_root=lake_root,
            reference=factor_t,
            relation="stk_factor_pro_history_factor_t",
            known_records=known_records,
        )
        check_cancel()
        p_relation = _read_history_factor(
            connection,
            lake_root=lake_root,
            reference=factor_p,
            relation="stk_factor_pro_history_factor_p",
            known_records=known_records,
        )
        path = silver_stock_lifecycle_path(lake_root)
        require_stk_factor_pro_safe_path(path)
        digest = factor_known_file_sha(path, known_records=known_records)
        lifecycle_relation = None
        if digest is not None:
            prior = known_records[path][0]
            if type(prior) is tuple and len(prior) == 3:
                lifecycle_relation = prior[0]
            else:
                lifecycle_relation = "stk_factor_pro_history_lifecycle"
                connection.execute(
                    f"CREATE TEMP TABLE {lifecycle_relation} AS SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
                )
                schema = tuple(
                    (row[0], row[1])
                    for row in connection.execute(
                        f"DESCRIBE {lifecycle_relation}"
                    ).fetchall()
                )
                count = connection.execute(
                    f"SELECT count(*) FROM {lifecycle_relation}"
                ).fetchone()[0]
                if schema != tuple(
                    (c.name, c.type) for c in SILVER_STOCK_LIFECYCLE_SCHEMA
                ):
                    connection.execute(f"DROP TABLE {lifecycle_relation}")
                    lifecycle_relation = None
                if factor_file_identity(path) != known_records[path][2]:
                    raise ValueError("历史规划生命周期文件在读取期间改变")
                known_records[path] = (
                    (lifecycle_relation, count, schema),
                    digest,
                    known_records[path][2],
                )
        check_cancel()
        return (t_relation, p_relation), lifecycle_relation
    except BaseException as error:
        release_stk_factor_pro_history_inputs(connection, error)
        raise


def read_stk_factor_pro_prior_history(
    connection, *, staging_root, target, contract, prior, known_records
):
    """Exact old work records only; never inspect old downloaded unit files."""
    plans = {}

    def load_plan(reference):
        if reference in plans:
            return plans[reference]
        record = read_stk_factor_pro_referenced_history_plan(
            staging_root=staging_root,
            target=target,
            contract=contract,
            reference=reference,
            known_records=known_records,
        )
        root = stk_factor_pro_run_staging_root(
            staging_root, reference.creator_run_id, target.isoformat()
        )
        rows = read_stk_factor_pro_history_ranges(
            connection, root=root, plan=record, known_records=known_records
        )
        plans[reference] = record, rows
        return record, rows

    if prior.history_ranges_ref is not None and prior.history_plan_ref is None:
        raise ValueError("原范围有引用但缺少完整计划")
    refs = (
        () if prior.history_plan_ref is None else (prior.history_plan_ref,)
    ) + prior.pending_plan_refs
    for ref in refs:
        record, _ = load_plan(ref)
        if (
            ref == prior.history_plan_ref
            and prior.history_ranges_ref is not None
            and prior.history_ranges_ref != record.ranges_ref
        ):
            raise ValueError("原完整计划和范围引用不对应")
    for ref in prior.successful_publication_refs:
        root = stk_factor_pro_run_staging_root(
            staging_root, ref.creator_run_id, target.isoformat()
        )
        _run_root(root, run_id=ref.creator_run_id, target=target)
        path = root / ref.relative_path
        require_stk_factor_pro_safe_path(path)
        if ref.relative_path != "publication/history/publication-complete.json":
            raise ValueError("原历史成功引用缺失、SHA不符或路径错误")
        published = _json_read(
            path, PublicationCompleteRecord, known_records=known_records
        )
        _ref_path(root, published.identity, ref, known_records=known_records)
        if (
            published.phase != "history"
            or published.identity.creator_run_id != ref.creator_run_id
            or published.identity.target_trade_date != target
            or published.contract != contract
        ):
            raise ValueError("原历史成功记录日期/run/合同不符")
        path = root / "history-plan.json"
        require_stk_factor_pro_safe_path(path)
        read_stk_factor_pro_history_plan(
            root,
            expected_target=target,
            expected_run_id=ref.creator_run_id,
            known_records=known_records,
        )
        record, _ = load_plan(
            RecordRef(ref.creator_run_id, "history-plan.json", known_records[path][1])
        )
        if (
            record.identity,
            record.history_plan_digest,
            record.history_ranges_digest,
        ) != (
            published.identity,
            published.history_plan_digest,
            published.history_ranges_digest,
        ):
            raise ValueError("原历史成功记录和完整计划不对应")
    return plans, load_plan


def stk_factor_pro_codes_without_history_starts(
    *,
    factor_comparison,
    prior_results,
    prior_history,
) -> tuple[str, ...]:
    """Find only missing boundaries in the plan that this run will build."""
    observed = {code for code, *_ in factor_comparison}
    needed = {
        code
        for code, current, previous, t_present, p_present in factor_comparison
        if not (t_present and p_present) or current != previous
    }
    pending = set(prior_results.pending_plan_refs)
    known = set()
    for ref, (_, ranges) in prior_history[0].items():
        for row in ranges:
            if row.start_date is not None:
                known.add(row.ts_code)
            if (
                ref in pending
                or row.ts_code not in observed
                or any(
                    reason
                    in (
                        HistoryPlanReason.FACTOR_CHANGED,
                        HistoryPlanReason.PRIOR_UNFINISHED,
                    )
                    for reason in row.plan_reasons
                )
            ):
                needed.add(row.ts_code)
    return tuple(sorted(needed - known))


def _history_lifecycle(connection, *, relation, codes, target):
    if not codes or relation is None:
        return {}
    rows = connection.execute(
        f"SELECT ts_code,list_date,delist_date,curr_type,is_cny_stock FROM {relation} WHERE ts_code=ANY(?) ORDER BY ts_code",
        [list(codes)],
    ).fetchall()
    counts = {}
    for row in rows:
        counts[row[0]] = counts.get(row[0], 0) + 1
    return {
        code: (listed, delisted)
        for code, listed, delisted, currency, cny in rows
        if counts[code] == 1
        and currency == "CNY"
        and cny is True
        and type(listed) is date
        and listed <= target
        and (delisted is None or (type(delisted) is date and delisted > listed))
    }


def compare_stk_factor_pro_history_factors(connection, *, factor_relations):
    """One T/P comparison, shared by earliest-date selection and plan creation."""
    t_relation, p_relation = map(relation_identifier, factor_relations)
    return tuple(
        connection.execute(
            f"SELECT coalesce(t.ts_code,p.ts_code),t.adj_factor,p.adj_factor,t.ts_code IS NOT NULL,p.ts_code IS NOT NULL FROM {t_relation} t FULL OUTER JOIN {p_relation} p USING(ts_code) ORDER BY 1"
        ).fetchall()
    )


def build_stk_factor_pro_history_plan(
    connection,
    *,
    identity: RunIdentity,
    contract: ContractIdentity,
    lake_root: Path,
    staging_root: Path,
    factor_t: FactorFileRef,
    factor_p: FactorFileRef,
    factor_relations: tuple[str, str],
    factor_comparison: tuple,
    lifecycle_relation: str | None,
    prior_results: StkFactorProRecordedResults,
    prior_history: tuple[dict, Callable],
    history_starts: tuple[StkFactorProHistoryStart, ...],
    check_cancel,
    known_records: dict,
    factor_revised: bool = False,
) -> tuple[HistoryPlanRecord, tuple[HistoryRange, ...], RecordRef]:
    if not isinstance(identity, RunIdentity) or not isinstance(
        prior_results, StkFactorProRecordedResults
    ):
        raise TypeError("历史规划必须接收冻结身份及已核历史结果")
    if contract != ContractIdentity(
        "stk_factor_pro",
        "1",
        content_digest(STK_FACTOR_PRO_CONTRACT),
        STK_FACTOR_PRO_PROCESSING_VERSION,
    ):
        raise ValueError("历史规划与当前登记契约不符")
    if prior_results.target_trade_date != identity.target_trade_date:
        raise ValueError("原历史结果不是同一目标T")
    if type(history_starts) is not tuple or any(
        not isinstance(r, StkFactorProHistoryStart) for r in history_starts
    ):
        raise TypeError("历史起点必须是冻结记录tuple")
    if len({r.ts_code for r in history_starts}) != len(history_starts) or any(
        r.start_date is not None and r.start_date > identity.target_trade_date
        for r in history_starts
    ):
        raise ValueError("历史起点重复或晚于原T")
    if not isinstance(factor_t, FactorFileRef) or not isinstance(
        factor_p, FactorFileRef
    ):
        raise TypeError("历史规划必须接收权威因子的冻结文件引用")
    if (factor_t.trade_date, factor_p.trade_date) != (
        identity.target_trade_date,
        identity.previous_trade_date,
    ):
        raise ValueError("历史规划权威因子不是原T/P")
    root = stk_factor_pro_run_staging_root(
        staging_root, identity.creator_run_id, identity.target_trade_date.isoformat()
    )
    _run_root(root, run_id=identity.creator_run_id, target=identity.target_trade_date)
    require_stk_factor_pro_safe_path(lake_root)
    check_cancel()
    plans, load_plan = prior_history
    authorized, origin_ref = None, None
    if identity.purpose == "manual_repair":
        source_refs = [
            ref for ref in plans if ref.creator_run_id == identity.source_run_id
        ]
        if not source_refs:
            raise ValueError("手动repair必须引用已核原完整授权计划")
        source_ref = source_refs[0]
        source_plan, _ = plans[source_ref]
        origin_ref = source_plan.origin_plan_ref or source_ref
        origin_plan, authorized = load_plan(origin_ref)
        if source_plan.origin_plan_ref is not None and (
            source_plan.origin_history_plan_digest,
            source_plan.origin_history_ranges_digest,
        ) != (origin_plan.history_plan_digest, origin_plan.history_ranges_digest):
            raise ValueError("手动repair原完整授权摘要不符")
    automatic_today = identity.purpose == "today" and identity.source_run_id is None
    pending = set()
    pending_revisions = set()
    for ref in prior_results.pending_plan_refs:
        for row in plans[ref][1]:
            pending.add(row.ts_code)
            if HistoryPlanReason.SAME_NIGHT_FACTOR_REVISION in row.plan_reasons:
                pending_revisions.add(row.ts_code)
    old = {}
    for reference, (_, rows) in plans.items():
        for row in rows:
            old.setdefault(row.ts_code, []).append((reference, row))
    starts = {r.ts_code: r for r in history_starts}
    if type(factor_relations) is not tuple or len(factor_relations) != 2:
        raise TypeError("历史规划必须接收首次已核T/P关系")
    t_relation, p_relation = factor_relations
    for reference, relation in ((factor_t, t_relation), (factor_p, p_relation)):
        path = raw_adj_factor_path(lake_root, reference.trade_date.isoformat())
        fact = known_records.get(path)
        if (
            fact is None
            or fact[1] != reference.file_sha256
            or fact[0][0] != relation
            or fact[0][1] != reference.rows
        ):
            raise ValueError("历史规划未交接首次权威因子事实")
    life_fact = known_records.get(silver_stock_lifecycle_path(lake_root))
    if (
        life_fact is None
        or (life_fact[0][0] if life_fact[0] is not None else None) != lifecycle_relation
    ):
        raise ValueError("历史规划未交接首次生命周期事实")
    compared = factor_comparison
    factors = {code: (tv, pv, tp, pp) for code, tv, pv, tp, pp in compared}
    codes = set(factors) | set(old) | set(starts)
    if authorized is not None:
        codes = {r.ts_code for r in authorized}
        pending.update(codes)
    missing = tuple(
        sorted(
            code
            for code in codes
            if code not in factors
            or not all(factors[code][2:])
            or (code in starts and starts[code].start_date is None)
        )
    )
    lifecycle = _history_lifecycle(
        connection,
        relation=lifecycle_relation,
        codes=missing,
        target=identity.target_trade_date,
    )
    authorized_by_code = (
        {} if authorized is None else {r.ts_code: r for r in authorized}
    )
    result = []
    for code in sorted(codes):
        tv, pv, tp, pp = factors.get(code, (None, None, False, False))
        previous = old.get(code, ())
        reasons = {
            int(reason)
            for _, r in previous
            for reason in r.plan_reasons
            if int(reason) in (1, 2)
        }
        if tp and pp and tv != pv:
            reasons.add(int(HistoryPlanReason.FACTOR_CHANGED))
        if code in pending:
            reasons.add(int(HistoryPlanReason.PRIOR_UNFINISHED))
        if not tp and not pp:
            reasons.add(int(HistoryPlanReason.BOTH_FACTORS_MISSING))
        elif not tp:
            reasons.add(int(HistoryPlanReason.TARGET_FACTOR_MISSING))
        elif not pp:
            reasons.add(int(HistoryPlanReason.PREVIOUS_FACTOR_MISSING))
        if not reasons:
            continue
        known = [
            r for r in (starts.get(code),) if r is not None and r.start_date is not None
        ]
        known.extend(
            StkFactorProHistoryStart(
                code, r.start_date, r.earliest_basis_kind, r.earliest_basis_date
            )
            for _, r in previous
            if r.start_date is not None
        )
        chosen = (
            min(known, key=lambda r: (r.start_date, r.earliest_basis_kind))
            if known
            else StkFactorProHistoryStart(code, None, None, None)
        )
        if authorized is not None:
            original = authorized_by_code[code]
            chosen = StkFactorProHistoryStart(
                code,
                original.start_date,
                original.earliest_basis_kind,
                original.earliest_basis_date,
            )
        life = lifecycle.get(code)
        if (
            tp
            and not pp
            and chosen.start_date in (None, identity.target_trade_date)
            and life is not None
            and identity.previous_trade_date < life[0] <= identity.target_trade_date
            and (life[1] is None or life[1] > identity.target_trade_date)
        ):
            reasons.add(int(HistoryPlanReason.NO_PRIOR_HISTORY))
        if (
            automatic_today
            and (factor_revised or code in pending_revisions)
            and HistoryPlanReason.NO_PRIOR_HISTORY not in reasons
        ):
            reasons.add(int(HistoryPlanReason.SAME_NIGHT_FACTOR_REVISION))
        origin_dates, origin_refs = {identity.target_trade_date}, set()
        for reference, r in previous:
            origin_dates.update(r.origin_target_dates)
            origin_refs.update(r.origin_record_refs)
            origin_refs.add(
                HistoryOriginRef(
                    identity.target_trade_date,
                    reference.creator_run_id,
                    reference.relative_path,
                    reference.file_sha256,
                )
            )
        result.append(
            HistoryRange(
                code,
                tp,
                pp,
                tv,
                pv,
                chosen.start_date,
                identity.target_trade_date if chosen.start_date is not None else None,
                tuple(sorted(reasons)),
                tuple(sorted(origin_dates)),
                tuple(
                    sorted(
                        origin_refs,
                        key=lambda ref: (
                            ref.T,
                            ref.run,
                            ref.relative_path,
                            ref.file_sha,
                        ),
                    )
                ),
                chosen.earliest_basis_kind,
                chosen.earliest_basis_date,
            )
        )
    ranges = tuple(result)
    ranges_digest = stk_factor_pro_history_ranges_digest(ranges)
    plan_digest = stk_factor_pro_history_plan_digest(
        identity, contract, ranges, ranges_digest=ranges_digest
    )
    latest_ref = prior_results.history_plan_ref
    if latest_ref is None and plans:
        latest_ref = max(
            plans,
            key=lambda ref: (
                plans[ref][0].revision,
                plans[ref][0].created_at,
                ref.creator_run_id,
            ),
        )
    latest = plans[latest_ref][0] if latest_ref is not None else None
    revision = (
        1
        if latest is None
        else latest.revision + int(latest.history_plan_digest != plan_digest)
    )
    revision_of = (
        None
        if latest is None
        else latest.revision_of
        if latest.history_plan_digest == plan_digest
        else latest_ref
    )
    check_cancel()
    plan = HistoryPlanRecord(
        1,
        identity,
        contract,
        revision,
        datetime.now(ZoneInfo(STK_FACTOR_PRO_TIMEZONE)),
        plan_digest,
        ranges_digest,
        RecordRef(identity.creator_run_id, "history-ranges.parquet", "0" * 64),
        len(ranges),
        factor_t,
        factor_p,
        revision_of,
        origin_ref,
        None if origin_ref is None else plans[origin_ref][0].history_plan_digest,
        None if origin_ref is None else plans[origin_ref][0].history_ranges_digest,
    )
    saved, digest = _write_verified_history_plan(
        root, plan, ranges, connection=connection, known_records=known_records
    )
    return (
        saved,
        ranges,
        RecordRef(identity.creator_run_id, "history-plan.json", digest),
    )


def _require_registered_history_plan(plan, ranges):
    if not isinstance(plan, HistoryPlanRecord):
        raise TypeError("历史处理必须接收冻结的完整计划")
    if plan.contract != ContractIdentity(
        "stk_factor_pro",
        "1",
        content_digest(STK_FACTOR_PRO_CONTRACT),
        STK_FACTOR_PRO_PROCESSING_VERSION,
    ):
        raise ValueError("历史处理计划不是当前登记的完整契约")
    if type(ranges) is not tuple or any(
        not isinstance(row, HistoryRange) for row in ranges
    ):
        raise TypeError("历史处理必须接收已核冻结范围tuple")


def plan_stk_factor_pro_history_publication_dates(
    *,
    identity: RunIdentity,
    expected_units: tuple[UnitProjection, ...],
    calendar: tuple[date, ...],
    registered_dates: tuple[date, ...],
) -> tuple[date, ...]:
    """Plan the registered d<T trading dates once before history download."""
    for values in (calendar, registered_dates):
        if (
            type(values) is not tuple
            or any(type(day) is not date for day in values)
            or tuple(sorted(set(values))) != values
        ):
            raise ValueError("历史日历/已登记分区必须是升序唯一DATE tuple")
    if (
        identity.target_trade_date not in calendar
        or identity.previous_trade_date not in calendar
        or any(unit.start_date not in calendar for unit in expected_units)
    ):
        raise ValueError("历史日历未覆盖原T/P及已批准的真实最早日期")
    dates = tuple(
        day
        for day in calendar
        if day < identity.target_trade_date
        and any(unit.start_date <= day <= unit.end_date for unit in expected_units)
    )
    if set(dates) - set(registered_dates):
        raise ValueError("历史发布日期尚未登记分区，禁止提升")
    return dates


def _history_units_for_ranges(plan, ranges):
    """Keep an unexplained object from disappearing behind a WHERE filter."""
    result = []
    for row in ranges:
        if int(HistoryPlanReason.NO_PRIOR_HISTORY) in row.plan_reasons:
            if (
                not row.t_present
                or row.p_present
                or row.t_value <= 0
                or row.start_date not in (None, plan.identity.target_trade_date)
            ):
                raise ValueError("无原历史原因与当前股票因子/可信起点矛盾")
            continue
        if (
            not row.t_present
            or not row.p_present
            or row.t_value <= 0
            or row.p_value <= 0
            or row.start_date is None
            or row.end_date != plan.identity.target_trade_date
        ):
            raise ValueError(f"历史完整范围尚未判明：{row.ts_code}；因子或最早日期缺失")
        result.append(
            UnitProjection(5, row.ts_code, None, row.start_date, row.end_date)
        )
    return tuple(result)


def _check_history_unit_subset(plan, ranges, units):
    if type(units) is not tuple or any(
        not isinstance(unit, UnitProjection) for unit in units
    ):
        raise TypeError("历史请求范围必须是冻结unit tuple")
    known = {unit.object_code: unit for unit in _history_units_for_ranges(plan, ranges)}
    keys = tuple((unit.object_code, unit.start_date, unit.end_date) for unit in units)
    if keys != tuple(sorted(set(keys))) or len(
        {unit.object_code for unit in units}
    ) != len(units):
        raise ValueError("历史请求unit必须按唯一代码及起止升序")
    if any(known.get(unit.object_code) != unit for unit in units):
        raise ValueError("历史请求unit不属于当前完整原范围")


def resolve_stk_factor_pro_history_units(
    connection,
    *,
    plan: HistoryPlanRecord,
    ranges: tuple[HistoryRange, ...],
    prior_results: StkFactorProRecordedResults,
    staging_root: Path,
    known_records: dict,
) -> tuple[UnitProjection, ...]:
    """Exclude only verified complete prior scopes; never read their source data."""
    _require_registered_history_plan(plan, ranges)
    if not isinstance(prior_results, StkFactorProRecordedResults):
        raise TypeError("历史请求规划必须接收已核DG结果")
    if prior_results.target_trade_date != plan.identity.target_trade_date:
        raise ValueError("历史请求规划旧结果不是原T")
    root = stk_factor_pro_run_staging_root(
        staging_root,
        plan.identity.creator_run_id,
        plan.identity.target_trade_date.isoformat(),
    )
    plan_fact = known_records.get(root / "history-plan.json")
    range_fact = known_records.get(root / "history-ranges.parquet")
    if (
        plan_fact is None
        or range_fact is None
        or plan_fact[0] != plan
        or range_fact[0] != ranges
        or range_fact[1] != plan.ranges_ref.file_sha256
    ):
        raise ValueError("历史请求规划必须使用当前run已保存读回的完整计划及范围")
    units = _history_units_for_ranges(plan, ranges)
    current = {unit.object_code: unit for unit in units}
    excluded = set()
    for reference in prior_results.successful_publication_refs:
        old_root = stk_factor_pro_run_staging_root(
            staging_root,
            reference.creator_run_id,
            plan.identity.target_trade_date.isoformat(),
        )
        _run_root(
            old_root,
            run_id=reference.creator_run_id,
            target=plan.identity.target_trade_date,
        )
        if reference.relative_path != "publication/history/publication-complete.json":
            raise ValueError("原历史成功引用不是固定完整发布记录")
        path = old_root / reference.relative_path
        require_stk_factor_pro_safe_path(path)
        published = _json_read(
            path, PublicationCompleteRecord, known_records=known_records
        )
        _ref_path(old_root, published.identity, reference, known_records=known_records)
        old_plan = read_stk_factor_pro_history_plan(
            old_root,
            expected_target=plan.identity.target_trade_date,
            expected_run_id=reference.creator_run_id,
            known_records=known_records,
        )
        old_ranges = read_stk_factor_pro_history_ranges(
            connection, root=old_root, plan=old_plan, known_records=known_records
        )
        if (
            published.phase != "history"
            or published.identity != old_plan.identity
            or published.contract != old_plan.contract
            or old_plan.contract != plan.contract
            or published.identity.previous_trade_date
            != plan.identity.previous_trade_date
            or published.history_plan_digest != old_plan.history_plan_digest
            or published.history_ranges_digest != old_plan.history_ranges_digest
        ):
            raise ValueError("原历史成功记录身份/日期/契约/完整计划不符")
        source_path = _ref_path(
            old_root,
            old_plan.identity,
            published.source_complete_ref,
            known_records=known_records,
        )
        source = _json_read(
            source_path, SourceCompleteRecord, known_records=known_records
        )
        if (
            source.identity != old_plan.identity
            or source.contract != old_plan.contract
            or source.history_plan_ref
            != RecordRef(
                reference.creator_run_id,
                "history-plan.json",
                known_records[old_root / "history-plan.json"][1],
            )
            or source.history_plan_digest != old_plan.history_plan_digest
            or source.history_plan_revision != old_plan.revision
            or source.origin_history_plan_digest != old_plan.origin_history_plan_digest
            or source.origin_history_ranges_digest
            != old_plan.origin_history_ranges_digest
            or published.scope_digest != source.scope_digest
            or published.history_input_digest != source.history_input_digest
            or published.source_manifest_digest != source.files_manifest_digest
        ):
            raise ValueError("原历史完整成功记录与原source-complete业务元数据不符")
        _check_history_unit_subset(old_plan, old_ranges, source.expected_units)
        if source.history_input_digest != stk_factor_pro_history_input_digest(
            old_plan.identity,
            old_plan.contract,
            source.expected_units,
            old_ranges,
        ):
            raise ValueError("原历史成功范围的权威业务输入摘要不符")
        # A previous scope is indivisible here: one changed member means no
        # member is excluded. Unrelated additions in the full plan do not matter.
        if all(current.get(unit.object_code) == unit for unit in source.expected_units):
            current_digest = stk_factor_pro_history_input_digest(
                plan.identity,
                plan.contract,
                source.expected_units,
                ranges,
            )
            if current_digest == source.history_input_digest:
                excluded.update(unit.object_code for unit in source.expected_units)
    return tuple(unit for unit in units if unit.object_code not in excluded)


def require_stk_factor_pro_history_eligibility(
    plan: HistoryPlanRecord,
    eligibility: HistoryEligibilityRecord,
) -> None:
    """Require supplied validated facts, without redoing PG/file evaluators."""
    if not isinstance(plan, HistoryPlanRecord) or not isinstance(
        eligibility, HistoryEligibilityRecord
    ):
        raise TypeError("历史处理必须接收冻结计划与资格结果")
    if (
        eligibility.identity != plan.identity
        or eligibility.history_plan_digest != plan.history_plan_digest
        or eligibility.history_ranges_digest != plan.history_ranges_digest
    ):
        raise ValueError("历史资格不是当前run原T及完整计划")
    raw, silver = eligibility.raw_coverage, eligibility.target_silver
    if (
        raw.target_trade_date != plan.identity.target_trade_date
        or raw.complete is not True
        or raw.raw_check_passed is not True
        or raw.raw_file_sha256 is None
        or raw.raw_materialization_storage_id is None
        or raw.raw_check_storage_id is None
    ):
        raise ValueError("原日期Raw未齐备或缺少有效文件检查记录")
    if (
        silver is None
        or silver.target_trade_date != plan.identity.target_trade_date
        or silver.ready is not True
        or silver.silver_file_sha256 is None
        or silver.current_raw_file_sha256 != raw.raw_file_sha256
        or silver.source_raw_file_sha256 != raw.raw_file_sha256
        or silver.silver_materialization_storage_id is None
        or silver.silver_check_execution_id is None
    ):
        raise ValueError("原日期Silver不可用或未对应当前Raw")


def recheck_stk_factor_pro_history_inputs(
    connection,
    *,
    plan: HistoryPlanRecord,
    ranges: tuple[HistoryRange, ...],
    expected_units: tuple[UnitProjection, ...],
    lake_root: Path,
    recheck_inputs,
    known_records: dict,
) -> tuple[
    FactorFileRef, FactorFileRef, StkFactorProRawCoverage, StkFactorProTargetSilver
]:
    """Compare first input identities and frozen results without reading source data."""
    _require_registered_history_plan(plan, ranges)
    if not expected_units:
        raise ValueError("无实际历史请求范围，不应进入历史下载或发布重查")
    facts = recheck_inputs()
    kinds = (
        FactorFileRef,
        FactorFileRef,
        StkFactorProRawCoverage,
        StkFactorProTargetSilver,
    )
    if (
        type(facts) is not tuple
        or len(facts) != 4
        or any(
            not isinstance(value, kind)
            for value, kind in zip(facts, kinds, strict=True)
        )
    ):
        raise TypeError("历史输入重查必须返回T/P及Raw/Silver四项冻结结果")
    factor_t, factor_p, raw, silver = facts
    if (factor_t.trade_date, factor_p.trade_date) != (
        plan.identity.target_trade_date,
        plan.identity.previous_trade_date,
    ):
        raise ValueError("历史输入重查不是原T/P")
    require_stk_factor_pro_history_eligibility(
        plan,
        HistoryEligibilityRecord(
            1,
            plan.identity,
            plan.history_plan_digest,
            plan.history_ranges_digest,
            raw,
            silver,
            datetime.now(ZoneInfo(STK_FACTOR_PRO_TIMEZONE)),
        ),
    )
    if (factor_t, factor_p) != (plan.factor_t_ref, plan.factor_p_ref):
        raise ValueError("历史权威因子输入身份已改变")
    for path in (
        raw_adj_factor_path(lake_root, factor_t.trade_date.isoformat()),
        raw_adj_factor_path(lake_root, factor_p.trade_date.isoformat()),
        silver_stock_lifecycle_path(lake_root),
    ):
        require_stk_factor_pro_safe_path(path)
        if path not in known_records:
            raise ValueError("历史输入缺少首次文件身份交接")
        wanted = known_records[path][2]
        try:
            current = factor_file_identity(path)
        except FileNotFoundError:
            current = None
        if current != wanted:
            raise ValueError("历史输入文件在首次确认后已改变")
    return facts


def _history_space_count(value):
    if type(value) is not int or value < 0:
        raise ValueError("历史容量行数和文件数必须为非负整数")
    return value


def _history_file_bytes(rows):
    _history_space_count(rows)
    return (
        C.STK_FACTOR_PRO_ESTIMATED_ROW_BYTES * rows
        + C.STK_FACTOR_PRO_ESTIMATED_FILE_OVERHEAD_BYTES
        if rows
        else 0
    )


def _history_space_failure(run_id, stage, reason, **details):
    return dg.Failure(
        description=reason,
        metadata={
            "phase": "history",
            "run_id": run_id,
            "stage": stage,
            "retryable": False,
            "source_error_code": None,
            **details,
        },
        allow_retries=False,
    )


@contextmanager
def _history_space_metadata_errors(run_id, stage, target_trade_date=None):
    try:
        yield
    except dg.Failure as error:
        if target_trade_date is None:
            raise
        raise dg.Failure(
            description=error.description,
            metadata={
                **error.metadata,
                "target_trade_date": target_trade_date.isoformat(),
            },
            allow_retries=False,
        ) from error
    except (OSError, DuckDBError) as error:
        details = (
            {"target_trade_date": target_trade_date.isoformat()}
            if target_trade_date
            else {}
        )
        raise _history_space_failure(
            run_id,
            stage,
            f"历史容量元信息读取失败（{type(error).__name__}）；请管理员检查目录或数据库配置后重新执行",
            **details,
        ) from error


def estimate_stk_factor_pro_history_space(
    *,
    unit_row_bounds,
    max_batch_rows,
    remaining_layer_row_bounds,
    remaining_record_file_count,
    day_work_bytes,
):
    """LLD 18.6.1 arithmetic over facts already obtained by this task."""
    if not unit_row_bounds:
        raise ValueError("无历史unit，不创建容量预算")
    for value in (
        *unit_row_bounds,
        *remaining_layer_row_bounds,
        max_batch_rows,
        remaining_record_file_count,
        day_work_bytes,
    ):
        _history_space_count(value)
    source = sum(_history_file_bytes(rows) for rows in unit_row_bounds)
    retained = _history_file_bytes(sum(unit_row_bounds))
    unit = max(_history_file_bytes(rows) for rows in unit_row_bounds)
    temporary = retained + max(
        2 * unit,
        _history_file_bytes(max_batch_rows)
        + max(day_work_bytes, C.STK_FACTOR_PRO_DAY_WORKSPACE_ESTIMATE_BYTES),
    )
    return C.BootstrapSpaceEstimate(
        source,
        sum(_history_file_bytes(rows) for rows in remaining_layer_row_bounds),
        temporary,
        C.STK_FACTOR_PRO_ESTIMATED_RECORD_BYTES * remaining_record_file_count,
    )


def require_stk_factor_pro_history_space(*, required_by_path, run_id, stage):
    """Compare future allocations with actual free bytes, once per device."""
    with _history_space_metadata_errors(run_id, stage):
        C.validate_stk_factor_pro_identifier(run_id)
        devices = {}
        for path, required in required_by_path:
            _history_space_count(required)
            if required == 0:
                continue
            require_stk_factor_pro_safe_path(path)
            for ancestor in (path, *path.parents):
                try:
                    info = ancestor.stat()
                except FileNotFoundError:
                    continue
                if not stat.S_ISDIR(info.st_mode):
                    continue
                device = devices.setdefault(info.st_dev, [ancestor, 0])
                device[1] += required
                break
            else:
                raise OSError(f"历史容量无法确认设备：{path}")
        for ancestor, future in devices.values():
            required = future + C.STK_FACTOR_PRO_FREE_SPACE_MARGIN_BYTES
            free = shutil.disk_usage(ancestor).free
            if free < required:
                raise dg.Failure(
                    description=f"历史下载空间不足，{stage}：需要{required}字节，剩余{free}字节；请管理员释放空间后重新执行",
                    metadata={
                        "phase": "history",
                        "run_id": run_id,
                        "stage": stage,
                        "required_bytes": required,
                        "free_bytes": free,
                        "device_path": str(ancestor),
                        "retryable": False,
                        "source_error_code": None,
                    },
                    allow_retries=False,
                )


def build_stk_factor_pro_history_space_check(
    connection,
    *,
    identity,
    expected_units,
    publication_dates,
    lake_root,
    staging_root,
    known_records,
    basis_row_counts,
    operation_dates=(),
):
    """Bind a single budget and update only the saved artifact's contribution."""
    with _history_space_metadata_errors(
        identity.creator_run_id, "历史容量准备", identity.target_trade_date
    ):
        if not expected_units:
            raise ValueError("无历史unit，不创建容量回调")
        root = stk_factor_pro_run_staging_root(
            staging_root,
            identity.creator_run_id,
            identity.target_trade_date.isoformat(),
        )
        target_paths = {
            (day, layer): getter(lake_root, day.isoformat())
            for day in publication_dates
            for layer, getter in (
                ("raw", raw_stk_factor_pro_path),
                ("silver", silver_stock_factor_pro_path),
            )
        }
        target_rows, missing_metadata = {}, []
        for key, path in target_paths.items():
            require_stk_factor_pro_safe_path(path)
            audit = known_records.get(path, (None, None, None))[0]
            if audit is not None and hasattr(audit, "row_count"):
                target_rows[key] = audit.row_count
            elif path.is_file():
                missing_metadata.append(path)
            else:
                target_rows[key] = 0
        if missing_metadata:
            counts = dict(
                connection.execute(
                    "SELECT file_name, num_rows FROM parquet_file_metadata(?)",
                    [[str(path) for path in missing_metadata]],
                ).fetchall()
            )
            for key, path in target_paths.items():
                if key not in target_rows:
                    target_rows[key] = counts[str(path)]
        h = tuple((unit.end_date - unit.start_date).days + 1 for unit in expected_units)
        per_date = {
            day: sum(unit.start_date <= day <= unit.end_date for unit in expected_units)
            for day in publication_dates
        }
        batches = tuple(
            publication_dates[
                index : index + C.STK_FACTOR_PRO_HISTORY_MERGE_BATCH_TRADE_DAYS
            ]
            for index in range(
                0,
                len(publication_dates),
                C.STK_FACTOR_PRO_HISTORY_MERGE_BATCH_TRADE_DAYS,
            )
        )
        max_batch_rows = max(
            (sum(per_date[day] for day in batch) for batch in batches), default=0
        )
        basis_bytes = sum(_history_file_bytes(rows) for rows in basis_row_counts)
        work = max(
            (
                4
                * (
                    basis_bytes
                    + _history_file_bytes(target_rows[day, "raw"])
                    + _history_file_bytes(target_rows[day, "silver"])
                    + 2 * _history_file_bytes(target_rows[day, "raw"] + per_date[day])
                )
                for day in publication_dates
            ),
            default=0,
        )
        layers = {
            root
            / f"candidates/history/{day}/{layer}/data.parquet": _history_file_bytes(
                target_rows[day, "raw"] + per_date[day]
            )
            for day in publication_dates
            for layer in ("raw", "silver")
        }
        sources = {
            root
            / f"source/history/units/{stk_factor_pro_unit_key(unit)}.parquet": _history_file_bytes(
                rows
            )
            for unit, rows in zip(expected_units, h, strict=True)
        }
        operation_set = set(operation_dates).intersection(publication_dates)
        operation_count = len(operation_set)
        summary_versions = sum(
            any(day in operation_set for day in batch) for batch in batches
        )
        record_count = (
            3 + 6 * len(publication_dates) + 3 * operation_count + summary_versions
        )
        if not (root / "history-eligibility.json").is_file():
            record_count += 1
        estimate = estimate_stk_factor_pro_history_space(
            unit_row_bounds=h,
            max_batch_rows=max_batch_rows,
            remaining_layer_row_bounds=tuple(
                target_rows[day, "raw"] + per_date[day]
                for day in publication_dates
                for _ in range(2)
            ),
            remaining_record_file_count=record_count,
            day_work_bytes=work,
        )
        totals = [
            estimate.source_bytes,
            estimate.candidate_bytes,
            estimate.temp_bytes,
            estimate.record_bytes,
        ]
        temporary = Path(
            connection.execute("SELECT current_setting('temp_directory')").fetchone()[0]
        )
        if not temporary.is_absolute():
            raise _history_space_failure(
                identity.creator_run_id,
                "历史容量准备",
                "历史计算临时目录必须是已配置绝对路径；请管理员检查数据库配置后重新执行",
            )
        seen_records, completed_dates = set(), set()

        def check_space(
            stage, *, path, rows=None, trade_date=None, layer=None, event=None
        ):
            with _history_space_metadata_errors(
                identity.creator_run_id, stage, identity.target_trade_date
            ):
                path = Path(path)
                if event in ("source_saved", "candidate_verified"):
                    planned = sources if event == "source_saved" else layers
                    if path in planned:
                        reserved = planned.pop(path)
                        totals[0 if event == "source_saved" else 1] -= reserved
                        size = (
                            known_records.get(path, (None, None, None))[2]
                            or factor_file_identity(path)
                        )[2]
                        if size > reserved:
                            raise _history_space_failure(
                                identity.creator_run_id,
                                stage,
                                f"历史文件实际大小超过估算：{path}，请调整后重新执行",
                            )
                elif event == "record_saved":
                    registered = known_records.get(path)
                    signature = (
                        registered[1] if registered else factor_file_identity(path)
                    )
                    version = (path, signature)
                    if version not in seen_records:
                        seen_records.add(version)
                        totals[3] = max(
                            0, totals[3] - C.STK_FACTOR_PRO_ESTIMATED_RECORD_BYTES
                        )
                        size = (
                            registered[2] if registered else factor_file_identity(path)
                        )[2]
                        if size > C.STK_FACTOR_PRO_ESTIMATED_RECORD_BYTES:
                            raise _history_space_failure(
                                identity.creator_run_id,
                                stage,
                                f"历史记录实际大小超过估算：{path}，请调整后重新执行",
                            )
                elif event == "date_completed" and trade_date not in completed_dates:
                    completed_dates.add(trade_date)
                    for name in ("raw", "silver"):
                        totals[1] -= layers.pop(
                            root
                            / f"candidates/history/{trade_date}/{name}/data.parquet",
                            0,
                        )
                elif event == "final_statistics":
                    totals[:] = [0, 0, 0, C.STK_FACTOR_PRO_ESTIMATED_RECORD_BYTES]
                spill = 0
                if totals[2]:
                    for file, size in connection.execute(
                        "SELECT path, size FROM duckdb_temporary_files()"
                    ).fetchall():
                        if Path(file).is_relative_to(temporary):
                            spill += size
                current = C.BootstrapSpaceEstimate(*totals)
                require_stk_factor_pro_history_space(
                    required_by_path=(
                        (root, totals[0] + totals[1] + totals[3]),
                        (temporary, max(totals[2] - spill, 0)),
                    ),
                    run_id=identity.creator_run_id,
                    stage=stage,
                )
                return current

        return check_space


def stk_factor_pro_missing_codes_reusable(coverage, *, staging_root, known_records):
    if not coverage.missing_count:
        return True
    ref = coverage.missing_codes_ref
    if ref is None:
        return False
    root = stk_factor_pro_run_staging_root(
        staging_root, ref.creator_run_id, str(coverage.target_trade_date)
    )
    path = root / ref.relative_path
    require_stk_factor_pro_safe_path(path)
    return factor_known_file_sha(path, known_records=known_records) == ref.file_sha256


def write_stk_factor_pro_missing_codes(
    connection, *, staging_root, identity, coverage, calculated, known_records
):
    """Persist only the first nonempty difference; hand off its existing result."""
    if coverage.missing_count in (None, 0):
        return coverage
    if coverage.missing_codes_ref is not None:
        if not stk_factor_pro_missing_codes_reusable(
            coverage,
            staging_root=staging_root,
            known_records=known_records,
        ):
            raise ValueError("原缺失清单失效，需以原T现有代码重新计算")
        return coverage
    if (
        calculated is None
        or calculated["coverage_counts"].missing_count != coverage.missing_count
    ):
        raise ValueError("缺失清单缺本任务首次集合结果")
    ref = calculated["missing_codes_ref"]
    if ref is not None:
        if isinstance(ref, C.StkFactorProBootstrapCodesRef):
            ref = RecordRef(ref.creator_run_id, ref.relative_path, ref.file_sha256)
        return replace(
            coverage,
            missing_codes_ref=ref,
            missing_sample_codes=calculated["missing_sample_codes"],
        )
    root = stk_factor_pro_run_staging_root(
        staging_root, identity.creator_run_id, str(identity.target_trade_date)
    )
    path = _path(root, identity, "diagnostics/day-missing-codes.parquet")
    temporary = _prepare(path)
    source = "stk_factor_pro_coverage_missing"
    saved = "stk_factor_pro_missing_saved"
    with _history_resource_cleanup(
        lambda: connection.execute(f"DROP TABLE IF EXISTS {saved}"),
        lambda: temporary.unlink(missing_ok=True),
    ):
        connection.execute(
            f"COPY (SELECT ts_code,trade_date FROM {source} ORDER BY ts_code) TO ? (FORMAT PARQUET)",
            [str(temporary)],
        )
        connection.execute(
            f"CREATE TEMP TABLE {saved} AS SELECT * FROM {read_parquet(temporary, hive_partitioning=False)}"
        )
        observed = tuple(
            (r[0], r[1]) for r in connection.execute(f"DESCRIBE {saved}").fetchall()
        )
        if observed != (("ts_code", "VARCHAR"), ("trade_date", "DATE")):
            raise ValueError("缺失清单传输schema不符")
        count = connection.execute(f"SELECT count(*) FROM {saved}").fetchone()[0]
        difference = connection.execute(
            f"SELECT count(*) FROM ((SELECT ts_code,trade_date FROM {source} EXCEPT ALL SELECT * FROM {saved}) UNION ALL "
            f"(SELECT * FROM {saved} EXCEPT ALL SELECT ts_code,trade_date FROM {source}))"
        ).fetchone()[0]
        if count != coverage.missing_count or difference:
            raise ValueError("缺失清单传输内容不符")
        sample = tuple(
            r[0]
            for r in connection.execute(
                f"SELECT ts_code FROM {saved} ORDER BY ts_code LIMIT 20"
            ).fetchall()
        )
        digest = factor_file_sha(temporary)
        _promote(temporary, path)
        ref = RecordRef(
            identity.creator_run_id, "diagnostics/day-missing-codes.parquet", digest
        )
        known_records[path] = (ref, digest, factor_file_identity(path))
        calculated["missing_codes_ref"], calculated["missing_sample_codes"] = (
            ref,
            sample,
        )
        return replace(coverage, missing_codes_ref=ref, missing_sample_codes=sample)
