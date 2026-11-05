"""Current-run per-file publication; no old candidate/checkpoint continuation."""

from __future__ import annotations

import hashlib
import os
import shutil
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import dagster as dg

from orchestrator.defs.checks.stk_factor_pro import (
    compare_factor_relations,
    factor_columns,
    factor_content_sha,
    factor_file_identity,
    factor_file_sha,
    factor_known_file_sha,
    release_stk_factor_pro_audit_relations,
)
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, duckdb_string
from orchestrator.defs.io.stk_factor_pro_candidates import (
    DAY_PRIOR,
    DAY_PRIOR_SILVER,
    HISTORY_DAY_SOURCE,
    RAW_EXPECTED,
    RAW_MATCHED_KEYS,
    SILVER_EXPECTED,
    build_stk_factor_pro_raw_candidate,
    build_stk_factor_pro_raw_candidate_from_relation,
    build_stk_factor_pro_silver_candidate,
    load_stk_factor_pro_prior_relation,
    require_stk_factor_pro_candidate_path,
)
from orchestrator.defs.io.stk_factor_pro_candidates import (
    require_stk_factor_pro_safe_path as _safe,
)
from orchestrator.defs.io.stk_factor_pro_download import (
    release_stk_factor_pro_history_source,
    require_stk_factor_pro_current_day_source,
)
from orchestrator.defs.io.stk_factor_pro_history import (
    _json_read,
    _json_write,
    _run_root,
    recheck_stk_factor_pro_history_inputs,
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
    StkFactorProFileAudit,
    StkFactorProPublicationRecord,
    VerifiedSource,
    stk_factor_pro_record_to_dict,
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


def read_stk_factor_pro_publication_record(
    path: Path, *, known_records: dict
) -> StkFactorProPublicationRecord:
    _safe(path)
    record = _json_read(
        path, StkFactorProPublicationRecord, known_records=known_records
    )
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


def _write_record(
    path: Path,
    record: StkFactorProPublicationRecord,
    *,
    known_records: dict,
    check_space,
) -> RecordRef:
    _safe(path)
    if path.exists():
        raise ValueError("技术因子不沿已有发布记录续跑，请创建重新下载的新任务")
    root = path.parents[4]
    return _json_write(
        root,
        record.identity,
        path.relative_to(root).as_posix(),
        record,
        known_records=known_records,
        check_space=check_space,
    )


def _hash_if_exists(path: Path, *, known_records: dict) -> str | None:
    _safe(path)
    return factor_known_file_sha(path, known_records=known_records)


def _publish_file(
    connection,
    *,
    source,
    run_root,
    target,
    candidate_audit,
    prior,
    prior_relation,
    expected_relation,
    check_cancel,
    raw_guard,
    known_records,
    check_space,
    phase="day",
    unrefreshed_keys_ref=None,
    unrefreshed_count=None,
    scope_facts=None,
    on_publish_attempt=None,
):
    candidate = candidate_audit.path
    for path in (candidate, target):
        _safe(path)
    if not candidate.is_relative_to(run_root) or not candidate_audit.passed:
        raise ValueError("技术因子候选未通过检查或不属于当前run")
    if known_records.get(candidate, (None, None, None))[0] is not candidate_audit:
        raise ValueError("技术因子候选未交接首次审计结果")
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
    if _hash_if_exists(target, known_records=known_records) != prior:
        raise ValueError("技术因子正式目标在构造候选时已改变")
    unchanged, prior_audit = False, None
    if prior is not None:
        relation, rows, schema = known_records[target][0]
        if prior_relation != relation:
            raise ValueError("技术因子旧文件关系未交接首次读取结果")
        comparison = compare_factor_relations(
            connection, expected=expected_relation, actual=prior_relation
        )
        unchanged = not any(
            (
                comparison.missing_key_count,
                comparison.unexpected_key_count,
                comparison.changed_row_count,
            )
        )
        prior_audit = StkFactorProFileAudit(
            candidate_audit.trade_date,
            layer,
            target,
            prior,
            schema,
            rows,
            0,
            0,
            0,
            0,
            comparison,
            unchanged,
            None,
        )
        if unchanged:
            known_records[target] = (prior_audit, prior, known_records[target][2])
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
    if on_publish_attempt is not None:
        on_publish_attempt(candidate_audit.trade_date, layer)
    _write_record(
        directory / "intent.json",
        record,
        known_records=known_records,
        check_space=check_space,
    )
    check_cancel()
    raw_guard()
    if (
        _hash_if_exists(target, known_records=known_records) != prior
        or factor_file_identity(candidate) != known_records[candidate][2]
    ):
        raise ValueError("技术因子目标或候选在发布前改变")
    target.parent.mkdir(parents=True, exist_ok=True)
    _safe(target)
    if target.parent.stat().st_dev != candidate.stat().st_dev:
        raise ValueError("技术因子提升跨文件系统")
    if shutil.disk_usage(target.parent).free < candidate.stat().st_size:
        raise ValueError("技术因子发布磁盘空间不足")
    if not unchanged:
        if check_space is not None:
            check_space(
                "历史正式文件提升前",
                path=target,
                trade_date=candidate_audit.trade_date,
                layer=layer,
            )
        os.replace(candidate, target)
        actual = replace(candidate_audit, path=target)
        known_records[target] = (
            actual,
            actual.file_sha256,
            factor_file_identity(target),
        )
        _fsync_directory(target.parent)
    else:
        actual = prior_audit
    # The moved candidate or equivalent prior file already supplied this audit.
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
    reference = _write_record(
        complete_path, complete, known_records=known_records, check_space=check_space
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
    connection,
    *,
    source,
    lake_root: Path,
    staging_root: Path,
    check_cancel,
    known_records: dict,
    on_publish_attempt=None,
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
    source_rows = len(source.unit_result.records)
    if source_rows == 0 and not raw.exists():
        if silver.exists():
            raise ValueError("技术因子仅存在Silver，缺少对应Raw，请管理员处理")
        return
    check_cancel()
    prior_raw = _hash_if_exists(raw, known_records=known_records)
    raw_audit = build_stk_factor_pro_raw_candidate(
        connection,
        source=source,
        prior_path=raw if prior_raw else None,
        candidate_path=raw_candidate,
        run_root=root,
        known_records=known_records,
    )
    raw_target, raw_audit = _publish_file(
        connection,
        source=source,
        run_root=root,
        target=raw,
        candidate_audit=raw_audit,
        prior=prior_raw,
        prior_relation=DAY_PRIOR if prior_raw else None,
        expected_relation=RAW_EXPECTED,
        check_cancel=check_cancel,
        raw_guard=lambda: None,
        known_records=known_records,
        check_space=None,
        on_publish_attempt=on_publish_attempt,
    )
    yield raw_target, raw_audit
    check_cancel()

    def raw_guard():
        if _hash_if_exists(raw, known_records=known_records) != raw_audit.file_sha256:
            raise ValueError("技术因子生成Silver期间对应Raw已改变")

    raw_guard()
    prior_silver = _hash_if_exists(silver, known_records=known_records)
    if prior_silver is not None:
        load_stk_factor_pro_prior_relation(
            connection,
            path=silver,
            relation=DAY_PRIOR_SILVER,
            target_trade_date=source.identity.target_trade_date,
            layer="silver",
            known_records=known_records,
        )
    silver_audit = build_stk_factor_pro_silver_candidate(
        connection,
        verified_raw_relation=RAW_EXPECTED,
        raw_audit=raw_audit,
        target_trade_date=source.identity.target_trade_date,
        candidate_path=silver_candidate,
        run_root=root,
        known_records=known_records,
    )
    raw_guard()
    yield _publish_file(
        connection,
        source=source,
        run_root=root,
        target=silver,
        candidate_audit=silver_audit,
        prior=prior_silver,
        prior_relation=DAY_PRIOR_SILVER if prior_silver else None,
        expected_relation=SILVER_EXPECTED,
        check_cancel=check_cancel,
        raw_guard=raw_guard,
        known_records=known_records,
        check_space=None,
        on_publish_attempt=on_publish_attempt,
    )


HISTORY_BATCH_SOURCE = "stk_factor_pro_history_batch_source"
HISTORY_PRIOR_SILVER = "stk_factor_pro_history_prior_silver"
HISTORY_SCOPE_ROWS = "stk_factor_pro_history_scope_rows"
HISTORY_UNREFRESHED_KEYS = "stk_factor_pro_history_unrefreshed_keys"
HISTORY_UNREFRESHED_SAVED = "stk_factor_pro_history_unrefreshed_saved"


def _release_history_sql(connection, statements, primary=None):
    failures = []
    for statement in statements:
        try:
            connection.execute(statement)
        except BaseException as cleanup:  # noqa: BLE001 -- attempt all owned SQL releases before propagating the first failure.
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
            RAW_MATCHED_KEYS,
            RAW_EXPECTED,
            SILVER_EXPECTED,
            HISTORY_PRIOR_SILVER,
            HISTORY_UNREFRESHED_KEYS,
        )
    )


def _release_stk_factor_pro_history_day(connection, primary=None):
    cleanup = None
    try:
        release_stk_factor_pro_audit_relations(connection)
    except BaseException as error:  # noqa: BLE001 -- finish fixed-table cleanup while preserving the body or first cleanup error.
        cleanup = error
        if primary is not None:
            primary.add_note(f"历史审计关系清理同时失败：{type(error).__name__}")
    _release_history_sql(connection, _history_day_release_sql(), primary or cleanup)
    if primary is None and cleanup is not None:
        raise cleanup


def _release_stk_factor_pro_history_batch(connection, primary=None):
    _release_history_sql(
        connection,
        (f"DROP TABLE IF EXISTS {HISTORY_BATCH_SOURCE}",),
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


def _load_stk_factor_pro_history_batch(connection, *, source_relation, dates):
    # Exactly one source query materializes each batch. Per-date consumers only
    # touch this real table, never reopen all multi-year source files.
    connection.execute(
        f"CREATE TEMP TABLE {HISTORY_BATCH_SOURCE} AS SELECT {factor_columns()} "
        f"FROM {source_relation} WHERE trade_date=ANY(?)",
        [[day.strftime("%Y%m%d") for day in dates]],
    )


def _history_publication_dates(
    connection, *, source, calendar, registered_dates, publication_dates
):
    identity = source.identity
    dates = publication_dates
    if (
        type(dates) is not tuple
        or any(type(day) is not date for day in dates)
        or tuple(sorted(set(dates))) != dates
        or any(
            day >= identity.target_trade_date
            or day not in calendar
            or day not in registered_dates
            for day in dates
        )
    ):
        raise ValueError("历史发布日期尚未登记分区，禁止提升")
    # One aggregate over all current sources checks every source date before any
    # formal file can be changed. T rows remain in source evidence only.
    observed = connection.execute(
        f"SELECT trade_date,count(*) FROM {source.source_relation} GROUP BY trade_date ORDER BY trade_date"
    ).fetchall()
    approved = {day.strftime("%Y%m%d") for day in dates}
    target = identity.target_trade_date.strftime("%Y%m%d")
    for day, count in observed:
        if day != target and day not in approved:
            raise ValueError(f"历史源日期不属于已批准开市/登记范围：{day}，行数{count}")
    return dates, dict(observed)


def _history_unrefreshed_keys(
    connection,
    *,
    root,
    identity,
    day,
    layer,
    codes,
    prior_relation,
    known_records,
    check_space,
):
    if prior_relation is None:
        return None, 0
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
    if prior_relation is not None:
        key_date = (
            "CAST(strptime(b.trade_date,'%Y%m%d') AS DATE)"
            if layer == "raw"
            else "b.trade_date"
        )
        source_relation = RAW_MATCHED_KEYS if layer == "raw" else HISTORY_DAY_SOURCE
        source_date = "CAST(strptime(u.trade_date,'%Y%m%d') AS DATE)"
        connection.execute(
            f"CREATE TEMP TABLE {HISTORY_UNREFRESHED_KEYS} AS SELECT ?::VARCHAR AS layer, "
            f"b.ts_code,{key_date} AS trade_date FROM {prior_relation} b "
            f"WHERE b.ts_code=ANY(?) AND NOT EXISTS (SELECT 1 FROM {source_relation} u "
            f"WHERE u.ts_code=b.ts_code AND {source_date}={key_date})",
            [layer, list(codes)],
        )

    def release_keys(connection, primary):
        _release_history_sql(
            connection,
            (
                f"DROP TABLE IF EXISTS {HISTORY_UNREFRESHED_SAVED}",
                f"DROP TABLE IF EXISTS {HISTORY_UNREFRESHED_KEYS}",
            ),
            primary,
        )

    with _history_cleanup(connection, release_keys):
        count = connection.execute(
            f"SELECT count(*) FROM {HISTORY_UNREFRESHED_KEYS}"
        ).fetchone()[0]
        if count == 0:
            return None, 0
        check_space(
            "历史缺原键明细保存前", path=path, trade_date=day, layer=layer, rows=count
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        for value in (path, temporary):
            _safe(value)
        connection.execute(
            copy_query_to_parquet(
                f"SELECT layer,ts_code,trade_date FROM {HISTORY_UNREFRESHED_KEYS} ORDER BY ts_code,trade_date",
                temporary,
            )
        )
        connection.execute(
            f"CREATE TEMP TABLE {HISTORY_UNREFRESHED_SAVED} AS SELECT * FROM read_parquet(?,hive_partitioning=false)",
            [str(temporary)],
        )
        schema = tuple(
            (row[0], row[1])
            for row in connection.execute(
                f"DESCRIBE {HISTORY_UNREFRESHED_SAVED}"
            ).fetchall()
        )
        difference = connection.execute(
            f"SELECT count(*) FROM ((SELECT layer,ts_code,trade_date FROM {HISTORY_UNREFRESHED_KEYS} "
            f"EXCEPT ALL SELECT layer,ts_code,trade_date FROM {HISTORY_UNREFRESHED_SAVED}) "
            f"UNION ALL (SELECT layer,ts_code,trade_date FROM {HISTORY_UNREFRESHED_SAVED} "
            f"EXCEPT ALL SELECT layer,ts_code,trade_date FROM {HISTORY_UNREFRESHED_KEYS}))"
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
        known_records[path] = (None, before, factor_file_identity(path))
        check_space(
            "历史缺原键明细已保存",
            path=path,
            trade_date=day,
            layer=layer,
            rows=count,
            event="record_saved",
        )
        return RecordRef(
            identity.creator_run_id, path.relative_to(root).as_posix(), before
        ), count


def _history_scope_facts(connection, *, relation, codes, row_count):
    selected = ",".join(duckdb_string(code) for code in codes)
    connection.execute(
        f"CREATE TEMP VIEW {HISTORY_SCOPE_ROWS} AS SELECT {factor_columns()} FROM {relation} WHERE ts_code IN ({selected})"
    )

    def release_scope(connection, primary):
        _release_history_sql(
            connection, (f"DROP VIEW IF EXISTS {HISTORY_SCOPE_ROWS}",), primary
        )

    with _history_cleanup(connection, release_scope):
        return row_count, factor_content_sha(connection, HISTORY_SCOPE_ROWS)


def publish_stk_factor_pro_history(
    connection,
    *,
    source: VerifiedSource,
    known_records: dict,
    plan,
    ranges,
    lake_root: Path,
    staging_root: Path,
    calendar: tuple[date, ...],
    registered_dates: tuple[date, ...],
    publication_dates: tuple[date, ...],
    check_space,
    recheck_inputs,
    check_cancel,
    on_publish_attempt=None,
):
    """Keep all source ownership through final consumers and every exit path."""
    with _history_cleanup(connection, release_stk_factor_pro_history_source):
        yield from _publish_stk_factor_pro_history(
            connection,
            source=source,
            known_records=known_records,
            plan=plan,
            ranges=ranges,
            lake_root=lake_root,
            staging_root=staging_root,
            calendar=calendar,
            registered_dates=registered_dates,
            publication_dates=publication_dates,
            check_space=check_space,
            recheck_inputs=recheck_inputs,
            check_cancel=check_cancel,
            on_publish_attempt=on_publish_attempt,
        )


def _publish_stk_factor_pro_history(
    connection,
    *,
    source: VerifiedSource,
    known_records: dict,
    plan,
    ranges,
    lake_root: Path,
    staging_root: Path,
    calendar: tuple[date, ...],
    registered_dates: tuple[date, ...],
    publication_dates: tuple[date, ...],
    check_space,
    recheck_inputs,
    check_cancel,
    on_publish_attempt=None,
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
    plan_fact = known_records.get(root / "history-plan.json")
    range_fact = known_records.get(root / "history-ranges.parquet")
    if (
        plan_fact is None
        or plan_fact[0] != plan
        or range_fact is None
        or range_fact[0] != ranges
    ):
        raise ValueError("历史发布的完整计划/范围不是当前run已保存结果")
    units = source.source_complete.expected_units
    check_cancel()
    dates, source_counts = _history_publication_dates(
        connection,
        source=source,
        calendar=calendar,
        registered_dates=registered_dates,
        publication_dates=publication_dates,
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
                known_records=known_records,
            )
            input_checked = True

    batch_size = STK_FACTOR_PRO_HISTORY_MERGE_BATCH_TRADE_DAYS
    for offset in range(0, len(dates), batch_size):
        batch_dates = dates[offset : offset + batch_size]
        check_cancel()
        check_space("历史20日批计算前", path=root)
        with _history_cleanup(connection, _release_stk_factor_pro_history_batch):
            _load_stk_factor_pro_history_batch(
                connection,
                source_relation=source.source_relation,
                dates=batch_dates,
            )
            for day in batch_dates:
                check_cancel()
                with _history_cleanup(connection, _release_stk_factor_pro_history_day):
                    connection.execute(
                        f"CREATE TEMP TABLE {HISTORY_DAY_SOURCE} AS SELECT {factor_columns()} "
                        f"FROM {HISTORY_BATCH_SOURCE} WHERE trade_date=?",
                        [day.strftime("%Y%m%d")],
                    )
                    raw = raw_stk_factor_pro_path(lake_root, day.isoformat())
                    silver = silver_stock_factor_pro_path(lake_root, day.isoformat())
                    for path in (raw, silver):
                        _safe(path)
                    count = source_counts.get(day.strftime("%Y%m%d"), 0)
                    prior_raw = _hash_if_exists(raw, known_records=known_records)
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
                                known_records=known_records,
                                check_space=check_space,
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
                        check_space(
                            "历史日期已完成",
                            path=root,
                            trade_date=day,
                            event="date_completed",
                        )
                        continue
                    raw_candidate = (
                        root
                        / "candidates"
                        / "history"
                        / day.isoformat()
                        / "raw"
                        / "data.parquet"
                    )
                    check_space(
                        "历史Raw候选写前",
                        path=raw_candidate,
                        trade_date=day,
                        layer="raw",
                    )
                    raw_audit = build_stk_factor_pro_raw_candidate_from_relation(
                        connection,
                        source_relation=HISTORY_DAY_SOURCE,
                        source_row_count=count,
                        target_trade_date=day,
                        prior_path=raw if prior_raw else None,
                        candidate_path=raw_candidate,
                        run_root=root,
                        known_records=known_records,
                    )
                    check_space(
                        "历史Raw候选已校验",
                        path=raw_candidate,
                        trade_date=day,
                        layer="raw",
                        rows=raw_audit.row_count,
                        event="candidate_verified",
                    )
                    ref, missing = _history_unrefreshed_keys(
                        connection,
                        root=root,
                        identity=source.identity,
                        day=day,
                        layer="raw",
                        codes=active_codes,
                        prior_relation=DAY_PRIOR if prior_raw else None,
                        known_records=known_records,
                        check_space=check_space,
                    )
                    scope_count = count + missing
                    scope_facts = _history_scope_facts(
                        connection,
                        relation=RAW_EXPECTED,
                        codes=active_codes,
                        row_count=scope_count,
                    )
                    before_first_publish()
                    raw_target, raw_audit = _publish_file(
                        connection,
                        source=source,
                        run_root=root,
                        target=raw,
                        candidate_audit=raw_audit,
                        prior=prior_raw,
                        prior_relation=DAY_PRIOR if prior_raw else None,
                        expected_relation=RAW_EXPECTED,
                        check_cancel=check_cancel,
                        raw_guard=lambda: None,
                        phase="history",
                        on_publish_attempt=on_publish_attempt,
                        unrefreshed_keys_ref=ref,
                        unrefreshed_count=missing,
                        scope_facts=scope_facts,
                        known_records=known_records,
                        check_space=check_space,
                    )
                    completed.append((raw_target, raw_audit))
                    yield raw_target, raw_audit
                    check_cancel()

                    def raw_guard(raw=raw, raw_audit=raw_audit):
                        if (
                            _hash_if_exists(raw, known_records=known_records)
                            != raw_audit.file_sha256
                        ):
                            raise ValueError("历史生成Silver期间对应Raw已改变")

                    raw_guard()
                    prior_silver = _hash_if_exists(silver, known_records=known_records)
                    if prior_silver is not None:
                        load_stk_factor_pro_prior_relation(
                            connection,
                            path=silver,
                            relation=HISTORY_PRIOR_SILVER,
                            target_trade_date=day,
                            layer="silver",
                            known_records=known_records,
                        )
                    ref, missing = _history_unrefreshed_keys(
                        connection,
                        root=root,
                        identity=source.identity,
                        day=day,
                        layer="silver",
                        codes=active_codes,
                        prior_relation=HISTORY_PRIOR_SILVER if prior_silver else None,
                        known_records=known_records,
                        check_space=check_space,
                    )
                    silver_candidate = (
                        root
                        / "candidates"
                        / "history"
                        / day.isoformat()
                        / "silver"
                        / "data.parquet"
                    )
                    check_space(
                        "历史Silver候选写前",
                        path=silver_candidate,
                        trade_date=day,
                        layer="silver",
                    )
                    silver_audit = build_stk_factor_pro_silver_candidate(
                        connection,
                        verified_raw_relation=RAW_EXPECTED,
                        raw_audit=raw_audit,
                        target_trade_date=day,
                        candidate_path=silver_candidate,
                        run_root=root,
                        known_records=known_records,
                    )
                    check_space(
                        "历史Silver候选已校验",
                        path=silver_candidate,
                        trade_date=day,
                        layer="silver",
                        rows=silver_audit.row_count,
                        event="candidate_verified",
                    )
                    scope_facts = _history_scope_facts(
                        connection,
                        relation=SILVER_EXPECTED,
                        codes=active_codes,
                        row_count=scope_count,
                    )
                    raw_guard()
                    silver_target, silver_audit = _publish_file(
                        connection,
                        source=source,
                        run_root=root,
                        target=silver,
                        candidate_audit=silver_audit,
                        prior=prior_silver,
                        prior_relation=HISTORY_PRIOR_SILVER if prior_silver else None,
                        expected_relation=SILVER_EXPECTED,
                        check_cancel=check_cancel,
                        raw_guard=raw_guard,
                        phase="history",
                        on_publish_attempt=on_publish_attempt,
                        unrefreshed_keys_ref=ref,
                        unrefreshed_count=missing,
                        scope_facts=scope_facts,
                        known_records=known_records,
                        check_space=check_space,
                    )
                    completed.append((silver_target, silver_audit))
                    yield silver_target, silver_audit
                    check_space(
                        "历史日期已完成",
                        path=root,
                        trade_date=day,
                        event="date_completed",
                    )
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
        known_records=known_records,
        check_space=check_space,
    )


def read_stk_factor_pro_history_publication_complete(
    root: Path,
    *,
    expected_target: date,
    expected_run_id: str,
    known_records: dict,
) -> PublicationCompleteRecord:
    _run_root(root, run_id=expected_run_id, target=expected_target)
    path = root / "publication/history/publication-complete.json"
    record = _json_read(path, PublicationCompleteRecord, known_records=known_records)
    if (
        record.phase != "history"
        or record.identity.creator_run_id != expected_run_id
        or record.identity.target_trade_date != expected_target
    ):
        raise ValueError("历史完整发布记录不是指定run/原T")
    return record


def _verify_history_published_targets(
    connection, *, source, root, lake_root, dates, completed, known_records
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
            checkpoint = root / target.checkpoint_ref.relative_path
            checkpoint_fact = known_records.get(checkpoint)
            if (
                checkpoint_fact is None
                or checkpoint_fact[1] != target.checkpoint_ref.file_sha256
            ):
                raise ValueError("历史完成记录未交接首次保存结果")
            record = checkpoint_fact[0]
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
            # The unique file audit is final; only the recorded identity is checked.
            if _hash_if_exists(path, known_records=known_records) != target.file_sha256:
                raise ValueError("历史正式文件在完成记录形成前已改变")
            if record.unrefreshed_keys_ref is not None:
                diagnostic = known_records.get(
                    root / record.unrefreshed_keys_ref.relative_path
                )
                if (
                    diagnostic is None
                    or diagnostic[1] != record.unrefreshed_keys_ref.file_sha256
                ):
                    raise ValueError("历史缺原键明细未交接首次保存结果")
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
    known_records,
    check_space,
):
    check_cancel()
    targets, missing_refs = _verify_history_published_targets(
        connection,
        source=source,
        root=root,
        lake_root=lake_root,
        dates=dates,
        completed=completed,
        known_records=known_records,
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
    recheck_stk_factor_pro_history_inputs(
        connection,
        plan=plan,
        ranges=ranges,
        expected_units=source.source_complete.expected_units,
        lake_root=lake_root,
        recheck_inputs=recheck_inputs,
        known_records=known_records,
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
        root,
        source.identity,
        "publication/history/publication-complete.json",
        record,
        known_records=known_records,
        check_space=check_space,
    )
