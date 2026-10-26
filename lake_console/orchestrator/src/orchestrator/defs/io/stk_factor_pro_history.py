"""Closed historical records and current-run source verification on one connection."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import fields, replace
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from duckdb import Error as DuckDBError

from orchestrator.defs.checks.stk_factor_pro import (
    factor_file_sha,
    require_factor_history_relation,
)
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.io.stk_factor_pro_candidates import (
    require_stk_factor_pro_safe_path,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_STAGING_ROOT,
    raw_adj_factor_path,
    raw_stk_factor_pro_path,
    silver_stock_lifecycle_path,
    stk_factor_pro_record_path,
    stk_factor_pro_run_staging_root,
)
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
    stk_factor_pro_files_manifest_digest,
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
            except DuckDBError as cleanup:
                failures.append(cleanup)
        if failures:
            reported = primary if primary is not None else failures[0]
            for cleanup in failures:
                reported.add_note(
                    f"历史记录清理同时失败：{type(cleanup).__name__}"
                )
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


def _ref_path(root: Path, identity: RunIdentity, reference: RecordRef) -> Path:
    if reference.creator_run_id != identity.creator_run_id:
        raise ValueError("历史源引用必须属于当前run")
    path = _path(root, identity, reference.relative_path)
    if not path.is_file() or factor_file_sha(path) != reference.file_sha256:
        raise ValueError("历史引用文件缺失或字节SHA不符")
    return path


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("历史JSON不得包含重复字段")
        result[key] = value
    return result


def _json_read(path: Path, record_type):
    require_stk_factor_pro_safe_path(path)
    before = factor_file_sha(path)
    value = json.loads(path.read_text(), object_pairs_hook=_pairs)
    record = parse_stk_factor_pro_record(record_type, value)
    if (
        factor_file_sha(path) != before
        or stk_factor_pro_record_to_dict(record) != value
    ):
        raise ValueError("历史JSON读回期间变化或表示不规范")
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


def _json_write(root: Path, identity: RunIdentity, relative: str, record):
    path = _path(root, identity, relative)
    payload = json.dumps(
        stk_factor_pro_record_to_dict(record),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    # Validate the complete wire representation before writing anything.
    parse_stk_factor_pro_record(
        type(record), json.loads(payload, object_pairs_hook=_pairs)
    )
    temporary = _prepare(path)
    with temporary.open("x", encoding="utf-8") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    if _json_read(temporary, type(record)) != record:
        raise ValueError("历史JSON候选读回不符")
    _promote(temporary, path)
    if _json_read(path, type(record)) != record:
        raise ValueError("历史JSON最终读回不符")
    return RecordRef(identity.creator_run_id, relative, factor_file_sha(path))


def _schema(connection, path: Path, expected) -> None:
    require_stk_factor_pro_safe_path(path)
    observed = tuple(
        (row[0], row[1])
        for row in connection.execute(
            f"DESCRIBE SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
        ).fetchall()
    )
    if observed != expected:
        raise ValueError("历史Parquet列名/顺序/类型与完整合同不符")


def _record_order(schema) -> str:
    if schema == HISTORY_RANGE_SCHEMA:
        return "ts_code"
    if schema == SOURCE_FILE_SCHEMA:
        return "unit_key"
    raise ValueError("未知历史记录schema")


def _read_rows(connection, path: Path, schema):
    before = factor_file_sha(path)
    _schema(connection, path, schema)
    columns = ", ".join(f'"{name}"' for name, _ in schema)
    rows = connection.execute(
        f"SELECT {columns} FROM {read_parquet(path, hive_partitioning=False)} ORDER BY {_record_order(schema)}"
    ).fetchall()
    if factor_file_sha(path) != before:
        raise ValueError("历史Parquet读回期间发生变化")
    return rows


def _write_rows(
    connection, root: Path, identity: RunIdentity, relative: str, schema, rows, decode
):
    path = _path(root, identity, relative)
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
            decode(values) for values in _read_rows(connection, temporary, schema)
        )
        expected = tuple(decode(values) for values in rows)
        if observed != expected:
            raise ValueError("历史Parquet候选内容与输入不符")
        _promote(temporary, path)
        if (
            tuple(decode(values) for values in _read_rows(connection, path, schema))
            != expected
        ):
            raise ValueError("历史Parquet最终内容与输入不符")
        return RecordRef(identity.creator_run_id, relative, factor_file_sha(path))


def read_stk_factor_pro_history_plan(
    root: Path, *, expected_target: date, expected_run_id: str
) -> HistoryPlanRecord:
    _run_root(root, run_id=expected_run_id, target=expected_target)
    result = _json_read(root / "history-plan.json", HistoryPlanRecord)
    if (
        result.identity.target_trade_date != expected_target
        or result.identity.creator_run_id != expected_run_id
    ):
        raise ValueError("历史计划不对应原T/run")
    return result


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
    if stk_factor_pro_history_ranges_digest(ranges) != plan.history_ranges_digest or (
        stk_factor_pro_history_plan_digest(plan.identity, plan.contract, ranges)
        != plan.history_plan_digest
    ):
        raise ValueError("历史计划/范围业务摘要读回不符")


def read_stk_factor_pro_history_ranges(
    connection, *, root: Path, plan: HistoryPlanRecord
) -> tuple[HistoryRange, ...]:
    path = _ref_path(root, plan.identity, plan.ranges_ref)
    result = tuple(
        _decode_range(row) for row in _read_rows(connection, path, HISTORY_RANGE_SCHEMA)
    )
    _validate_ranges(plan, result)
    return result


def write_stk_factor_pro_history_plan(
    root: Path,
    record: HistoryPlanRecord,
    ranges: tuple[HistoryRange, ...],
    *,
    connection,
) -> HistoryPlanRecord:
    _validate_ranges(record, ranges)
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
    )
    saved = replace(record, ranges_ref=reference)
    _json_write(root, record.identity, "history-plan.json", saved)
    actual = read_stk_factor_pro_history_plan(
        root,
        expected_target=saved.identity.target_trade_date,
        expected_run_id=saved.identity.creator_run_id,
    )
    if (
        actual != saved
        or read_stk_factor_pro_history_ranges(connection, root=root, plan=actual)
        != ranges
    ):
        raise ValueError("历史计划完整读回不符")
    return actual


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
    )


def read_stk_factor_pro_source_files(
    root: Path,
    reference: RecordRef,
    *,
    connection,
    identity: RunIdentity,
    contract: ContractIdentity,
) -> tuple[SourceFileRecord, ...]:
    if reference.relative_path != "source/history/source-files.parquet":
        raise ValueError("历史manifest必须使用固定相对路径")
    path = _ref_path(root, identity, reference)
    result = tuple(
        _decode_source_file(row)
        for row in _read_rows(connection, path, SOURCE_FILE_SCHEMA)
    )
    _validate_source_files(identity, contract, result)
    return result


def write_stk_factor_pro_source_complete(
    root: Path, record: SourceCompleteRecord
) -> SourceCompleteRecord:
    _json_write(root, record.identity, "source/history/source-complete.json", record)
    return record


def _verify_source_unit(connection, path: Path, file: SourceFileRecord) -> None:
    relation = "stk_factor_pro_verified_source_unit"
    before = factor_file_sha(path)
    with _history_resource_cleanup(
        lambda: connection.execute(f"DROP VIEW IF EXISTS {relation}"),
    ):
        connection.execute(
            f"CREATE TEMP VIEW {relation} AS SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
        )
        count, _ = require_factor_history_relation(
            connection,
            relation,
            object_code=file.object_code,
            start_date=file.start_date,
            end_date=file.end_date,
        )
        if count != file.file_rows:
            raise ValueError("历史unit实际行数与完整记录不符")
        if before != file.file_sha256 or factor_file_sha(path) != before:
            raise ValueError("历史unit文件在核验期间改变或SHA不符")


def verify_stk_factor_pro_current_source(
    root: Path,
    record: SourceCompleteRecord,
    *,
    connection,
    current_run_id: str,
    expected_units: tuple[UnitProjection, ...],
) -> VerifiedSource:
    if (
        not isinstance(record, SourceCompleteRecord)
        or record.identity.creator_run_id != current_run_id
        or record.expected_units != expected_units
    ):
        raise ValueError("历史源必须属于当前run且逐项覆盖本次expected_units")
    if record.contract != ContractIdentity(
        "stk_factor_pro",
        "1",
        content_digest(STK_FACTOR_PRO_CONTRACT),
        STK_FACTOR_PRO_PROCESSING_VERSION,
    ):
        raise ValueError("历史源与当前登记契约不符")
    source_path = _path(root, record.identity, "source/history/source-complete.json")
    if _json_read(source_path, SourceCompleteRecord) != record:
        raise ValueError("历史源完整记录与实际保存不符")
    plan_path = _ref_path(root, record.identity, record.history_plan_ref)
    plan = read_stk_factor_pro_history_plan(
        root,
        expected_target=record.identity.target_trade_date,
        expected_run_id=current_run_id,
    )
    if (
        plan.identity != record.identity
        or plan_path.name != "history-plan.json"
        or (
            plan.contract,
            plan.revision,
            plan.history_plan_digest,
            plan.origin_history_plan_digest,
            plan.origin_history_ranges_digest,
        )
        != (
            record.contract,
            record.history_plan_revision,
            record.history_plan_digest,
            record.origin_history_plan_digest,
            record.origin_history_ranges_digest,
        )
    ):
        raise ValueError("历史源与原完整计划的身份/版本/授权不符")
    ranges = read_stk_factor_pro_history_ranges(connection, root=root, plan=plan)
    if (
        stk_factor_pro_history_input_digest(
            record.identity, record.contract, expected_units, ranges
        )
        != record.history_input_digest
    ):
        raise ValueError("历史源业务输入摘要不符")
    files = read_stk_factor_pro_source_files(
        root,
        record.files_manifest_ref,
        connection=connection,
        identity=record.identity,
        contract=record.contract,
    )
    by_key = {stk_factor_pro_unit_key(unit): unit for unit in expected_units}
    if len(files) != record.completed_unit_count or {
        row.unit_key for row in files
    } != set(by_key):
        raise ValueError("历史manifest没有逐项覆盖全部expected_units")
    if (
        stk_factor_pro_files_manifest_digest(record.scope_digest, files)
        != record.files_manifest_digest
    ):
        raise ValueError("历史manifest业务摘要不符")
    for file in files:
        actual_unit = UnitProjection(
            file.mode, file.object_code, file.point, file.start_date, file.end_date
        )
        if actual_unit != by_key[file.unit_key]:
            raise ValueError("历史manifest业务unit错位")
        path = _ref_path(
            root,
            record.identity,
            RecordRef(current_run_id, file.file_relative_path, file.file_sha256),
        )
        _verify_source_unit(connection, path, file)
    # Re-check all metadata identities after the last actual unit was inspected.
    _ref_path(root, record.identity, record.history_plan_ref)
    _ref_path(root, record.identity, plan.ranges_ref)
    _ref_path(root, record.identity, record.files_manifest_ref)
    if _json_read(source_path, SourceCompleteRecord) != record:
        raise ValueError("历史源完整记录在核验期间改变")
    reference = RecordRef(
        current_run_id,
        "source/history/source-complete.json",
        factor_file_sha(source_path),
    )
    return VerifiedSource(record.identity, record.contract, record, reference)


def resolve_stk_factor_pro_history_starts(
    connection,
    *,
    lake_root: Path,
    target_trade_date: date,
    codes: tuple[str, ...],
    known_starts: tuple[StkFactorProHistoryStart, ...],
    approved_raw_dates: tuple[date, ...],
    check_cancel,
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
        for path in paths:
            require_stk_factor_pro_safe_path(path)
            if not path.is_file():
                raise ValueError("已批准可信Raw文件缺失，不能据剩余文件推算最早日期")
            schema = {
                row[0]: row[1]
                for row in connection.execute(
                    "DESCRIBE SELECT ts_code,trade_date FROM read_parquet(?,hive_partitioning=false)",
                    [str(path)],
                ).fetchall()
            }
            if schema != {"ts_code": "VARCHAR", "trade_date": "VARCHAR"}:
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


def _read_history_factor(connection, *, lake_root, reference, relation):
    if not isinstance(reference, FactorFileRef):
        raise TypeError("历史规划必须使用权威因子引用")
    path = raw_adj_factor_path(lake_root, reference.trade_date.isoformat())
    require_stk_factor_pro_safe_path(path)
    if not path.is_file() or factor_file_sha(path) != reference.file_sha256:
        raise ValueError("历史规划权威因子文件缺失或SHA不符")
    _schema(
        connection, path, tuple((c.name, c.type) for c in RAW_TUSHARE_ADJ_FACTOR_SCHEMA)
    )
    connection.execute(
        f"CREATE TEMP TABLE {relation} AS SELECT ts_code,trade_date,adj_factor FROM {read_parquet(path, hive_partitioning=False)}"
    )
    count, bad = connection.execute(
        f"SELECT count(*),count(*) FILTER (WHERE ts_code IS NULL OR NOT regexp_full_match(ts_code,'[0-9]{{6}}\\.(SH|SZ|BJ)') "
        "OR trade_date IS DISTINCT FROM ? OR adj_factor IS NULL OR NOT isfinite(adj_factor) OR adj_factor<=0) "
        f"FROM {relation}",
        [reference.trade_date.strftime("%Y%m%d")],
    ).fetchone()
    duplicates = connection.execute(
        f"SELECT count(*) FROM (SELECT ts_code FROM {relation} GROUP BY ts_code HAVING count(*)>1)"
    ).fetchone()[0]
    if (
        count != reference.rows
        or count == 0
        or bad
        or duplicates
        or factor_file_sha(path) != reference.file_sha256
    ):
        raise ValueError("历史规划权威因子行数/非空/股票/日期/正值/唯一键检查不符")
    return path


def _history_old_records(connection, *, staging_root, target, contract, prior):
    """Exact old work records only; never inspect old downloaded unit files."""
    plans = {}

    def load_plan(reference):
        if reference.relative_path != "history-plan.json":
            raise ValueError("原历史计划引用必须是固定history-plan.json")
        if reference in plans:
            return plans[reference]
        root = stk_factor_pro_run_staging_root(
            staging_root, reference.creator_run_id, target.isoformat()
        )
        _run_root(root, run_id=reference.creator_run_id, target=target)
        path = root / reference.relative_path
        require_stk_factor_pro_safe_path(path)
        if not path.is_file() or factor_file_sha(path) != reference.file_sha256:
            raise ValueError("原历史计划引用缺失或SHA不符")
        record = read_stk_factor_pro_history_plan(
            root, expected_target=target, expected_run_id=reference.creator_run_id
        )
        if record.contract != contract:
            raise ValueError("原历史计划不属于本次完整契约")
        rows = read_stk_factor_pro_history_ranges(connection, root=root, plan=record)
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
        if (
            ref.relative_path != "publication/history/publication-complete.json"
            or not path.is_file()
            or factor_file_sha(path) != ref.file_sha256
        ):
            raise ValueError("原历史成功引用缺失、SHA不符或路径错误")
        published = _json_read(path, PublicationCompleteRecord)
        if (
            published.phase != "history"
            or published.identity.creator_run_id != ref.creator_run_id
            or published.identity.target_trade_date != target
            or published.contract != contract
        ):
            raise ValueError("原历史成功记录日期/run/合同不符")
        path = root / "history-plan.json"
        require_stk_factor_pro_safe_path(path)
        record, _ = load_plan(
            RecordRef(ref.creator_run_id, "history-plan.json", factor_file_sha(path))
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


def _history_lifecycle(connection, *, lake_root, codes, target):
    if not codes:
        return {}
    path = silver_stock_lifecycle_path(lake_root)
    require_stk_factor_pro_safe_path(path)
    if not path.is_file():
        return {}
    before = factor_file_sha(path)
    try:
        _schema(
            connection,
            path,
            tuple((c.name, c.type) for c in SILVER_STOCK_LIFECYCLE_SCHEMA),
        )
    except ValueError:
        return {}
    rows = connection.execute(
        f"SELECT ts_code,list_date,delist_date,curr_type,is_cny_stock FROM {read_parquet(path, hive_partitioning=False)} WHERE ts_code=ANY(?) ORDER BY ts_code",
        [list(codes)],
    ).fetchall()
    if factor_file_sha(path) != before:
        raise ValueError("历史规划生命周期文件在读取期间改变")
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


def build_stk_factor_pro_history_plan(
    connection,
    *,
    identity: RunIdentity,
    contract: ContractIdentity,
    lake_root: Path,
    staging_root: Path,
    factor_t: FactorFileRef,
    factor_p: FactorFileRef,
    prior_results: StkFactorProRecordedResults,
    history_starts: tuple[StkFactorProHistoryStart, ...],
    check_cancel,
) -> HistoryPlanRecord:
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
    plans, load_plan = _history_old_records(
        connection,
        staging_root=staging_root,
        target=identity.target_trade_date,
        contract=contract,
        prior=prior_results,
    )
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
    pending = {
        r.ts_code for ref in prior_results.pending_plan_refs for r in plans[ref][1]
    }
    old = {}
    for reference, (_, rows) in plans.items():
        for row in rows:
            old.setdefault(row.ts_code, []).append((reference, row))
    starts = {r.ts_code: r for r in history_starts}
    t_relation, p_relation = (
        "stk_factor_pro_history_factor_t",
        "stk_factor_pro_history_factor_p",
    )
    with _history_resource_cleanup(
        lambda: connection.execute(f"DROP TABLE IF EXISTS {t_relation}"),
        lambda: connection.execute(f"DROP TABLE IF EXISTS {p_relation}"),
    ):
        t_path = _read_history_factor(
            connection, lake_root=lake_root, reference=factor_t, relation=t_relation
        )
        p_path = _read_history_factor(
            connection, lake_root=lake_root, reference=factor_p, relation=p_relation
        )
        compared = connection.execute(
            f"SELECT coalesce(t.ts_code,p.ts_code),t.adj_factor,p.adj_factor,t.ts_code IS NOT NULL,p.ts_code IS NOT NULL FROM {t_relation} t FULL OUTER JOIN {p_relation} p USING(ts_code) ORDER BY 1"
        ).fetchall()
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
            lake_root=lake_root,
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
                r
                for r in (starts.get(code),)
                if r is not None and r.start_date is not None
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
                    identity.target_trade_date
                    if chosen.start_date is not None
                    else None,
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
        plan_digest = stk_factor_pro_history_plan_digest(identity, contract, ranges)
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
        for path, reference in ((t_path, factor_t), (p_path, factor_p)):
            if factor_file_sha(path) != reference.file_sha256:
                raise ValueError("历史规划权威输入在保存前改变")
        check_cancel()
        plan = HistoryPlanRecord(
            1,
            identity,
            contract,
            revision,
            datetime.now(ZoneInfo(STK_FACTOR_PRO_TIMEZONE)),
            plan_digest,
            stk_factor_pro_history_ranges_digest(ranges),
            RecordRef(identity.creator_run_id, "history-ranges.parquet", "0" * 64),
            len(ranges),
            factor_t,
            factor_p,
            revision_of,
            origin_ref,
            None if origin_ref is None else plans[origin_ref][0].history_plan_digest,
            None if origin_ref is None else plans[origin_ref][0].history_ranges_digest,
        )
        return write_stk_factor_pro_history_plan(
            root, plan, ranges, connection=connection
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
    _validate_ranges(plan, ranges)


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
    actual = read_stk_factor_pro_history_plan(
        root,
        expected_target=plan.identity.target_trade_date,
        expected_run_id=plan.identity.creator_run_id,
    )
    if (
        actual != plan
        or read_stk_factor_pro_history_ranges(connection, root=root, plan=actual)
        != ranges
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
        if not path.is_file() or factor_file_sha(path) != reference.file_sha256:
            raise ValueError("原历史完整成功引用缺失或SHA不符")
        published = _json_read(path, PublicationCompleteRecord)
        old_plan = read_stk_factor_pro_history_plan(
            old_root,
            expected_target=plan.identity.target_trade_date,
            expected_run_id=reference.creator_run_id,
        )
        old_ranges = read_stk_factor_pro_history_ranges(
            connection, root=old_root, plan=old_plan
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
            old_root, old_plan.identity, published.source_complete_ref
        )
        source = _json_read(source_path, SourceCompleteRecord)
        if (
            source.identity != old_plan.identity
            or source.contract != old_plan.contract
            or source.history_plan_ref
            != RecordRef(
                reference.creator_run_id,
                "history-plan.json",
                factor_file_sha(old_root / "history-plan.json"),
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
) -> tuple[
    FactorFileRef, FactorFileRef, StkFactorProRawCoverage, StkFactorProTargetSilver
]:
    """Recheck only the requested business factor projection when bytes change."""
    _require_registered_history_plan(plan, ranges)
    _check_history_unit_subset(plan, ranges, expected_units)
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
    require_stk_factor_pro_safe_path(lake_root)
    by_code = {row.ts_code: row for row in ranges}
    relations = ("stk_factor_pro_history_recheck_t", "stk_factor_pro_history_recheck_p")
    with _history_resource_cleanup(
        lambda: connection.execute(f"DROP TABLE IF EXISTS {relations[0]}"),
        lambda: connection.execute(f"DROP TABLE IF EXISTS {relations[1]}"),
    ):
        for position, (reference, original) in enumerate(
            ((factor_t, plan.factor_t_ref), (factor_p, plan.factor_p_ref))
        ):
            path = raw_adj_factor_path(lake_root, reference.trade_date.isoformat())
            require_stk_factor_pro_safe_path(path)
            if not path.is_file() or factor_file_sha(path) != reference.file_sha256:
                raise ValueError("历史输入重查实际因子文件缺失或SHA不符")
            if reference.file_sha256 == original.file_sha256:
                if reference.rows != original.rows:
                    raise ValueError("同一因子文件的行数引用不一致")
                continue
            _read_history_factor(
                connection,
                lake_root=lake_root,
                reference=reference,
                relation=relations[position],
            )
            values = dict(
                connection.execute(
                    f"SELECT ts_code,adj_factor FROM {relations[position]} WHERE ts_code=ANY(?) ORDER BY ts_code",
                    [[unit.object_code for unit in expected_units]],
                ).fetchall()
            )
            for unit in expected_units:
                row = by_code[unit.object_code]
                wanted = row.t_value if position == 0 else row.p_value
                if values.get(unit.object_code) != wanted:
                    raise ValueError(
                        f"历史请求范围权威复权因子已改变：{unit.object_code}"
                    )
            if factor_file_sha(path) != reference.file_sha256:
                raise ValueError("历史输入重查因子在比较期间改变")
        for reference in (factor_t, factor_p):
            path = raw_adj_factor_path(lake_root, reference.trade_date.isoformat())
            require_stk_factor_pro_safe_path(path)
            if factor_file_sha(path) != reference.file_sha256:
                raise ValueError("历史输入重查因子在返回前改变")
        return facts
