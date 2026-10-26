"""Operation-bound bootstrap records; no database ownership or event discovery."""

from __future__ import annotations

import json
import os
import shutil
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
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
    stk_factor_pro_fragment_file_signature,
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


def write_json(path, record, *, mutable=False, check_space=None):
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
        if check_space is not None:
            check_space(
                "已有业务记录读回",
                path=path,
                trade_date=getattr(record, "trade_date", None),
                event="record_saved",
            )
        return existing
    if check_space is not None:
        check_space(
            "业务记录保存前", path=path, trade_date=getattr(record, "trade_date", None)
        )
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
    if check_space is not None:
        check_space(
            "业务记录保存读回后",
            path=path,
            trade_date=getattr(record, "trade_date", None),
            event="record_saved",
        )
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


def _verify_bootstrap_source_fragment(connection, *, path, root, fragment):
    before = stk_factor_pro_fragment_file_signature(path)
    relation = "stk_factor_bootstrap_verify_fragment"
    connection.execute(
        f"CREATE OR REPLACE TEMP VIEW {relation} AS SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
    )
    with resource_cleanup(
        lambda: connection.execute(f"DROP VIEW IF EXISTS {relation}")
    ):
        if (
            fragment_from_relation(
                connection, path=path, operation_root=root, relation=relation
            )
            != fragment
        ):
            raise ValueError("bootstrap片段完整内容不符")
    if stk_factor_pro_fragment_file_signature(path) != before:
        raise ValueError("bootstrap源片段完整核验期间改变")
    return before


class BootstrapFragmentVerification:
    """Successful fragment facts scoped to one caller connection and one month."""

    def __init__(self, connection, *, staging_root, approval, month):
        if month not in approval.month_limits:
            raise ValueError("bootstrap片段验证月份不属于本次批准")
        self._connection = connection
        self._staging_root = Path(staging_root)
        self._approval = approval
        self._approval_digest = approval_sha(staging_root, approval)
        self._month = month
        self._entries = {}
        self._closed = False

    def close(self):
        self._entries.clear()
        self._closed = True

    def _require_scope(self, connection, *, staging_root, approval, record=None):
        if (
            self._closed
            or connection is not self._connection
            or Path(staging_root) != self._staging_root
            or approval != self._approval
            or approval_sha(staging_root, approval) != self._approval_digest
        ):
            raise ValueError("bootstrap片段验证上下文已关闭或连接/operation/批准不符")
        if record is not None and (
            record.month_start,
            record.month_end_exclusive,
            record.row_upper_bound,
        ) != (
            self._month.month_start,
            self._month.month_end_exclusive,
            self._month.row_upper_bound,
        ):
            raise ValueError("bootstrap片段验证上下文月份不符")

    def _path(self, fragment):
        prefix = f"source/month={self._month.month_start:%Y-%m}/attempt_id="
        if not fragment.relative_path.startswith(prefix):
            raise ValueError("bootstrap片段验证引用不属于当前月份source")
        return operation_path(
            self._staging_root, self._approval, fragment.relative_path
        )

    def remember_saved(self, *, connection, path, fragment):
        """Accept only the writer's already-complete real Parquet readback."""
        self._require_scope(
            connection, staging_root=self._staging_root, approval=self._approval
        )
        if path != self._path(fragment):
            raise ValueError("bootstrap已核片段路径与描述不符")
        before = stk_factor_pro_fragment_file_signature(path)
        if (
            factor_file_sha(path) != fragment.file_sha256
            or stk_factor_pro_fragment_file_signature(path) != before
        ):
            raise ValueError("bootstrap已核片段登记前改变")
        self._entries[path] = (before, fragment)

    def verify(self, connection, *, staging_root, approval, record, reference):
        self._require_scope(
            connection, staging_root=staging_root, approval=approval, record=record
        )
        path = self._path(reference.fragment)
        before = stk_factor_pro_fragment_file_signature(path)
        observed = self._entries.get(path)
        if observed != (before, reference.fragment):
            self._entries.pop(path, None)
            before = _verify_bootstrap_source_fragment(
                connection,
                path=path,
                root=operation_root(staging_root, approval),
                fragment=reference.fragment,
            )
            self._entries[path] = (before, reference.fragment)
        return path, before


def load_complete_source(
    connection, *, staging_root, approval, record, verification=None
):
    """Verify exact referenced fragments, then materialize one bounded full day."""
    _source_identity(staging_root, approval, record)
    if verification is not None:
        verification._require_scope(
            connection, staging_root=staging_root, approval=approval, record=record
        )
    paths = []
    identities = []
    root = operation_root(staging_root, approval)
    for reference in record.fragments:
        fragment = reference.fragment
        wanted = f"source/month={record.month_start:%Y-%m}/attempt_id={record.attempt_id}/fragment-{reference.fragment_no:06d}.parquet"
        if (
            fragment.relative_path != wanted
            or reference.attempt_id != record.attempt_id
        ):
            raise ValueError("bootstrap片段位置/attempt不符")
        if verification is None:
            path = operation_path(staging_root, approval, wanted)
            before = _verify_bootstrap_source_fragment(
                connection, path=path, root=root, fragment=fragment
            )
        else:
            path, before = verification.verify(
                connection,
                staging_root=staging_root,
                approval=approval,
                record=record,
                reference=reference,
            )
        relation = "stk_factor_bootstrap_fragment_day_presence"
        connection.execute(
            f"CREATE OR REPLACE TEMP VIEW {relation} AS SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
        )
        with resource_cleanup(
            lambda relation=relation: connection.execute(
                f"DROP VIEW IF EXISTS {relation}"
            )
        ):
            if not connection.execute(
                f"SELECT count(*) FROM {relation} WHERE trade_date=?",
                [record.trade_date.strftime("%Y%m%d")],
            ).fetchone()[0]:
                raise ValueError("bootstrap引用片段没有本日行")
        if stk_factor_pro_fragment_file_signature(path) != before:
            raise ValueError("bootstrap源片段本日读取期间改变")
        paths.append(str(path))
        identities.append((path, before))
    for path, before in identities:
        if stk_factor_pro_fragment_file_signature(path) != before:
            raise ValueError("bootstrap源片段本日物化前改变")
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
        for path, before in identities:
            if stk_factor_pro_fragment_file_signature(path) != before:
                raise ValueError("bootstrap源片段本日物化期间改变")
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
    connection, *, staging_root, approval, record, check_space, verification=None
):
    _source_identity(staging_root, approval, record)
    counts = dict(
        load_approved_counts(connection, staging_root=staging_root, approval=approval)
    )
    if counts[record.trade_date] != record.approved_rows:
        raise ValueError("bootstrap完整日源计数不符批准")
    check_space(
        "完整日源记录保存前",
        path=operation_path(
            staging_root,
            approval,
            f"source/dates/{record.trade_date.isoformat()}/source-complete.json",
        ),
        trade_date=record.trade_date,
        rows=record.actual_rows,
    )
    with resource_cleanup(
        lambda: connection.execute(f"DROP TABLE IF EXISTS {BOOTSTRAP_DAY_SOURCE}")
    ):
        load_complete_source(
            connection,
            staging_root=staging_root,
            approval=approval,
            record=record,
            verification=verification,
        )
        return write_json(
            operation_path(
                staging_root,
                approval,
                f"source/dates/{record.trade_date.isoformat()}/source-complete.json",
            ),
            record,
            check_space=check_space,
        )


@dataclass(frozen=True, slots=True)
class BootstrapSpaceEstimate:
    """Additional bytes still required, not bytes already present on disk."""

    source_bytes: int
    candidate_bytes: int
    temp_bytes: int
    record_bytes: int

    def __post_init__(self):
        for name in ("source_bytes", "candidate_bytes", "temp_bytes", "record_bytes"):
            _space_count(getattr(self, name), name)


def _space_count(value, name, *, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"bootstrap空间估算{name}必须是至少{minimum}的整数")
    return value


def estimate_bootstrap_space(
    *,
    pending_source_rows_by_month,
    remaining_layer_rows,
    work_rows,
    pending_fetch_rows,
    remaining_date_count,
    statistics_only=False,
    remaining_layer_totals=None,
    observed_row_bytes=4178,
    observed_file_overhead=4 * 1024 * 1024,
    observed_record_bytes=1024 * 1024,
):
    """LLD 17.8.2 arithmetic over already verified counts; performs no IO."""
    for name, values in (
        ("pending_source_rows_by_month", pending_source_rows_by_month),
        ("remaining_layer_rows", remaining_layer_rows),
        ("work_rows", work_rows),
    ):
        if type(values) is not tuple:
            raise ValueError(f"bootstrap空间估算{name}必须是内部tuple")
        for value in values:
            _space_count(value, name)
    if len(work_rows) != 2 or type(statistics_only) is not bool:
        raise ValueError("bootstrap空间估算须提供两层工作行数及明确统计模式")
    if remaining_layer_totals is not None:
        if (
            type(remaining_layer_totals) is not tuple
            or len(remaining_layer_totals) != 2
        ):
            raise ValueError("bootstrap候选聚合量须为总行数和非空文件数的二元tuple")
        total_rows, file_count = remaining_layer_totals
        _space_count(total_rows, "remaining_layer_totals rows")
        _space_count(file_count, "remaining_layer_totals files")
        if remaining_layer_rows:
            raise ValueError("bootstrap候选逐文件行数和聚合量不能同时计入")
        if (file_count == 0 and total_rows != 0) or total_rows < file_count:
            raise ValueError("bootstrap候选聚合量每个非空文件至少须有一行")
    _space_count(pending_fetch_rows, "pending_fetch_rows")
    if pending_fetch_rows > 5000:
        raise ValueError("bootstrap空间估算当前批不能超过5000行")
    _space_count(remaining_date_count, "remaining_date_count")
    _space_count(observed_row_bytes, "observed_row_bytes", minimum=4178)
    _space_count(
        observed_file_overhead, "observed_file_overhead", minimum=4 * 1024 * 1024
    )
    _space_count(observed_record_bytes, "observed_record_bytes", minimum=1024 * 1024)

    def file_bytes(rows):
        return observed_row_bytes * rows + observed_file_overhead if rows else 0

    if statistics_only and (
        any(pending_source_rows_by_month)
        or any(remaining_layer_rows)
        or pending_fetch_rows
        or (remaining_layer_totals is not None and any(remaining_layer_totals))
    ):
        raise ValueError("bootstrap仅本地统计不能含源导出或两层新增工作")
    source_bytes = 0
    for rows in pending_source_rows_by_month:
        full, tail = divmod(rows, 5000)
        source_bytes += full * file_bytes(5000) + file_bytes(tail)
    candidate_bytes = (
        observed_row_bytes * remaining_layer_totals[0]
        + observed_file_overhead * remaining_layer_totals[1]
        if remaining_layer_totals is not None
        else sum(file_bytes(rows) for rows in remaining_layer_rows)
    )
    temp_bytes = 4 * (
        file_bytes(work_rows[0])
        if statistics_only
        else file_bytes(pending_fetch_rows) + sum(file_bytes(n) for n in work_rows)
    )
    return BootstrapSpaceEstimate(
        source_bytes,
        candidate_bytes,
        temp_bytes,
        observed_record_bytes * (remaining_date_count + 1),
    )


def _bootstrap_space_ancestor(path):
    if not isinstance(path, Path):
        raise TypeError("bootstrap空间检查路径必须是内部Path")
    require_stk_factor_pro_safe_path(path)
    for ancestor in (path, *path.parents):
        try:
            info = ancestor.stat()
        except FileNotFoundError:
            continue
        if not stat.S_ISDIR(info.st_mode):
            raise NotADirectoryError(str(ancestor))
        return ancestor, info.st_dev
    raise FileNotFoundError(str(path))


def require_bootstrap_space(
    *, estimate, operation_id, stage, staging_root, temp_directory
):
    """Check each used device once, without creating directories or probe files."""
    if not isinstance(estimate, BootstrapSpaceEstimate):
        raise TypeError("bootstrap空间检查缺内部预算")
    C.validate_stk_factor_pro_identifier(operation_id)
    if type(stage) is not str or not stage.strip():
        raise ValueError("bootstrap空间检查缺阶段")
    devices = {}
    requirements = (
        (
            staging_root,
            estimate.source_bytes + estimate.candidate_bytes + estimate.record_bytes,
        ),
        (temp_directory, estimate.temp_bytes),
    )
    for path, amount in requirements:
        if not amount:
            continue
        try:
            ancestor, device = _bootstrap_space_ancestor(path)
        except OSError as error:
            raise ValueError(
                f"bootstrap空间检查失败：operation={operation_id}，阶段={stage}，"
                f"设备无法确认，required={amount}，free=未知；请管理员检查目录和磁盘"
            ) from error
        previous = devices.get(device)
        devices[device] = (
            ancestor if previous is None else previous[0],
            amount + (0 if previous is None else previous[1]),
        )
    for device, (ancestor, amount) in devices.items():
        required = amount + 16 * 1024 * 1024
        try:
            free = shutil.disk_usage(ancestor).free
        except OSError as error:
            raise ValueError(
                f"bootstrap空间检查失败：operation={operation_id}，阶段={stage}，"
                f"设备={device}，required={required}，free=未知；请管理员检查磁盘容量"
            ) from error
        if type(free) is not int or free < 0:
            raise ValueError("bootstrap磁盘可用空间不是有效非负整数")
        if free < required:
            raise ValueError(
                f"bootstrap空间不足：operation={operation_id}，阶段={stage}，"
                f"设备={device}，required={required}，free={free}；"
                "停止后续读写，请管理员释放或扩充空间；不删除旧源"
            )
