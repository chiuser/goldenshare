"""Approved Prod month export with complete-day facts and bounded memory."""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from psycopg2 import sql

from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_records as records
from orchestrator.defs.checks.stk_factor_pro import (
    factor_content_sha,
    factor_file_sha,
    require_factor_relation,
)
from orchestrator.defs.io.stk_factor_pro_candidates import (
    build_stk_factor_pro_raw_batch,
    write_stk_factor_pro_raw_fragment,
)
from orchestrator.defs.run_contracts import stk_factor_pro as C
from orchestrator.tushare_download.contract_registry import content_digest


def _now():
    return datetime.now(ZoneInfo(C.STK_FACTOR_PRO_TIMEZONE))


def _natural_dates(start, end_exclusive):
    return tuple(start + timedelta(days=i) for i in range((end_exclusive - start).days))


def plan_stk_factor_pro_bootstrap_months(
    start_trade_date, end_trade_date, row_upper_bounds
):
    """Split the approved whole-source interval; bounds are internal approved input."""
    if (
        type(start_trade_date) is not date
        or type(end_trade_date) is not date
        or start_trade_date > end_trade_date
    ):
        raise ValueError("bootstrap实际源日期范围不合法")
    result = []
    current = start_trade_date
    while current <= end_trade_date:
        following = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
        end = min(following, end_trade_date + timedelta(days=1))
        key = current.strftime("%Y-%m")
        if key not in row_upper_bounds:
            raise ValueError("bootstrap月份缺批准行数上界")
        result.append(
            C.StkFactorProBootstrapMonthLimit(current, end, row_upper_bounds[key])
        )
        current = end
    if set(row_upper_bounds) != {item.month_start.strftime("%Y-%m") for item in result}:
        raise ValueError("bootstrap月份上界混入范围外月份")
    return tuple(result)


def validate_stk_factor_pro_bootstrap_approval(*, approval, now, source_identity):
    """Pure approval validation; a local-statistics replay may be outside its window."""
    if not isinstance(approval, C.StkFactorProBootstrapApproval) or not isinstance(
        source_identity, C.StkFactorProSourceIdentity
    ):
        raise TypeError("bootstrap缺完整批准或来源身份")
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError("bootstrap当前时间必须带时区")
    if (
        source_identity.contract_content_digest
        != content_digest(C.STK_FACTOR_PRO_CONTRACT)
        or approval.contract_content_digest != source_identity.contract_content_digest
    ):
        raise ValueError("bootstrap批准不对应当前完整字段合同")
    if (
        C.stk_factor_pro_bootstrap_source_identity_digest(source_identity)
        != approval.source_identity_digest
    ):
        raise ValueError("bootstrap批准来源身份摘要不符")
    planned = plan_stk_factor_pro_bootstrap_months(
        approval.start_trade_date,
        approval.end_trade_date,
        {
            item.month_start.strftime("%Y-%m"): item.row_upper_bound
            for item in approval.month_limits
        },
    )
    if planned != approval.month_limits:
        raise ValueError("bootstrap月份未按源全量自然月完整切分")
    return planned


def require_stk_factor_pro_bootstrap_source_window(*, approval, now):
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError("bootstrap当前时间必须带时区")
    if not approval.source_maintenance_start <= now < approval.source_maintenance_end:
        raise ValueError("bootstrap原Prod维护窗口已结束或尚未开始")


def _approved_inputs(connection, *, staging_root, approval):
    records.approval_sha(staging_root, approval)
    counts = dict(
        records.load_approved_counts(
            connection, staging_root=staging_root, approval=approval
        )
    )
    evidence_path = records.operation_path(
        staging_root, approval, approval.approved_source_evidence_ref
    )
    if factor_file_sha(evidence_path) != approval.approved_source_evidence_digest:
        raise ValueError("bootstrap来源证据文件摘要不符")
    evidence = records.read_json(evidence_path, C.StkFactorProBootstrapSourceEvidence)
    if evidence is None:
        raise ValueError("bootstrap缺批准来源证据")
    expected = (
        approval.operation_id,
        approval.source_identity_digest,
        approval.contract_content_digest,
        approval.start_trade_date,
        approval.end_trade_date,
        sum(counts.values()),
        approval.approved_daily_counts_ref,
        approval.approved_daily_counts_digest,
        approval.source_maintenance_start,
        approval.source_maintenance_end,
    )
    actual = (
        evidence.operation_id,
        evidence.source_identity_digest,
        evidence.contract_content_digest,
        evidence.min_trade_date,
        evidence.max_trade_date,
        evidence.total_rows,
        evidence.approved_daily_counts_ref,
        evidence.approved_daily_counts_digest,
        evidence.source_maintenance_start,
        evidence.source_maintenance_end,
    )
    if actual != expected:
        raise ValueError("bootstrap批准来源证据与范围/计数/窗口不符")
    validate_stk_factor_pro_bootstrap_approval(
        approval=approval, now=_now(), source_identity=evidence.source_identity
    )
    for month in approval.month_limits:
        if (
            sum(
                counts[day]
                for day in _natural_dates(month.month_start, month.month_end_exclusive)
            )
            > month.row_upper_bound
        ):
            raise ValueError("bootstrap批准月上界小于批准计数")
    sample_path = records.operation_path(
        staging_root, approval, evidence.source_sample_ref
    )
    if factor_file_sha(sample_path) != evidence.source_sample_file_sha256:
        raise ValueError("bootstrap来源样本文件摘要不符")
    sample = records.read_json(sample_path, C.StkFactorProBootstrapSourceSample)
    if sample is None or (
        sample.operation_id != approval.operation_id
        or sample.source_identity_digest != approval.source_identity_digest
        or sample.contract_content_digest != approval.contract_content_digest
        or sample.observed_source_schema != evidence.source_identity.columns
        or not sample.passed
        or not approval.start_trade_date
        <= sample.sample_date
        <= approval.end_trade_date
    ):
        raise ValueError("bootstrap批准固定样本身份或结果不符")
    if (
        factor_file_sha(evidence_path) != approval.approved_source_evidence_digest
        or factor_file_sha(sample_path) != evidence.source_sample_file_sha256
    ):
        raise ValueError("bootstrap批准来源证据在读取期间变化")
    return counts, evidence, sample


def _selected_dates(connection, *, staging_root, approval, month):
    if month not in approval.month_limits:
        raise ValueError("bootstrap月份不属于批准")
    pending = []
    for day in _natural_dates(month.month_start, month.month_end_exclusive):
        completed = records.read_stk_factor_pro_bootstrap_source_complete(
            connection,
            staging_root=staging_root,
            approval=approval,
            trade_date=day,
        )
        if completed is None:
            pending.append(day)
    return tuple(pending)


@contextmanager
def _readonly_transaction(prod_postgres):
    """Keep the original failure even if the existing resource exit also fails."""
    manager = prod_postgres.connect_readonly_transaction()
    remote = manager.__enter__()
    try:
        yield remote
    except BaseException as primary:
        try:
            manager.__exit__(type(primary), primary, primary.__traceback__)
        except BaseException as cleanup:  # noqa: BLE001 -- Retain cancellation or the body error when resource exit also fails.
            primary.add_note(f"bootstrap事务退出同时失败：{type(cleanup).__name__}")
        raise
    else:
        manager.__exit__(None, None, None)


def _description(cursor):
    return tuple(
        item.name if hasattr(item, "name") else item[0]
        for item in (cursor.description or ())
    )


def _projection():
    return sql.SQL(",").join(
        sql.Identifier(name) for name in C.STK_FACTOR_PRO_SOURCE_COLUMNS
    )


def _preflight(
    control, *, prod_postgres, approval, month, selected_dates, counts, evidence, sample
):
    require_stk_factor_pro_bootstrap_source_window(approval=approval, now=_now())
    control.execute(
        "SELECT set_config('statement_timeout', %s, true)",
        (str(approval.source_statement_timeout_ms),),
    )
    control.execute(
        "SELECT column_name,data_type,is_nullable FROM information_schema.columns "
        "WHERE table_schema=%s AND table_name=%s AND column_name=ANY(%s) ORDER BY ordinal_position",
        ("raw_tushare", "stk_factor_pro", list(C.STK_FACTOR_PRO_SOURCE_COLUMNS)),
    )
    columns = control.fetchmany(len(C.STK_FACTOR_PRO_SOURCE_COLUMNS) + 1)
    mapped = {}
    for name, kind, nullable in columns:
        if name in mapped or nullable not in ("YES", "NO"):
            raise ValueError("bootstrap实际源schema重复或nullable非法")
        mapped[name] = (name, kind, nullable == "YES")
    if set(mapped) != set(C.STK_FACTOR_PRO_SOURCE_COLUMNS):
        raise ValueError("bootstrap实际源缺完整261业务字段")
    identity = C.StkFactorProSourceIdentity(
        prod_postgres._required_env(prod_postgres.host_env_var),
        int(prod_postgres._required_env(prod_postgres.port_env_var)),
        prod_postgres._required_env(prod_postgres.database_env_var),
        "raw_tushare",
        "stk_factor_pro",
        tuple(mapped[name] for name in C.STK_FACTOR_PRO_SOURCE_COLUMNS),
        approval.contract_content_digest,
    )
    validate_stk_factor_pro_bootstrap_approval(
        approval=approval, now=_now(), source_identity=identity
    )
    if identity != evidence.source_identity:
        raise ValueError("bootstrap实际来源schema或身份改变")
    table = sql.Identifier("raw_tushare", "stk_factor_pro")
    control.execute(
        sql.SQL("SELECT MIN(trade_date),MAX(trade_date) FROM {}").format(table)
    )
    if tuple(control.fetchone()) != (
        approval.start_trade_date,
        approval.end_trade_date,
    ):
        raise ValueError("bootstrap源实际首尾或截止日期改变")
    control.execute(
        sql.SQL(
            "SELECT trade_date,COUNT(*) FROM {} WHERE trade_date>=%s AND trade_date<%s AND trade_date=ANY(%s::date[]) GROUP BY trade_date ORDER BY trade_date"
        ).format(table),
        (month.month_start, month.month_end_exclusive, list(selected_dates)),
    )
    current = control.fetchmany(32)
    if (
        any(
            type(day) is not date or type(number) is not int or number <= 0
            for day, number in current
        )
        or len(dict(current)) != len(current)
        or set(dict(current)) - set(selected_dates)
    ):
        raise ValueError("bootstrap当前日计数结构非法")
    if {day: dict(current).get(day, 0) for day in selected_dates} != {
        day: counts[day] for day in selected_dates
    }:
        raise ValueError("bootstrap当前源日计数与批准不符")
    control.execute(
        sql.SQL(
            "SELECT {} FROM {} WHERE trade_date=%s AND ts_code=ANY(%s) ORDER BY trade_date,ts_code LIMIT %s"
        ).format(_projection(), table),
        (sample.sample_date, list(sample.sample_codes), sample.row_limit),
    )
    rows = control.fetchmany(sample.row_limit + 1)
    if (
        len(rows) != sample.returned_rows
        or _description(control) != sample.request_columns
    ):
        raise ValueError("bootstrap固定样本字段或行数改变")
    build_stk_factor_pro_raw_batch(
        rows=rows,
        source_fields=sample.request_columns,
        source="prod_postgres",
        expected_dates=(sample.sample_date,),
    )
    if any(row[0] not in sample.sample_codes for row in rows):
        raise ValueError("bootstrap固定样本返回范围外股票")
    require_stk_factor_pro_bootstrap_source_window(approval=approval, now=_now())


def preflight_stk_factor_pro_bootstrap_source(
    *, prod_postgres, connection, staging_root, approval, month, selected_dates
):
    """Check the existing approved source before restoring business publication."""
    counts, evidence, sample = _approved_inputs(
        connection, staging_root=staging_root, approval=approval
    )
    if (
        month not in approval.month_limits
        or tuple(sorted(set(selected_dates))) != selected_dates
        or not selected_dates
        or any(
            day not in _natural_dates(month.month_start, month.month_end_exclusive)
            for day in selected_dates
        )
    ):
        raise ValueError("bootstrap来源预检日期不在批准月内")
    require_stk_factor_pro_bootstrap_source_window(approval=approval, now=_now())
    with _readonly_transaction(prod_postgres) as remote:
        control = remote.cursor()
        with records.resource_cleanup(control.close):
            _preflight(
                control,
                prod_postgres=prod_postgres,
                approval=approval,
                month=month,
                selected_dates=selected_dates,
                counts=counts,
                evidence=evidence,
                sample=sample,
            )


def _complete_day(
    connection,
    *,
    staging_root,
    approval,
    month,
    selected_dates,
    attempt_id,
    day,
    references,
    approved_rows,
    close_reason,
    next_trade_date,
    check_space,
    verification=None,
):
    paths = [
        str(records.operation_path(staging_root, approval, ref.fragment.relative_path))
        for ref in references
    ]
    relation = "stk_factor_bootstrap_source_day_facts"
    with records.resource_cleanup(
        lambda: connection.execute(f"DROP TABLE IF EXISTS {relation}")
    ):
        if paths:
            connection.execute(
                f"CREATE TEMP TABLE {relation} AS SELECT * FROM read_parquet(?,hive_partitioning=false) WHERE trade_date=?",
                [paths, day.strftime("%Y%m%d")],
            )
        else:
            projection = ",".join(
                f'CAST(NULL AS {kind}) AS "{name}"'
                for name, kind in C.STK_FACTOR_PRO_RAW_COLUMN_TYPES.items()
            )
            connection.execute(
                f"CREATE TEMP TABLE {relation} AS SELECT {projection} WHERE false"
            )
        actual_rows, _ = require_factor_relation(
            connection, relation, target_trade_date=day, layer="raw"
        )
        if actual_rows != approved_rows:
            raise ValueError("bootstrap完整日源行数与批准不符")
        record = C.StkFactorProBootstrapSourceComplete(
            1,
            approval.operation_id,
            records.approval_sha(staging_root, approval),
            approval.source_identity_digest,
            approval.contract_content_digest,
            approval.source_cutoff_trade_date,
            month.month_start,
            month.month_end_exclusive,
            attempt_id,
            C.stk_factor_pro_bootstrap_query_digest(
                approval,
                records.approval_sha(staging_root, approval),
                month,
                selected_dates,
            ),
            selected_dates,
            month.row_upper_bound,
            day,
            approved_rows,
            actual_rows,
            references,
            C.fragments_manifest_digest(references),
            C.stk_factor_pro_schema_digest("raw"),
            factor_content_sha(connection, relation),
            1,
            close_reason,
            next_trade_date,
            actual_rows == 0,
            "0" * 64,
            _now(),
        )
    record = replace(
        record,
        source_complete_digest=C.stk_factor_pro_bootstrap_source_complete_digest(
            record
        ),
    )
    return records.write_stk_factor_pro_bootstrap_source_complete(
        connection,
        staging_root=staging_root,
        approval=approval,
        record=record,
        check_space=check_space,
        verification=verification,
    )


def _validate_date_result(record, result):
    if (
        not isinstance(result, C.StkFactorProBootstrapDateResult)
        or result.trade_date != record.trade_date
        or result.source_complete_digest != record.source_complete_digest
    ):
        raise ValueError("bootstrap完整日处理回调返回身份不符")
    audits = (result.raw_audit, result.silver_audit)
    if record.source_empty:
        if any(item is not None for item in audits):
            raise ValueError("bootstrap源0回调不得制造文件检查")
    elif (
        any(item is None or not item.passed for item in audits)
        or result.coverage is None
    ):
        raise ValueError("bootstrap有源日回调缺两层检查或覆盖结果")
    if result.coverage is not None and result.coverage.trade_date != record.trade_date:
        raise ValueError("bootstrap回调覆盖结果日期不符")
    return tuple(item for item in audits if item is not None)


def export_stk_factor_pro_bootstrap_month(
    *,
    prod_postgres,
    connection,
    staging_root,
    approval,
    month,
    selected_dates,
    on_complete_date,
    check_space,
    verification=None,
    progress=None,
):
    """Fetch whole pending days, save batches, and synchronously publish closed days."""
    counts, evidence, sample = _approved_inputs(
        connection, staging_root=staging_root, approval=approval
    )
    if selected_dates != _selected_dates(
        connection, staging_root=staging_root, approval=approval, month=month
    ):
        raise ValueError("bootstrap待读取日期必须是批准月扣除有效完整源日期")
    attempt_id = uuid4().hex
    if progress is not None:
        progress.start_attempt(attempt_id)
    if not selected_dates:
        return C.StkFactorProBootstrapMonthResult(month, attempt_id, 0, (), (), (), ())
    require_stk_factor_pro_bootstrap_source_window(approval=approval, now=_now())
    fragments, audits, completed = [], [], []
    references = {day: [] for day in selected_dates}
    actual_counts = Counter()
    seen, last_key, open_day = 0, None, None

    def complete(day, reason, following):
        require_stk_factor_pro_bootstrap_source_window(approval=approval, now=_now())
        record = _complete_day(
            connection,
            staging_root=staging_root,
            approval=approval,
            month=month,
            selected_dates=selected_dates,
            attempt_id=attempt_id,
            day=day,
            references=tuple(references[day]),
            approved_rows=counts[day],
            close_reason=reason,
            next_trade_date=following,
            check_space=check_space,
            verification=verification,
        )
        completed.append(day)
        audits.extend(_validate_date_result(record, on_complete_date(record)))

    check_space(
        "月源明细读取前",
        path=records.operation_root(staging_root, approval),
        month_start=month.month_start,
    )
    with _readonly_transaction(prod_postgres) as remote:
        control = remote.cursor()
        with records.resource_cleanup(control.close):
            _preflight(
                control,
                prod_postgres=prod_postgres,
                approval=approval,
                month=month,
                selected_dates=selected_dates,
                counts=counts,
                evidence=evidence,
                sample=sample,
            )
            cursor = remote.cursor(
                name=f"stk_factor_bootstrap_{attempt_id}",
                scrollable=False,
                withhold=False,
            )
            with records.resource_cleanup(cursor.close):
                cursor.itersize = C.STK_FACTOR_PRO_BOOTSTRAP_FETCH_ROWS
                cursor.execute(
                    sql.SQL(
                        "SELECT {} FROM {} WHERE trade_date >= %s AND trade_date < %s AND trade_date = ANY(%s::date[]) ORDER BY trade_date, ts_code LIMIT %s"
                    ).format(
                        _projection(), sql.Identifier("raw_tushare", "stk_factor_pro")
                    ),
                    (
                        month.month_start,
                        month.month_end_exclusive,
                        list(selected_dates),
                        month.row_upper_bound + 1,
                    ),
                )
                while True:
                    require_stk_factor_pro_bootstrap_source_window(
                        approval=approval, now=_now()
                    )
                    check_space(
                        "领取下一批源前",
                        path=records.operation_root(staging_root, approval),
                        month_start=month.month_start,
                    )
                    if progress is not None:
                        progress.set_stage("读取源批次")
                    rows = cursor.fetchmany(
                        min(
                            C.STK_FACTOR_PRO_BOOTSTRAP_FETCH_ROWS,
                            month.row_upper_bound + 1 - seen,
                        )
                    )
                    require_stk_factor_pro_bootstrap_source_window(
                        approval=approval, now=_now()
                    )
                    if _description(cursor) != C.STK_FACTOR_PRO_SOURCE_COLUMNS:
                        raise ValueError("bootstrap服务端游标未返回完整有序261字段")
                    if seen + len(rows) > month.row_upper_bound:
                        raise ValueError("bootstrap读取触及批准上限R+1，当前批不保存")
                    if not rows:
                        if seen != sum(counts[day] for day in selected_dates) or any(
                            actual_counts[day] != counts[day] for day in selected_dates
                        ):
                            raise ValueError("bootstrap真实EOF日计数或合计与批准不符")
                        for day in sorted(
                            {day for day in selected_dates if counts[day] == 0}
                            | ({open_day} if open_day is not None else set())
                        ):
                            complete(day, "eof", None)
                        break
                    frame = build_stk_factor_pro_raw_batch(
                        rows=rows,
                        source_fields=_description(cursor),
                        source="prod_postgres",
                        expected_dates=selected_dates,
                    )
                    batch_counts = Counter()
                    for row in rows:
                        key = (row[1], row[0])
                        if last_key is not None and key <= last_key:
                            raise ValueError("bootstrap源主键重复或跨批逆序")
                        last_key = key
                        batch_counts[row[1]] += 1
                    number = len(fragments) + 1
                    path = records.operation_path(
                        staging_root,
                        approval,
                        f"source/month={month.month_start:%Y-%m}/attempt_id={attempt_id}/fragment-{number:06d}.parquet",
                    )
                    check_space(
                        "源片段保存前",
                        path=path,
                        rows=len(rows),
                        month_start=month.month_start,
                    )
                    fragment = write_stk_factor_pro_raw_fragment(
                        connection=connection,
                        frame=frame,
                        candidate_path=path,
                        expected_row_count=len(rows),
                        on_verified_fragment=(
                            None
                            if verification is None
                            else lambda **facts: verification.remember_saved(
                                connection=connection, **facts
                            )
                        ),
                    )
                    if progress is not None:
                        progress.batch_saved(
                            batch_no=number, rows=len(rows), trade_date=last_key[0]
                        )
                    check_space(
                        "源片段已保存",
                        path=path,
                        rows=len(rows),
                        month_start=month.month_start,
                        event="source_saved",
                    )
                    seen += len(rows)
                    del rows, frame
                    fragments.append(fragment)
                    reference = C.StkFactorProBootstrapFragmentRef(
                        number, attempt_id, fragment
                    )
                    for day, number_rows in batch_counts.items():
                        references[day].append(reference)
                        actual_counts[day] += number_rows
                    for day in sorted(batch_counts):
                        if open_day is not None and day != open_day:
                            complete(open_day, "next_date", day)
                        open_day = day
                if progress is not None:
                    progress.set_stage("关闭源游标和只读事务")
    return C.StkFactorProBootstrapMonthResult(
        month,
        attempt_id,
        seen,
        tuple(fragments),
        tuple(sorted(completed)),
        tuple(day for day in selected_dates if day not in completed),
        tuple(audits),
    )
