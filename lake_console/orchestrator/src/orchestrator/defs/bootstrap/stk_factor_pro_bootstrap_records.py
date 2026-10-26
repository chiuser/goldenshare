"""Operation-bound bootstrap records; no database ownership or event discovery."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import timedelta
from uuid import uuid4

from orchestrator.defs.checks.stk_factor_pro import (
    factor_content_sha,
    factor_file_sha,
    require_factor_relation,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.io.stk_factor_pro_candidates import (
    BOOTSTRAP_DAY_SOURCE,
    require_stk_factor_pro_safe_path,
)
from orchestrator.defs.paths import (
    stk_factor_pro_bootstrap_operation_root,
    stk_factor_pro_bootstrap_record_path,
)
from orchestrator.defs.run_contracts import stk_factor_pro as C


def operation_root(staging_root, approval):
    return stk_factor_pro_bootstrap_operation_root(staging_root, approval.operation_id)


def operation_path(staging_root, approval, relative):
    return stk_factor_pro_bootstrap_record_path(
        staging_root, approval.operation_id, relative
    )


def fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def resource_cleanup(*releases):
    """Attempt all owned cleanup, retaining the original failure/cancellation."""
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
            except BaseException as error:  # noqa: BLE001 - attempt every cleanup, including cancellation
                failures.append(error)
        if failures:
            reported = primary if primary is not None else failures[0]
            for error in failures:
                reported.add_note(f"bootstrap清理同时失败：{type(error).__name__}")
            if primary is None:
                raise reported


@contextmanager
def resource_context(manager):
    """Preserve body errors even when an existing context's exit also fails."""
    value = manager.__enter__()
    try:
        yield value
    except BaseException as primary:
        try:
            manager.__exit__(type(primary), primary, primary.__traceback__)
        except BaseException as cleanup:  # noqa: BLE001 - retain the original cancellation/failure
            primary.add_note(f"bootstrap资源退出同时失败：{type(cleanup).__name__}")
        raise
    else:
        manager.__exit__(None, None, None)


def atomic_promote(temporary, path, *, replace_existing=False):
    for value in (temporary, path):
        require_stk_factor_pro_safe_path(value)
    if path.exists() and not replace_existing:
        raise ValueError("bootstrap不可变文件已经存在")
    if temporary.stat().st_dev != path.parent.stat().st_dev:
        raise ValueError("bootstrap必须同文件系统原子保存")
    with temporary.open("rb") as stream:
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    fsync_directory(path.parent)


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("bootstrap JSON重复键")
        result[key] = value
    return result


def read_json(path, record_type):
    require_stk_factor_pro_safe_path(path)
    if not path.exists():
        return None
    before = factor_file_sha(path)
    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError("非法JSON常量")),
    )
    record = C.parse_stk_factor_pro_record(record_type, value)
    if (
        C.stk_factor_pro_record_to_dict(record) != value
        or factor_file_sha(path) != before
    ):
        raise ValueError("bootstrap记录不规范或读回期间变化")
    return record


def write_json(path, record, *, mutable=False):
    require_stk_factor_pro_safe_path(path)
    payload = (
        json.dumps(
            C.stk_factor_pro_record_to_dict(record),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode()
    C.parse_stk_factor_pro_record(
        type(record), json.loads(payload, object_pairs_hook=_pairs)
    )
    if path.exists() and not mutable:
        existing = read_json(path, type(record))
        if existing != record:
            raise ValueError("bootstrap不可变记录内容冲突")
        return existing
    before = factor_file_sha(path) if path.exists() else None
    path.parent.mkdir(parents=True, exist_ok=True)
    require_stk_factor_pro_safe_path(path)
    temporary = path.with_name(path.name + f".{uuid4().hex}.tmp")
    with temporary.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    if (factor_file_sha(path) if path.exists() else None) != before:
        raise ValueError("bootstrap记录写入期间改变")
    atomic_promote(temporary, path, replace_existing=mutable)
    saved = read_json(path, type(record))
    if saved != record:
        raise ValueError("bootstrap记录读回不一致")
    return saved


def approval_sha(staging_root, approval):
    path = operation_path(staging_root, approval, "approval.json")
    if read_json(path, C.StkFactorProBootstrapApproval) != approval:
        raise ValueError("bootstrap批准记录不存在或与当前operation不符")
    return factor_file_sha(path)


def load_approved_counts(connection, *, staging_root, approval):
    path = operation_path(staging_root, approval, approval.approved_daily_counts_ref)
    if factor_file_sha(path) != approval.approved_daily_counts_digest:
        raise ValueError("bootstrap批准日计数摘要不符")
    connection.execute(
        f"CREATE OR REPLACE TEMP VIEW stk_factor_bootstrap_counts AS SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
    )
    with resource_cleanup(
        lambda: connection.execute("DROP VIEW IF EXISTS stk_factor_bootstrap_counts")
    ):
        schema = tuple(
            (row[0], row[1])
            for row in connection.execute(
                "DESCRIBE stk_factor_bootstrap_counts"
            ).fetchall()
        )
        if schema != (("trade_date", "DATE"), ("row_count", "BIGINT")):
            raise ValueError("bootstrap批准日计数schema错误")
        rows = tuple(
            connection.execute(
                "SELECT trade_date,row_count FROM stk_factor_bootstrap_counts ORDER BY trade_date"
            ).fetchall()
        )
        days = tuple(
            approval.start_trade_date + timedelta(days=i)
            for i in range(
                (approval.end_trade_date - approval.start_trade_date).days + 1
            )
        )
        if tuple(row[0] for row in rows) != days or any(
            type(n) is not int or n < 0 for _, n in rows
        ):
            raise ValueError("bootstrap批准日计数缺日、重复或非法")
        if factor_file_sha(path) != approval.approved_daily_counts_digest:
            raise ValueError("bootstrap批准日计数读取期间改变")
        return rows


def fragment_from_relation(connection, *, path, operation_root, relation):
    from orchestrator.defs.io.stk_factor_pro_candidates import (
        describe_stk_factor_pro_fragment,
    )

    return describe_stk_factor_pro_fragment(
        connection, path=path, root=operation_root, relation=relation
    )


def _source_identity(staging_root, approval, record):
    if (
        record.operation_id != approval.operation_id
        or record.approval_digest != approval_sha(staging_root, approval)
        or record.source_identity_digest != approval.source_identity_digest
        or record.contract_content_digest != approval.contract_content_digest
        or record.source_cutoff_trade_date != approval.source_cutoff_trade_date
        or not approval.start_trade_date <= record.trade_date <= approval.end_trade_date
    ):
        raise ValueError("bootstrap完整日源与批准/来源/日期不符")
    if not any(
        (m.month_start, m.month_end_exclusive, m.row_upper_bound)
        == (record.month_start, record.month_end_exclusive, record.row_upper_bound)
        for m in approval.month_limits
    ):
        raise ValueError("bootstrap完整日源月份不属于批准")
    if (
        record.source_complete_digest
        != C.stk_factor_pro_bootstrap_source_complete_digest(record)
    ):
        raise ValueError("bootstrap完整日源摘要不符")
    month = next(
        m for m in approval.month_limits if m.month_start == record.month_start
    )
    if record.query_scope_digest != C.stk_factor_pro_bootstrap_query_digest(
        approval, approval_sha(staging_root, approval), month, record.selected_dates
    ) or record.fragments_manifest_digest != C.fragments_manifest_digest(
        record.fragments
    ):
        raise ValueError("bootstrap完整日查询范围或片段清单摘要不符")


def read_stk_factor_pro_bootstrap_source_complete(
    connection, *, staging_root, approval, trade_date
):
    path = operation_path(
        staging_root,
        approval,
        f"source/dates/{trade_date.isoformat()}/source-complete.json",
    )
    record = read_json(path, C.StkFactorProBootstrapSourceComplete)
    if record is not None:
        _source_identity(staging_root, approval, record)
        if record.trade_date != trade_date:
            raise ValueError("bootstrap源记录固定日期不符")
    return record


def load_complete_source(connection, *, staging_root, approval, record):
    """Verify exact referenced fragments, then materialize one bounded full day."""
    _source_identity(staging_root, approval, record)
    paths = []
    root = operation_root(staging_root, approval)
    for reference in record.fragments:
        fragment = reference.fragment
        wanted = f"source/month={record.month_start:%Y-%m}/attempt_id={record.attempt_id}/fragment-{reference.fragment_no:06d}.parquet"
        if (
            fragment.relative_path != wanted
            or reference.attempt_id != record.attempt_id
        ):
            raise ValueError("bootstrap片段位置/attempt不符")
        path = operation_path(staging_root, approval, wanted)
        if factor_file_sha(path) != fragment.file_sha256:
            raise ValueError("bootstrap源片段文件摘要不符")
        relation = "stk_factor_bootstrap_verify_fragment"
        connection.execute(
            f"CREATE OR REPLACE TEMP VIEW {relation} AS SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
        )
        with resource_cleanup(
            lambda relation=relation: connection.execute(
                f"DROP VIEW IF EXISTS {relation}"
            )
        ):
            if (
                fragment_from_relation(
                    connection, path=path, operation_root=root, relation=relation
                )
                != fragment
            ):
                raise ValueError("bootstrap片段完整内容不符")
            if not connection.execute(
                f"SELECT count(*) FROM {relation} WHERE trade_date=?",
                [record.trade_date.strftime("%Y%m%d")],
            ).fetchone()[0]:
                raise ValueError("bootstrap引用片段没有本日行")
        paths.append(str(path))
    connection.execute(f"DROP TABLE IF EXISTS {BOOTSTRAP_DAY_SOURCE}")
    if paths:
        connection.execute(
            f"CREATE TEMP TABLE {BOOTSTRAP_DAY_SOURCE} AS SELECT * FROM read_parquet(?,hive_partitioning=false) WHERE trade_date=?",
            [paths, record.trade_date.strftime("%Y%m%d")],
        )
    else:
        fields = ",".join(
            f'CAST(NULL AS {kind}) AS "{name}"'
            for name, kind in C.STK_FACTOR_PRO_RAW_COLUMN_TYPES.items()
        )
        connection.execute(
            f"CREATE TEMP TABLE {BOOTSTRAP_DAY_SOURCE} AS SELECT {fields} WHERE false"
        )
    try:
        count, _ = require_factor_relation(
            connection,
            BOOTSTRAP_DAY_SOURCE,
            target_trade_date=record.trade_date,
            layer="raw",
        )
        if (
            count != record.actual_rows
            or factor_content_sha(connection, BOOTSTRAP_DAY_SOURCE)
            != record.date_content_sha256
        ):
            raise ValueError("bootstrap完整日源行数/业务内容不符")
    except BaseException as primary:
        try:
            connection.execute(f"DROP TABLE IF EXISTS {BOOTSTRAP_DAY_SOURCE}")
        except BaseException as cleanup:  # noqa: BLE001 - retain the original cancellation/failure
            primary.add_note(f"bootstrap源验证清理同时失败：{type(cleanup).__name__}")
        raise


def write_stk_factor_pro_bootstrap_source_complete(
    connection, *, staging_root, approval, record
):
    _source_identity(staging_root, approval, record)
    counts = dict(
        load_approved_counts(connection, staging_root=staging_root, approval=approval)
    )
    if counts[record.trade_date] != record.approved_rows:
        raise ValueError("bootstrap完整日源计数不符批准")
    with resource_cleanup(
        lambda: connection.execute(f"DROP TABLE IF EXISTS {BOOTSTRAP_DAY_SOURCE}")
    ):
        load_complete_source(
            connection, staging_root=staging_root, approval=approval, record=record
        )
        return write_json(
            operation_path(
                staging_root,
                approval,
                f"source/dates/{record.trade_date.isoformat()}/source-complete.json",
            ),
            record,
        )
