"""Operation-bound bootstrap records; no database ownership or event discovery."""

from __future__ import annotations

import json
import os
import shutil
import stat
from contextlib import contextmanager
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from orchestrator.defs.checks.stk_factor_pro import (
    factor_content_sha,
    factor_file_sha,
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
from orchestrator.defs.run_contracts.stk_factor_pro import BootstrapSpaceEstimate


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


def atomic_promote(temporary, path, *, replace_existing=False, on_replaced=None):
    for value in (temporary, path):
        require_stk_factor_pro_safe_path(value)
    if path.exists() and not replace_existing:
        raise ValueError("bootstrap不可变文件已经存在")
    if temporary.stat().st_dev != path.parent.stat().st_dev:
        raise ValueError("bootstrap必须同文件系统原子保存")
    with temporary.open("rb") as stream:
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    if on_replaced is not None:
        on_replaced()
    fsync_directory(path.parent)


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("bootstrap JSON重复键")
        result[key] = value
    return result


def read_json(path, record_type, *, known_records):
    path = Path(path)
    if path in known_records:
        record = known_records[path][0]
        if record is not None and type(record) is not record_type:
            raise ValueError("bootstrap已登记记录类型不符")
        return record
    require_stk_factor_pro_safe_path(path)
    if not path.exists():
        known_records[path] = (None, None, None)
        return None
    before = stk_factor_pro_fragment_file_signature(path)
    payload = path.read_bytes()
    value = json.loads(
        payload,
        object_pairs_hook=_pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError("非法JSON常量")),
    )
    record = C.parse_stk_factor_pro_record(record_type, value)
    if (
        C.stk_factor_pro_record_to_dict(record) != value
        or stk_factor_pro_fragment_file_signature(path) != before
    ):
        raise ValueError("bootstrap记录不规范或读回期间变化")
    known_records[path] = (record, sha256(payload).hexdigest(), before)
    return record


def write_json(
    path, record, *, known_records, mutable=False, check_space=None, on_replaced=None
):
    path = Path(path)
    require_stk_factor_pro_safe_path(path)
    existing = read_json(path, type(record), known_records=known_records)
    if existing == record:
        if check_space is not None:
            check_space(
                "已有业务记录复用",
                path=path,
                trade_date=getattr(record, "trade_date", None),
                event="record_saved",
            )
        return existing, known_records[path][1]
    if existing is not None and not mutable:
        raise ValueError("bootstrap不可变记录内容冲突")
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
    if check_space is not None:
        check_space(
            "业务记录保存前", path=path, trade_date=getattr(record, "trade_date", None)
        )
    before = known_records[path][2]
    path.parent.mkdir(parents=True, exist_ok=True)
    require_stk_factor_pro_safe_path(path)
    temporary = path.with_name(path.name + f".{uuid4().hex}.tmp")
    with temporary.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    if (
        stk_factor_pro_fragment_file_signature(path) if path.exists() else None
    ) != before:
        raise ValueError("bootstrap记录写入期间改变")

    def replaced():
        known_records.pop(path, None)
        if on_replaced is not None:
            on_replaced()

    atomic_promote(temporary, path, replace_existing=mutable, on_replaced=replaced)
    digest = sha256(payload).hexdigest()
    known_records[path] = (
        record,
        digest,
        stk_factor_pro_fragment_file_signature(path),
    )
    if check_space is not None:
        check_space(
            "业务记录保存后",
            path=path,
            trade_date=getattr(record, "trade_date", None),
            event="record_saved",
        )
    return record, digest


def approval_sha(staging_root, approval, *, known_records):
    path = operation_path(staging_root, approval, "approval.json")
    if (
        read_json(path, C.StkFactorProBootstrapApproval, known_records=known_records)
        != approval
    ):
        raise ValueError("bootstrap批准记录不存在或与当前operation不符")
    return known_records[path][1]


def load_approved_counts(connection, *, staging_root, approval, known_records):
    path = operation_path(staging_root, approval, approval.approved_daily_counts_ref)
    if path in known_records:
        rows, digest, _ = known_records[path]
        if digest != approval.approved_daily_counts_digest:
            raise ValueError("bootstrap批准日计数摘要不符")
        return rows
    before = stk_factor_pro_fragment_file_signature(path)
    digest = factor_file_sha(path)
    if digest != approval.approved_daily_counts_digest:
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
        if stk_factor_pro_fragment_file_signature(path) != before:
            raise ValueError("bootstrap批准日计数读取期间改变")
        known_records[path] = (rows, digest, before)
        return rows


def fragment_from_relation(connection, *, path, operation_root, relation):
    from orchestrator.defs.io.stk_factor_pro_candidates import (
        describe_stk_factor_pro_fragment,
    )

    return describe_stk_factor_pro_fragment(
        connection, path=path, root=operation_root, relation=relation
    )


def _source_identity(staging_root, approval, record, *, known_records):
    if (
        record.operation_id != approval.operation_id
        or record.approval_digest
        != approval_sha(staging_root, approval, known_records=known_records)
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
        approval,
        approval_sha(staging_root, approval, known_records=known_records),
        month,
        record.selected_dates,
    ) or record.fragments_manifest_digest != C.fragments_manifest_digest(
        record.fragments
    ):
        raise ValueError("bootstrap完整日查询范围或片段清单摘要不符")


def read_stk_factor_pro_bootstrap_source_complete(
    connection, *, staging_root, approval, trade_date, known_records
):
    path = operation_path(
        staging_root,
        approval,
        f"source/dates/{trade_date.isoformat()}/source-complete.json",
    )
    first_read = path not in known_records
    record = read_json(
        path, C.StkFactorProBootstrapSourceComplete, known_records=known_records
    )
    if record is not None:
        try:
            if first_read:
                _source_identity(
                    staging_root, approval, record, known_records=known_records
                )
            if record.trade_date != trade_date:
                raise ValueError("bootstrap源记录固定日期不符")
        except BaseException:
            if first_read:
                known_records.pop(path, None)
            raise
    return record


def _verify_bootstrap_source_fragment(connection, *, path, root, fragment):
    before = stk_factor_pro_fragment_file_signature(path)
    relation = f"stk_factor_bootstrap_verify_fragment_{uuid4().hex}"
    connection.execute(
        f"CREATE TEMP TABLE {relation} AS SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
    )
    try:
        if (
            fragment_from_relation(
                connection, path=path, operation_root=root, relation=relation
            )
            != fragment
        ):
            raise ValueError("bootstrap片段完整内容不符")
        if stk_factor_pro_fragment_file_signature(path) != before:
            raise ValueError("bootstrap源片段完整核验期间改变")
    except BaseException:
        with resource_cleanup(
            lambda: connection.execute(f"DROP TABLE IF EXISTS {relation}")
        ):
            raise
    return before, relation


class BootstrapFragmentVerification:
    """Successful fragment facts scoped to one caller connection and one month."""

    def __init__(self, connection, *, staging_root, approval, month, known_records):
        if month not in approval.month_limits:
            raise ValueError("bootstrap片段验证月份不属于本次批准")
        self._connection = connection
        self._staging_root = Path(staging_root)
        self._approval = approval
        self._known_records = known_records
        self._approval_digest = approval_sha(
            staging_root, approval, known_records=known_records
        )
        self._month = month
        self._entries = {}
        self._relations = {}
        self._closed = False

    def close(self):
        with resource_cleanup(
            *(
                lambda path=path: self.release_source_relation(path)
                for path in tuple(self._relations)
            )
        ):
            self._closed = True
            self._entries.clear()

    def _require_scope(self, connection, *, staging_root, approval, record=None):
        if (
            self._closed
            or connection is not self._connection
            or Path(staging_root) != self._staging_root
            or approval != self._approval
            or approval_sha(staging_root, approval, known_records=self._known_records)
            != self._approval_digest
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

    def remember_saved(self, *, connection, path, fragment, source_relation):
        """Accept only the writer's already-complete real Parquet readback."""
        self._require_scope(
            connection, staging_root=self._staging_root, approval=self._approval
        )
        if path != self._path(fragment):
            raise ValueError("bootstrap已核片段路径与描述不符")
        before = stk_factor_pro_fragment_file_signature(path)
        self._entries[path] = (before, fragment)
        self._relations[path] = source_relation
        self._known_records[path] = (fragment, fragment.file_sha256, before)

    def release_source_relation(self, path):
        relation = self._relations.pop(path, None)
        if relation is not None:
            self._connection.execute(f"DROP TABLE IF EXISTS {relation}")

    def verify(self, connection, *, staging_root, approval, record, reference):
        self._require_scope(
            connection, staging_root=staging_root, approval=approval, record=record
        )
        path = self._path(reference.fragment)
        before = stk_factor_pro_fragment_file_signature(path)
        observed = self._entries.get(path)
        if observed is not None and observed != (before, reference.fragment):
            raise ValueError("bootstrap片段首次确认后的身份或描述已改变")
        if observed is None:
            before, relation = _verify_bootstrap_source_fragment(
                connection,
                path=path,
                root=operation_root(staging_root, approval),
                fragment=reference.fragment,
            )
            self._entries[path] = (before, reference.fragment)
            self._relations[path] = relation
            self._known_records[path] = (
                reference.fragment,
                reference.fragment.file_sha256,
                before,
            )
        if path not in self._relations:
            raise ValueError("bootstrap片段本次关系已释放，不能重新回盘读取")
        return path, before, self._relations[path]


def load_complete_source(
    connection, *, staging_root, approval, record, verification, known_records
):
    """Restore one day from each necessary fragment's first actual readback."""
    path = operation_path(
        staging_root,
        approval,
        f"source/dates/{record.trade_date.isoformat()}/source-complete.json",
    )
    if path not in known_records or known_records[path][0] != record:
        raise ValueError("bootstrap源恢复缺少本次首次核实的完整日记录")
    verification._require_scope(
        connection, staging_root=staging_root, approval=approval, record=record
    )
    for prior_path, (_, fragment) in tuple(verification._entries.items()):
        if fragment.max_trade_date < record.trade_date:
            verification.release_source_relation(prior_path)
    fields = ",".join(
        f'CAST(NULL AS {kind}) AS "{name}"'
        for name, kind in C.STK_FACTOR_PRO_RAW_COLUMN_TYPES.items()
    )
    connection.execute(
        f"CREATE TEMP TABLE {BOOTSTRAP_DAY_SOURCE} AS SELECT {fields} WHERE false"
    )
    actual_rows = 0
    consumed = []
    primary = None
    try:
        for reference in record.fragments:
            fragment = reference.fragment
            wanted = f"source/month={record.month_start:%Y-%m}/attempt_id={record.attempt_id}/fragment-{reference.fragment_no:06d}.parquet"
            if (
                fragment.relative_path != wanted
                or reference.attempt_id != record.attempt_id
            ):
                raise ValueError("bootstrap片段位置/attempt不符")
            fragment_path, _, relation = verification.verify(
                connection,
                staging_root=staging_root,
                approval=approval,
                record=record,
                reference=reference,
            )
            count = connection.execute(
                f"INSERT INTO {BOOTSTRAP_DAY_SOURCE} SELECT * FROM {relation} WHERE trade_date=?",
                [record.trade_date.strftime("%Y%m%d")],
            ).fetchone()[0]
            if not count:
                raise ValueError("bootstrap引用片段没有本日行")
            actual_rows += count
            if fragment.max_trade_date <= record.trade_date:
                consumed.append(fragment_path)
        if (
            actual_rows != record.actual_rows
            or factor_content_sha(connection, BOOTSTRAP_DAY_SOURCE)
            != record.date_content_sha256
        ):
            raise ValueError("bootstrap完整日源行数/业务内容不符")
        return BOOTSTRAP_DAY_SOURCE
    except BaseException as error:
        primary = error
        raise
    finally:
        releases = [
            lambda fragment_path=fragment_path: verification.release_source_relation(
                fragment_path
            )
            for fragment_path in consumed
        ]
        if primary is not None:
            releases.append(
                lambda: connection.execute(
                    f"DROP TABLE IF EXISTS {BOOTSTRAP_DAY_SOURCE}"
                )
            )
        with resource_cleanup(*releases):
            if primary is not None:
                raise primary


def write_stk_factor_pro_bootstrap_source_complete(
    connection,
    *,
    staging_root,
    approval,
    record,
    approved_date_rows,
    source_relation,
    check_space,
    verification=None,
    known_records,
):
    if (
        record.operation_id != approval.operation_id
        or record.approval_digest
        != approval_sha(staging_root, approval, known_records=known_records)
        or record.source_identity_digest != approval.source_identity_digest
        or record.contract_content_digest != approval.contract_content_digest
        or record.source_cutoff_trade_date != approval.source_cutoff_trade_date
        or not approval.start_trade_date <= record.trade_date <= approval.end_trade_date
        or source_relation != BOOTSTRAP_DAY_SOURCE
    ):
        raise ValueError("bootstrap完整日源与本次批准/关系不符")
    if (
        type(approved_date_rows) is not int
        or approved_date_rows != record.approved_rows
    ):
        raise ValueError("bootstrap完整日源计数不符批准")
    if verification is not None:
        verification._require_scope(
            connection, staging_root=staging_root, approval=approval, record=record
        )
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
    return write_json(
        operation_path(
            staging_root,
            approval,
            f"source/dates/{record.trade_date.isoformat()}/source-complete.json",
        ),
        record,
        check_space=check_space,
        known_records=known_records,
    )


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
    observed_row_bytes=C.STK_FACTOR_PRO_ESTIMATED_ROW_BYTES,
    observed_file_overhead=C.STK_FACTOR_PRO_ESTIMATED_FILE_OVERHEAD_BYTES,
    observed_record_bytes=C.STK_FACTOR_PRO_ESTIMATED_RECORD_BYTES,
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
    _space_count(
        observed_row_bytes,
        "observed_row_bytes",
        minimum=C.STK_FACTOR_PRO_ESTIMATED_ROW_BYTES,
    )
    _space_count(
        observed_file_overhead,
        "observed_file_overhead",
        minimum=C.STK_FACTOR_PRO_ESTIMATED_FILE_OVERHEAD_BYTES,
    )
    _space_count(
        observed_record_bytes,
        "observed_record_bytes",
        minimum=C.STK_FACTOR_PRO_ESTIMATED_RECORD_BYTES,
    )

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
        required = amount + C.STK_FACTOR_PRO_FREE_SPACE_MARGIN_BYTES
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
