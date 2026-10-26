"""Current-run per-file publication; no old candidate/checkpoint continuation."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import dagster as dg
from duckdb import Error as DuckDBError

from orchestrator.defs.checks.stk_factor_pro import (
    audit_stk_factor_pro_file,
    factor_columns,
    factor_content_sha,
    factor_file_sha,
    require_factor_relation,
)
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, duckdb_string
from orchestrator.defs.io.stk_factor_pro_candidates import (
    DAY_PRIOR,
    DAY_SOURCE,
    HISTORY_DAY_SOURCE,
    RAW_EXPECTED,
    SILVER_EXPECTED,
    build_stk_factor_pro_raw_candidate,
    build_stk_factor_pro_raw_candidate_from_relation,
    build_stk_factor_pro_silver_candidate,
    require_stk_factor_pro_candidate_path,
)
from orchestrator.defs.io.stk_factor_pro_candidates import (
    require_stk_factor_pro_safe_path as _safe,
)
from orchestrator.defs.io.stk_factor_pro_download import (
    require_stk_factor_pro_current_day_source,
)
from orchestrator.defs.io.stk_factor_pro_history import (
    _json_read,
    _json_write,
    _ref_path,
    _run_root,
    read_stk_factor_pro_history_plan,
    read_stk_factor_pro_history_ranges,
    read_stk_factor_pro_source_files,
    recheck_stk_factor_pro_history_inputs,
    verify_stk_factor_pro_current_source,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    raw_stk_factor_pro_path,
    silver_stock_factor_pro_path,
    stk_factor_pro_run_staging_root,
)
from orchestrator.defs.run_contracts.stk_factor_pro import (
    STK_FACTOR_PRO_HISTORY_MERGE_BATCH_TRADE_DAYS,
    STK_FACTOR_PRO_TIMEZONE,
    PublicationCompleteRecord,
    PublishedTarget,
    RecordRef,
    StkFactorProPublicationRecord,
    VerifiedSource,
    parse_stk_factor_pro_record,
    stk_factor_pro_history_input_digest,
    stk_factor_pro_record_to_dict,
    stk_factor_pro_scope_digest,
)


def _roots(lake: Path, staging: Path) -> None:
    for root in (lake, staging):
        _safe(root)
        if not root.is_dir():
            raise ValueError("技术因子目标根目录不存在")
    if lake == staging or lake in staging.parents or staging in lake.parents:
        raise ValueError("技术因子正式根和staging不能重叠")
    if any(
        root == Path("/Volumes") or Path("/Volumes") in root.parents
        for root in (lake, staging)
    ) and (lake, staging) != (Path(DEFAULT_LAKE_ROOT), Path(DEFAULT_LAKE_STAGING_ROOT)):
        raise ValueError("技术因子仅允许既定正式Volumes根")
    if lake == Path(DEFAULT_LAKE_ROOT) and not lake.parent.is_mount():
        raise ValueError("技术因子正式数据卷未挂载，禁止写入")
    if lake.stat().st_dev != staging.stat().st_dev:
        raise ValueError("技术因子候选和正式目标必须同一文件系统")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _json_value(value):
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds")
    if type(value) is date:
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    return value


def read_stk_factor_pro_publication_record(path: Path) -> StkFactorProPublicationRecord:
    _safe(path)
    value = json.loads(path.read_text())
    record = parse_stk_factor_pro_record(StkFactorProPublicationRecord, value)
    if stk_factor_pro_record_to_dict(record) != value:
        raise ValueError("技术因子发布记录日期或时刻不是规范表示")
    expected_suffix = (
        f"run_id={record.identity.creator_run_id}",
        "publication",
        record.phase,
        record.trade_date.isoformat(),
        record.layer,
        f"{record.stage}.json",
    )
    if path.parts[-len(expected_suffix) :] != expected_suffix:
        raise ValueError("技术因子发布记录物理路径与run、日期、层或状态不符")
    return record


def _write_record(path: Path, record: StkFactorProPublicationRecord) -> None:
    _safe(path)
    if path.exists():
        raise ValueError("技术因子不沿已有发布记录续跑，请创建重新下载的新任务")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    _safe(temporary)
    payload = json.dumps(
        _json_value(asdict(record)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    with temporary.open("x") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)
    if read_stk_factor_pro_publication_record(path) != record:
        raise ValueError("技术因子发布记录读回不符")


def _hash_if_exists(path: Path) -> str | None:
    _safe(path)
    return factor_file_sha(path) if path.is_file() else None


def _publish_file(
    connection,
    *,
    source,
    run_root,
    target,
    candidate_audit,
    prior,
    expected_relation,
    check_cancel,
    raw_guard,
    phase="day",
    unrefreshed_keys_ref=None,
    unrefreshed_count=None,
    scope_facts=None,
):
    candidate = candidate_audit.path
    for path in (candidate, target):
        _safe(path)
    if not candidate.is_relative_to(run_root) or not candidate_audit.passed:
        raise ValueError("技术因子候选未通过检查或不属于当前run")
    layer = candidate_audit.layer
    directory = (
        run_root
        / "publication"
        / phase
        / candidate_audit.trade_date.isoformat()
        / layer
    )
    if (directory / "intent.json").exists() or (directory / "complete.json").exists():
        raise ValueError("技术因子不得使用已有intent或complete继续发布")
    if _hash_if_exists(target) != prior:
        raise ValueError("技术因子正式目标在构造候选时已改变")
    unchanged = False
    if prior is not None:
        # Candidate and current target must both equal this run's independent expected relation.
        current_audit = audit_stk_factor_pro_file(
            connection,
            path=target,
            expected_relation=expected_relation,
            target_trade_date=candidate_audit.trade_date,
            layer=layer,
        )
        unchanged = current_audit.passed
    raw_guard()
    with candidate.open("rb") as stream:
        os.fsync(stream.fileno())
    mode = "reuse" if unchanged else "replace"
    if phase == "history":
        scope_digest = source.source_complete.scope_digest
        history_input_digest = source.source_complete.history_input_digest
        source_manifest_digest = source.source_complete.files_manifest_digest
        day_source_digest = None
    elif phase == "day":
        scope_digest, day_source_digest = source.scope_digest, source.day_source_digest
        history_input_digest = source_manifest_digest = None
    else:
        raise ValueError("技术因子发布阶段不合法")
    record = StkFactorProPublicationRecord(
        1,
        source.identity,
        phase,
        candidate_audit.trade_date,
        layer,
        source.contract,
        scope_digest,
        history_input_digest,
        day_source_digest,
        source_manifest_digest,
        str(target),
        candidate.relative_to(run_root).as_posix(),
        prior,
        candidate_audit.file_sha256,
        candidate_audit.row_count,
        prior if unchanged else candidate_audit.file_sha256,
        mode,
        "intent",
        unrefreshed_keys_ref,
        unrefreshed_count,
        None,
        None,
        None,
    )
    _write_record(directory / "intent.json", record)
    check_cancel()
    raw_guard()
    if (
        _hash_if_exists(target) != prior
        or factor_file_sha(candidate) != record.candidate_sha256
    ):
        raise ValueError("技术因子目标或候选在发布前改变")
    target.parent.mkdir(parents=True, exist_ok=True)
    _safe(target)
    if target.parent.stat().st_dev != candidate.stat().st_dev:
        raise ValueError("技术因子提升跨文件系统")
    if shutil.disk_usage(target.parent).free < candidate.stat().st_size:
        raise ValueError("技术因子发布磁盘空间不足")
    if not unchanged:
        os.replace(candidate, target)
        _fsync_directory(target.parent)
    # No cancellation boundary here: finish facts for a file already replaced.
    actual_sha = factor_file_sha(target)
    observed = tuple(
        (r[0], r[1])
        for r in connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?,hive_partitioning=false)",
            [str(target)],
        ).fetchall()
    )
    row_count = connection.execute(
        "SELECT count(*) FROM read_parquet(?,hive_partitioning=false)", [str(target)]
    ).fetchone()[0]
    if (
        actual_sha != record.expected_published_sha256
        or observed != candidate_audit.observed_schema
        or row_count != candidate_audit.row_count
        or factor_file_sha(target) != actual_sha
    ):
        raise ValueError("技术因子正式文件与已完整校验的候选身份不符")
    # os.replace moved those exact validated bytes. Reuse the all-field audit;
    # do not scan/join 259 columns a second time just to emit the same check.
    actual = replace(candidate_audit, path=target, file_sha256=actual_sha)
    raw_guard()
    if not actual.passed or actual.file_sha256 != record.expected_published_sha256:
        raise ValueError("技术因子正式文件发布读回不符")
    complete = replace(
        record,
        stage="complete",
        verified_at=datetime.now(ZoneInfo(STK_FACTOR_PRO_TIMEZONE)),
        actual_sha256=actual.file_sha256,
        actual_rows=actual.row_count,
    )
    complete_path = directory / "complete.json"
    _write_record(complete_path, complete)
    reference = RecordRef(
        source.identity.creator_run_id,
        complete_path.relative_to(run_root).as_posix(),
        factor_file_sha(complete_path),
    )
    return PublishedTarget(
        candidate_audit.trade_date,
        layer,
        False,
        actual.file_sha256,
        actual.row_count,
        reference,
        0 if unrefreshed_count is None else unrefreshed_count,
        None if scope_facts is None else scope_facts[0],
        None if scope_facts is None else scope_facts[1],
        None if scope_facts is None else 1,
    ), actual


def publish_stk_factor_pro_day(
    connection, *, source, lake_root: Path, staging_root: Path, check_cancel
):
    require_stk_factor_pro_current_day_source(connection, source)
    _roots(lake_root, staging_root)
    day = source.identity.target_trade_date.isoformat()
    root = stk_factor_pro_run_staging_root(
        staging_root, source.identity.creator_run_id, day
    )
    raw = raw_stk_factor_pro_path(lake_root, day)
    silver = silver_stock_factor_pro_path(lake_root, day)
    for path in (root, raw, silver):
        _safe(path)
    raw_candidate = root / "candidates" / "day" / "raw" / "data.parquet"
    silver_candidate = root / "candidates" / "day" / "silver" / "data.parquet"
    for path in (raw_candidate, silver_candidate):
        require_stk_factor_pro_candidate_path(candidate_path=path, run_root=root)
    if (root / "candidates" / "day").exists() or (
        root / "publication" / "day"
    ).exists():
        raise ValueError("技术因子当前run已有日候选或发布记录，不接受续跑")
    source_rows = connection.execute(f"SELECT count(*) FROM {DAY_SOURCE}").fetchone()[0]
    if source_rows == 0 and not raw.exists():
        if silver.exists():
            raise ValueError("技术因子仅存在Silver，缺少对应Raw，请管理员处理")
        return
    check_cancel()
    prior_raw = _hash_if_exists(raw)
    raw_audit = build_stk_factor_pro_raw_candidate(
        connection,
        source=source,
        prior_path=raw if prior_raw else None,
        candidate_path=raw_candidate,
        run_root=root,
    )
    raw_target, raw_audit = _publish_file(
        connection,
        source=source,
        run_root=root,
        target=raw,
        candidate_audit=raw_audit,
        prior=prior_raw,
        expected_relation=RAW_EXPECTED,
        check_cancel=check_cancel,
        raw_guard=lambda: None,
    )
    yield raw_target, raw_audit
    check_cancel()

    def raw_guard():
        if _hash_if_exists(raw) != raw_audit.file_sha256:
            raise ValueError("技术因子生成Silver期间对应Raw已改变")

    raw_guard()
    prior_silver = _hash_if_exists(silver)
    silver_audit = build_stk_factor_pro_silver_candidate(
        connection,
        verified_raw_path=raw,
        target_trade_date=source.identity.target_trade_date,
        candidate_path=silver_candidate,
        run_root=root,
    )
    raw_guard()
    yield _publish_file(
        connection,
        source=source,
        run_root=root,
        target=silver,
        candidate_audit=silver_audit,
        prior=prior_silver,
        expected_relation=SILVER_EXPECTED,
        check_cancel=check_cancel,
        raw_guard=raw_guard,
    )


HISTORY_BATCH_SOURCE = "stk_factor_pro_history_batch_source"
HISTORY_PRIOR_SILVER = "stk_factor_pro_history_prior_silver"
HISTORY_SCOPE_ROWS = "stk_factor_pro_history_scope_rows"
HISTORY_UNREFRESHED_KEYS = "stk_factor_pro_history_unrefreshed_keys"


def _release_history_sql(connection, statements, primary=None):
    failures = []
    for statement in statements:
        try:
            connection.execute(statement)
        except DuckDBError as cleanup:
            failures.append(cleanup)
    if failures:
        reported = primary if primary is not None else failures[0]
        for cleanup in failures:
            reported.add_note(f"历史发布清理同时失败：{type(cleanup).__name__}")
        if primary is None:
            raise reported


def _history_day_release_sql():
    return (f"DROP VIEW IF EXISTS {HISTORY_SCOPE_ROWS}",) + tuple(
        f"DROP TABLE IF EXISTS {relation}"
        for relation in (
            HISTORY_DAY_SOURCE,
            DAY_PRIOR,
            RAW_EXPECTED,
            SILVER_EXPECTED,
            HISTORY_PRIOR_SILVER,
            HISTORY_UNREFRESHED_KEYS,
        )
    )


def _release_stk_factor_pro_history_day(connection, primary=None):
    _release_history_sql(connection, _history_day_release_sql(), primary)


def _release_stk_factor_pro_history_batch(connection, primary=None):
    _release_history_sql(
        connection,
        _history_day_release_sql() + (f"DROP TABLE IF EXISTS {HISTORY_BATCH_SOURCE}",),
        primary,
    )


@contextmanager
def _history_cleanup(connection, release):
    primary = None
    try:
        yield
    except BaseException as error:
        primary = error
        raise
    finally:
        # A failed close must be visible to .close(), rather than disappearing
        # as a note on GeneratorExit which the generator protocol suppresses.
        release(connection, None if isinstance(primary, GeneratorExit) else primary)


def _load_stk_factor_pro_history_batch(connection, *, paths, dates):
    # Exactly one source query materializes each batch. Per-date consumers only
    # touch this real table, never reopen all multi-year source files.
    connection.execute(
        f"CREATE TEMP TABLE {HISTORY_BATCH_SOURCE} AS SELECT {factor_columns()} "
        "FROM read_parquet(?,hive_partitioning=false) WHERE trade_date=ANY(?)",
        [[str(path) for path in paths], [day.strftime("%Y%m%d") for day in dates]],
    )


def _history_publication_dates(
    connection, *, source, units, paths, calendar, registered_dates
):
    for values in (calendar, registered_dates):
        if (
            type(values) is not tuple
            or any(type(day) is not date for day in values)
            or tuple(sorted(set(values))) != values
        ):
            raise ValueError("历史日历/已登记分区必须是升序唯一DATE tuple")
    identity = source.identity
    if (
        identity.target_trade_date not in calendar
        or identity.previous_trade_date not in calendar
        or any(unit.start_date not in calendar for unit in units)
    ):
        raise ValueError("历史日历未覆盖原T/P及已批准的真实最早日期")
    dates = tuple(
        day
        for day in calendar
        if day < identity.target_trade_date
        and any(unit.start_date <= day <= unit.end_date for unit in units)
    )
    if set(dates) - set(registered_dates):
        raise ValueError("历史发布日期尚未登记分区，禁止提升")
    # One aggregate over all current sources checks every source date before any
    # formal file can be changed. T rows remain in source evidence only.
    observed = connection.execute(
        "WITH scope AS (SELECT unnest(?::VARCHAR[]) AS ts_code, "
        "unnest(?::VARCHAR[]) AS start_date,unnest(?::VARCHAR[]) AS end_date) "
        "SELECT r.trade_date,count(*),count(*) FILTER (WHERE s.ts_code IS NULL) "
        "FROM read_parquet(?,hive_partitioning=false) r LEFT JOIN scope s "
        "ON r.ts_code=s.ts_code AND r.trade_date BETWEEN s.start_date AND s.end_date "
        "GROUP BY r.trade_date ORDER BY r.trade_date",
        [
            [unit.object_code for unit in units],
            [unit.start_date.strftime("%Y%m%d") for unit in units],
            [unit.end_date.strftime("%Y%m%d") for unit in units],
            [str(path) for path in paths],
        ],
    ).fetchall()
    approved = {day.strftime("%Y%m%d") for day in dates}
    target = identity.target_trade_date.strftime("%Y%m%d")
    for day, count, bad in observed:
        if bad or (day != target and day not in approved):
            raise ValueError(
                f"历史源日期不属于已批准开市/登记范围：{day}，行数{count}，越界{bad}"
            )
    return dates


def _history_unrefreshed_keys(
    connection, *, root, identity, day, layer, codes, prior_relation
):
    path = (
        root
        / "publication"
        / "history"
        / day.isoformat()
        / layer
        / "unrefreshed-keys.parquet"
    )
    temporary = path.with_suffix(".parquet.tmp")
    for value in (root, path, temporary):
        _safe(value)
    if path.exists() or temporary.exists():
        raise ValueError("历史缺原键诊断已存在，不接受续跑")
    if prior_relation is None:
        connection.execute(
            f"CREATE TEMP TABLE {HISTORY_UNREFRESHED_KEYS} (layer VARCHAR,ts_code VARCHAR,trade_date DATE)"
        )
    else:
        key_date = (
            "CAST(strptime(b.trade_date,'%Y%m%d') AS DATE)"
            if layer == "raw"
            else "b.trade_date"
        )
        source_date = "CAST(strptime(u.trade_date,'%Y%m%d') AS DATE)"
        connection.execute(
            f"CREATE TEMP TABLE {HISTORY_UNREFRESHED_KEYS} AS SELECT ?::VARCHAR AS layer, "
            f"b.ts_code,{key_date} AS trade_date FROM {prior_relation} b "
            f"WHERE b.ts_code=ANY(?) AND NOT EXISTS (SELECT 1 FROM {HISTORY_DAY_SOURCE} u "
            f"WHERE u.ts_code=b.ts_code AND {source_date}={key_date})",
            [layer, list(codes)],
        )

    def release_keys(connection, primary):
        _release_history_sql(
            connection, (f"DROP TABLE IF EXISTS {HISTORY_UNREFRESHED_KEYS}",), primary
        )

    with _history_cleanup(connection, release_keys):
        count = connection.execute(
            f"SELECT count(*) FROM {HISTORY_UNREFRESHED_KEYS}"
        ).fetchone()[0]
        path.parent.mkdir(parents=True, exist_ok=True)
        for value in (path, temporary):
            _safe(value)
        connection.execute(
            copy_query_to_parquet(
                f"SELECT layer,ts_code,trade_date FROM {HISTORY_UNREFRESHED_KEYS} ORDER BY ts_code,trade_date",
                temporary,
            )
        )
        schema = tuple(
            (row[0], row[1])
            for row in connection.execute(
                "DESCRIBE SELECT * FROM read_parquet(?,hive_partitioning=false)",
                [str(temporary)],
            ).fetchall()
        )
        difference = connection.execute(
            f"SELECT count(*) FROM ((SELECT layer,ts_code,trade_date FROM {HISTORY_UNREFRESHED_KEYS} "
            "EXCEPT ALL SELECT layer,ts_code,trade_date FROM read_parquet(?,hive_partitioning=false)) "
            "UNION ALL (SELECT layer,ts_code,trade_date FROM read_parquet(?,hive_partitioning=false) "
            f"EXCEPT ALL SELECT layer,ts_code,trade_date FROM {HISTORY_UNREFRESHED_KEYS}))",
            [str(temporary), str(temporary)],
        ).fetchone()[0]
        if (
            schema
            != (("layer", "VARCHAR"), ("ts_code", "VARCHAR"), ("trade_date", "DATE"))
            or difference
        ):
            raise ValueError("历史缺原键诊断读回不符")
        before = factor_file_sha(temporary)
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        if temporary.stat().st_dev != path.parent.stat().st_dev:
            raise ValueError("历史缺原键诊断跨文件系统")
        _safe(path)
        _safe(temporary)
        if path.exists():
            raise ValueError("历史缺原键诊断目标已改变")
        os.replace(temporary, path)
        _fsync_directory(path.parent)
        if factor_file_sha(path) != before:
            raise ValueError("历史缺原键诊断保存后SHA不符")
        return RecordRef(
            identity.creator_run_id, path.relative_to(root).as_posix(), before
        ), count


def _history_scope_facts(connection, *, relation, codes):
    selected = ",".join(duckdb_string(code) for code in codes)
    connection.execute(
        f"CREATE TEMP VIEW {HISTORY_SCOPE_ROWS} AS SELECT {factor_columns()} FROM {relation} WHERE ts_code IN ({selected})"
    )

    def release_scope(connection, primary):
        _release_history_sql(
            connection, (f"DROP VIEW IF EXISTS {HISTORY_SCOPE_ROWS}",), primary
        )

    with _history_cleanup(connection, release_scope):
        count = connection.execute(
            f"SELECT count(*) FROM {HISTORY_SCOPE_ROWS}"
        ).fetchone()[0]
        return count, factor_content_sha(connection, HISTORY_SCOPE_ROWS)


def publish_stk_factor_pro_history(
    connection,
    *,
    source: VerifiedSource,
    plan,
    ranges,
    lake_root: Path,
    staging_root: Path,
    calendar: tuple[date, ...],
    registered_dates: tuple[date, ...],
    recheck_inputs,
    check_cancel,
):
    """Publish actual history dates in bounded batches; yields each completed file."""
    if (
        not isinstance(source, VerifiedSource)
        or source.identity != plan.identity
        or source.contract != plan.contract
    ):
        raise ValueError("历史发布必须属于当前run完整计划及契约")
    _roots(lake_root, staging_root)
    root = stk_factor_pro_run_staging_root(
        staging_root,
        source.identity.creator_run_id,
        source.identity.target_trade_date.isoformat(),
    )
    _safe(root)
    actual_plan = read_stk_factor_pro_history_plan(
        root,
        expected_target=source.identity.target_trade_date,
        expected_run_id=source.identity.creator_run_id,
    )
    if (
        actual_plan != plan
        or read_stk_factor_pro_history_ranges(connection, root=root, plan=plan)
        != ranges
    ):
        raise ValueError("历史发布的完整计划/范围不是当前run已保存结果")
    units = source.source_complete.expected_units
    if (
        stk_factor_pro_history_input_digest(
            source.identity, source.contract, units, ranges
        )
        != source.source_complete.history_input_digest
    ):
        raise ValueError("历史发布实际范围的权威业务摘要不符")
    check_cancel()
    verified = verify_stk_factor_pro_current_source(
        root,
        source.source_complete,
        connection=connection,
        current_run_id=source.identity.creator_run_id,
        expected_units=units,
    )
    if verified != source:
        raise ValueError("历史发布源引用与当前run读回不符")
    files = read_stk_factor_pro_source_files(
        root,
        source.source_complete.files_manifest_ref,
        connection=connection,
        identity=source.identity,
        contract=source.contract,
    )
    paths = tuple(root / file.file_relative_path for file in files)
    for path in paths:
        _safe(path)
    dates = _history_publication_dates(
        connection,
        source=source,
        units=units,
        paths=paths,
        calendar=calendar,
        registered_dates=registered_dates,
    )
    if (root / "candidates" / "history").exists() or (
        root / "publication" / "history"
    ).exists():
        raise ValueError("当前run已有历史候选或发布记录，不接受续跑")
    input_checked = False
    completed = []

    def before_first_publish():
        nonlocal input_checked
        if not input_checked:
            check_cancel()
            recheck_stk_factor_pro_history_inputs(
                connection,
                plan=plan,
                ranges=ranges,
                expected_units=units,
                lake_root=lake_root,
                recheck_inputs=recheck_inputs,
            )
            input_checked = True

    with _history_cleanup(connection, _release_stk_factor_pro_history_batch):
        batch_size = STK_FACTOR_PRO_HISTORY_MERGE_BATCH_TRADE_DAYS
        for offset in range(0, len(dates), batch_size):
            batch_dates = dates[offset : offset + batch_size]
            check_cancel()
            with _history_cleanup(connection, _release_stk_factor_pro_history_batch):
                _load_stk_factor_pro_history_batch(
                    connection, paths=paths, dates=batch_dates
                )
                for day in batch_dates:
                    check_cancel()
                    with _history_cleanup(
                        connection, _release_stk_factor_pro_history_day
                    ):
                        connection.execute(
                            f"CREATE TEMP TABLE {HISTORY_DAY_SOURCE} AS SELECT {factor_columns()} "
                            f"FROM {HISTORY_BATCH_SOURCE} WHERE trade_date=?",
                            [day.strftime("%Y%m%d")],
                        )
                        raw = raw_stk_factor_pro_path(lake_root, day.isoformat())
                        silver = silver_stock_factor_pro_path(
                            lake_root, day.isoformat()
                        )
                        for path in (raw, silver):
                            _safe(path)
                        count = connection.execute(
                            f"SELECT count(*) FROM {HISTORY_DAY_SOURCE}"
                        ).fetchone()[0]
                        prior_raw = _hash_if_exists(raw)
                        active_codes = tuple(
                            unit.object_code
                            for unit in units
                            if unit.start_date <= day <= unit.end_date
                        )
                        if prior_raw is None and count == 0:
                            if silver.exists():
                                raise ValueError(
                                    "历史日期仅存在Silver但缺Raw，请管理员处理"
                                )
                            for layer in ("raw", "silver"):
                                _history_unrefreshed_keys(
                                    connection,
                                    root=root,
                                    identity=source.identity,
                                    day=day,
                                    layer=layer,
                                    codes=active_codes,
                                    prior_relation=None,
                                )
                                target = PublishedTarget(
                                    day,
                                    layer,
                                    True,
                                    None,
                                    0,
                                    None,
                                    0,
                                    0,
                                    hashlib.sha256(b"").hexdigest(),
                                    1,
                                )
                                completed.append((target, None))
                                yield target, None
                            continue
                        raw_candidate = (
                            root
                            / "candidates"
                            / "history"
                            / day.isoformat()
                            / "raw"
                            / "data.parquet"
                        )
                        raw_audit = build_stk_factor_pro_raw_candidate_from_relation(
                            connection,
                            source_relation=HISTORY_DAY_SOURCE,
                            target_trade_date=day,
                            prior_path=raw if prior_raw else None,
                            candidate_path=raw_candidate,
                            run_root=root,
                        )
                        ref, missing = _history_unrefreshed_keys(
                            connection,
                            root=root,
                            identity=source.identity,
                            day=day,
                            layer="raw",
                            codes=active_codes,
                            prior_relation=DAY_PRIOR if prior_raw else None,
                        )
                        scope_facts = _history_scope_facts(
                            connection, relation=RAW_EXPECTED, codes=active_codes
                        )
                        before_first_publish()
                        raw_target, raw_audit = _publish_file(
                            connection,
                            source=source,
                            run_root=root,
                            target=raw,
                            candidate_audit=raw_audit,
                            prior=prior_raw,
                            expected_relation=RAW_EXPECTED,
                            check_cancel=check_cancel,
                            raw_guard=lambda: None,
                            phase="history",
                            unrefreshed_keys_ref=ref,
                            unrefreshed_count=missing,
                            scope_facts=scope_facts,
                        )
                        completed.append((raw_target, raw_audit))
                        yield raw_target, raw_audit
                        check_cancel()

                        def raw_guard(raw=raw, raw_audit=raw_audit):
                            if _hash_if_exists(raw) != raw_audit.file_sha256:
                                raise ValueError("历史生成Silver期间对应Raw已改变")

                        raw_guard()
                        prior_silver = _hash_if_exists(silver)
                        if prior_silver is not None:
                            connection.execute(
                                f"CREATE TEMP TABLE {HISTORY_PRIOR_SILVER} AS SELECT {factor_columns()} "
                                "FROM read_parquet(?,hive_partitioning=false)",
                                [str(silver)],
                            )
                            require_factor_relation(
                                connection,
                                HISTORY_PRIOR_SILVER,
                                target_trade_date=day,
                                layer="silver",
                            )
                        ref, missing = _history_unrefreshed_keys(
                            connection,
                            root=root,
                            identity=source.identity,
                            day=day,
                            layer="silver",
                            codes=active_codes,
                            prior_relation=HISTORY_PRIOR_SILVER
                            if prior_silver
                            else None,
                        )
                        silver_candidate = (
                            root
                            / "candidates"
                            / "history"
                            / day.isoformat()
                            / "silver"
                            / "data.parquet"
                        )
                        silver_audit = build_stk_factor_pro_silver_candidate(
                            connection,
                            verified_raw_path=raw,
                            target_trade_date=day,
                            candidate_path=silver_candidate,
                            run_root=root,
                        )
                        scope_facts = _history_scope_facts(
                            connection, relation=SILVER_EXPECTED, codes=active_codes
                        )
                        raw_guard()
                        silver_target, silver_audit = _publish_file(
                            connection,
                            source=source,
                            run_root=root,
                            target=silver,
                            candidate_audit=silver_audit,
                            prior=prior_silver,
                            expected_relation=SILVER_EXPECTED,
                            check_cancel=check_cancel,
                            raw_guard=raw_guard,
                            phase="history",
                            unrefreshed_keys_ref=ref,
                            unrefreshed_count=missing,
                            scope_facts=scope_facts,
                        )
                        completed.append((silver_target, silver_audit))
                        yield silver_target, silver_audit
        _finish_stk_factor_pro_history_publication(
            connection,
            source=source,
            plan=plan,
            ranges=ranges,
            lake_root=lake_root,
            root=root,
            dates=dates,
            completed=tuple(completed),
            recheck_inputs=recheck_inputs,
            check_cancel=check_cancel,
        )


def read_stk_factor_pro_history_publication_complete(
    root: Path,
    *,
    expected_target: date,
    expected_run_id: str,
) -> PublicationCompleteRecord:
    _run_root(root, run_id=expected_run_id, target=expected_target)
    path = root / "publication/history/publication-complete.json"
    record = _json_read(path, PublicationCompleteRecord)
    if (
        record.phase != "history"
        or record.identity.creator_run_id != expected_run_id
        or record.identity.target_trade_date != expected_target
    ):
        raise ValueError("历史完整发布记录不是指定run/原T")
    return record


def _verify_history_published_targets(
    connection, *, source, root, lake_root, dates, completed
):
    expected = tuple((day, layer) for day in dates for layer in ("raw", "silver"))
    actual = tuple((target.trade_date, target.layer) for target, _ in completed)
    if actual != expected:
        raise ValueError("历史已交付结果没有按日期/两层唯一完整覆盖请求范围")
    targets, missing_refs = [], []
    for target, audit in completed:
        day = target.trade_date
        path = (
            raw_stk_factor_pro_path
            if target.layer == "raw"
            else silver_stock_factor_pro_path
        )(lake_root, day.isoformat())
        _safe(path)
        if target.skip_no_file:
            if (
                audit is not None
                or path.exists()
                or target.scope_rows != 0
                or target.unrefreshed_count
            ):
                raise ValueError("历史无文件结果与实际目标或检查结果不符")
            diagnostic = (
                root
                / "publication/history"
                / day.isoformat()
                / target.layer
                / "unrefreshed-keys.parquet"
            )
            _safe(diagnostic)
            if (
                not diagnostic.is_file()
                or connection.execute(
                    "SELECT count(*) FROM read_parquet(?,hive_partitioning=false)",
                    [str(diagnostic)],
                ).fetchone()[0]
                != 0
            ):
                raise ValueError("历史无文件日期缺少明确零行诊断")
        else:
            if (
                audit is None
                or not audit.passed
                or audit.trade_date != day
                or audit.layer != target.layer
                or audit.path != path
                or audit.file_sha256 != target.file_sha256
                or audit.row_count != target.file_rows
            ):
                raise ValueError("历史文件未对应本轮已通过的检查事实")
            checkpoint = _ref_path(root, source.identity, target.checkpoint_ref)
            record = read_stk_factor_pro_publication_record(checkpoint)
            if (
                record.identity != source.identity
                or record.contract != source.contract
                or record.phase != "history"
                or record.stage != "complete"
                or record.trade_date != day
                or record.layer != target.layer
                or record.target_path != str(path)
                or record.actual_sha256 != target.file_sha256
                or record.actual_rows != target.file_rows
                or record.unrefreshed_count != target.unrefreshed_count
                or record.scope_digest != source.source_complete.scope_digest
                or record.history_input_digest
                != source.source_complete.history_input_digest
                or record.source_manifest_digest
                != source.source_complete.files_manifest_digest
            ):
                raise ValueError("历史文件完成记录与本轮来源/实际结果不符")
            # The 261-column audit already proved content. Final identity checks
            # cost one byte hash per actual target, without another field join.
            if _hash_if_exists(path) != target.file_sha256:
                raise ValueError("历史正式文件在完成记录形成前已改变")
            _ref_path(root, source.identity, record.unrefreshed_keys_ref)
            if target.unrefreshed_count:
                missing_refs.append(record.unrefreshed_keys_ref)
        targets.append(target)
    return tuple(targets), tuple(missing_refs)


def _finish_stk_factor_pro_history_publication(
    connection,
    *,
    source,
    plan,
    ranges,
    lake_root,
    root,
    dates,
    completed,
    recheck_inputs,
    check_cancel,
):
    check_cancel()
    targets, missing_refs = _verify_history_published_targets(
        connection,
        source=source,
        root=root,
        lake_root=lake_root,
        dates=dates,
        completed=completed,
    )
    missing = sum(target.unrefreshed_count for target in targets)
    if missing:
        summary = f"历史修复未完成：{source.identity.target_trade_date}；Raw/Silver合计{missing}条记录未刷新。"
        raise dg.Failure(
            description=summary,
            allow_retries=False,
            metadata={
                "goldenshare/failure_phase": "history",
                "goldenshare/retryable": True,
                "goldenshare/source_error_code": None,
                "goldenshare/target_trade_date": source.identity.target_trade_date.isoformat(),
                "goldenshare/unrefreshed_count": missing,
                "goldenshare/unrefreshed_keys_refs": dg.MetadataValue.json(
                    [stk_factor_pro_record_to_dict(ref) for ref in missing_refs]
                ),
                "goldenshare/history_plan_ref": dg.MetadataValue.json(
                    stk_factor_pro_record_to_dict(
                        source.source_complete.history_plan_ref
                    )
                ),
                "goldenshare/history_plan_digest": plan.history_plan_digest,
                "goldenshare/history_ranges_digest": plan.history_ranges_digest,
                "goldenshare/summary": summary,
                "goldenshare/next_action": "查看缺原键清单，处理来源后重新执行原完整历史范围；手动repair由管理员再次执行。",
            },
        )
    current_source = _ref_path(root, source.identity, source.source_complete_ref)
    if (
        _json_read(current_source, type(source.source_complete))
        != source.source_complete
    ):
        raise ValueError("历史完整源业务元数据在发布过程中改变")
    _ref_path(root, source.identity, source.source_complete.history_plan_ref)
    current_plan = read_stk_factor_pro_history_plan(
        root,
        expected_target=source.identity.target_trade_date,
        expected_run_id=source.identity.creator_run_id,
    )
    if current_plan != plan:
        raise ValueError("历史完整计划在发布过程中改变")
    _ref_path(root, source.identity, plan.ranges_ref)
    _ref_path(root, source.identity, source.source_complete.files_manifest_ref)
    if (
        stk_factor_pro_scope_digest(
            "history",
            source.identity.target_trade_date,
            source.source_complete.expected_units,
        )
        != source.source_complete.scope_digest
        or stk_factor_pro_history_input_digest(
            source.identity,
            source.contract,
            source.source_complete.expected_units,
            ranges,
        )
        != source.source_complete.history_input_digest
    ):
        raise ValueError("历史实际请求范围或权威输入摘要不符")
    recheck_stk_factor_pro_history_inputs(
        connection,
        plan=plan,
        ranges=ranges,
        expected_units=source.source_complete.expected_units,
        lake_root=lake_root,
        recheck_inputs=recheck_inputs,
    )
    check_cancel()
    record = PublicationCompleteRecord(
        1,
        source.identity,
        "history",
        source.contract,
        plan.history_plan_digest,
        plan.history_ranges_digest,
        source.source_complete.scope_digest,
        source.source_complete.history_input_digest,
        source.source_complete_ref,
        None,
        source.source_complete.files_manifest_digest,
        targets,
        datetime.now(ZoneInfo(STK_FACTOR_PRO_TIMEZONE)),
    )
    _json_write(
        root, source.identity, "publication/history/publication-complete.json", record
    )
    if (
        read_stk_factor_pro_history_publication_complete(
            root,
            expected_target=source.identity.target_trade_date,
            expected_run_id=source.identity.creator_run_id,
        )
        != record
    ):
        raise ValueError("历史完整范围发布记录最终读回不符")
