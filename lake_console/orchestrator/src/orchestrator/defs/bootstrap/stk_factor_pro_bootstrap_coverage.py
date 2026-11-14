"""Once-acquired bootstrap inputs, one coverage result and pure summary records."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from orchestrator.defs.asset_guards.stk_factor_pro_readiness import (
    _GLOBALS,
    _load_basis,
    _schema,
    _stat,
    _stk_factor_pro_date_code_issues,
    calculate_stk_factor_pro_coverage,
    release_stk_factor_pro_coverage_keys,
    stk_factor_pro_invalid_code_sql,
)
from orchestrator.defs.bootstrap.stk_factor_pro_bootstrap_records import (
    approval_sha,
    atomic_promote,
    operation_path,
    read_json,
    resource_cleanup,
    write_json,
)
from orchestrator.defs.checks.stk_factor_pro import (
    factor_file_identity,
    factor_known_file_sha,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.io.stk_factor_pro_candidates import (
    require_stk_factor_pro_safe_path,
)
from orchestrator.defs.paths import (
    raw_stk_factor_pro_path,
    silver_stock_factor_pro_path,
    silver_stock_suspend_daily_path,
    stk_factor_pro_run_staging_root,
)
from orchestrator.defs.run_contracts import stk_factor_pro as C
from orchestrator.defs.run_contracts.asset_column_schemas import (
    SILVER_STOCK_SUSPEND_DAILY_SCHEMA,
)

_PREFIX = "stk_factor_bootstrap_coverage_"
_SUSPEND = _PREFIX + "suspend"
_CODE_SCHEMA = (("ts_code", "VARCHAR"), ("trade_date", "DATE"))


def _now():
    return datetime.now(ZoneInfo("Asia/Shanghai"))


def _days(first, last_exclusive):
    return tuple(
        first + timedelta(days=i) for i in range((last_exclusive - first).days)
    )


def _drop(connection, names):
    with resource_cleanup(
        *(
            lambda name=n: connection.execute(f"DROP TABLE IF EXISTS {name}")
            for n in names
        )
    ):
        pass


def _basis_path(lake_root, basis):
    return (
        silver_stock_suspend_daily_path(lake_root, basis.trade_date.isoformat())
        if basis.kind == "suspend"
        else _GLOBALS[basis.kind][0](lake_root)
    )


def prepare_stk_factor_pro_bootstrap_coverage_month(
    connection, *, lake_root, staging_root, approval, month, basis_inputs, known_records
):
    if month not in approval.month_limits:
        raise ValueError("覆盖月份不属于本次批准")
    if month.month_start in basis_inputs["months"]:
        if basis_inputs["active_month"] != month:
            raise ValueError("本次已释放月份不可重新准备")
        return basis_inputs["months"][month.month_start]
    if basis_inputs["active_month"] is not None:
        raise ValueError("覆盖准备前必须结束上一月份")
    digest = approval_sha(staging_root, approval, known_records=known_records)
    dates = _days(month.month_start, month.month_end_exclusive)
    files, issues, by_kind = [], {d: {} for d in dates}, {}
    for kind in ("calendar", "lifecycle", "identity"):
        fact = _load_basis(
            connection,
            path=_GLOBALS[kind][0](lake_root),
            kind=kind,
            trade_date=None,
            basis_inputs=basis_inputs,
            known_records=known_records,
        )
        by_kind[kind] = fact
        files.append(fact["basis"])
        if not fact["basis"].valid:
            for day in dates:
                issues[day][kind] = fact["reason"]
    for day in dates:
        issues[day].update(
            _stk_factor_pro_date_code_issues(
                connection, trade_date=day, by_kind=by_kind
            )
        )
    flags = {}
    if by_kind["calendar"]["basis"].valid:
        rows = connection.execute(
            f"SELECT trade_date,is_open FROM {by_kind['calendar']['relation']} WHERE exchange='SSE' AND trade_date>=? AND trade_date<? ORDER BY trade_date",
            [month.month_start, month.month_end_exclusive],
        ).fetchall()
        for day, is_open in rows:
            flags.setdefault(day, []).append(is_open)
    open_dates, closed_dates, unknown_dates = [], [], []
    for day in dates:
        values = flags.get(day, ())
        if len(values) != 1 or values[0] is None:
            unknown_dates.append(day)
            issues[day]["calendar"] = issues[day].get(
                "calendar", "日历本日缺失、重复或开市标志为空"
            )
        else:
            (open_dates if values[0] else closed_dates).append(day)
    columns = ",".join(f"{c.name} {c.type}" for c in SILVER_STOCK_SUSPEND_DAILY_SCHEMA)
    connection.execute(f"CREATE TEMP TABLE {_SUSPEND} ({columns})")
    basis_inputs["active_month"] = month
    for day in dates:
        path = silver_stock_suspend_daily_path(lake_root, day.isoformat())
        fact = _load_basis(
            connection,
            path=path,
            kind="suspend",
            trade_date=day,
            basis_inputs=basis_inputs,
            known_records=known_records,
        )
        files.append(fact["basis"])
        if fact["basis"].valid:
            connection.execute(
                f"INSERT INTO {_SUSPEND} SELECT * FROM {fact['relation']}"
            )
        else:
            issues[day]["suspend"] = fact["reason"]
        if fact["owned"]:
            _drop(connection, (fact["relation"],))
            fact["relation"], fact["owned"] = None, False
    values = {
        "operation_id": approval.operation_id,
        "month": month,
        "natural_dates": dates,
        "open_dates": tuple(open_dates),
        "closed_dates": tuple(closed_dates),
        "calendar_unknown_dates": tuple(unknown_dates),
        "basis_files": tuple(
            sorted(files, key=lambda b: (b.kind, b.trade_date or date.min))
        ),
        "unknown_by_date": tuple(
            (
                d,
                tuple(sorted(issues[d])),
                "; ".join(issues[d][k] for k in sorted(issues[d])),
            )
            for d in dates
            if issues[d]
        ),
    }
    result = C.StkFactorProBootstrapCoverageInputs(
        **values,
        input_digest=C.stk_factor_pro_bootstrap_month_basis_digest(
            approval_digest=digest,
            **{k: v for k, v in values.items() if k != "unknown_by_date"},
        ),
    )
    basis_inputs["months"][month.month_start] = result
    return result


def release_stk_factor_pro_bootstrap_coverage_month(connection, *, basis_inputs):
    if basis_inputs["active_month"] is None:
        return
    basis_inputs["active_month"] = None
    _drop(connection, (_SUSPEND,))


def release_stk_factor_pro_bootstrap_coverage_inputs(connection, *, basis_inputs):
    releases = [
        lambda: release_stk_factor_pro_bootstrap_coverage_month(
            connection, basis_inputs=basis_inputs
        )
    ]
    for fact in basis_inputs["files"].values():
        if fact["owned"]:
            relation = fact["relation"]
            fact["owned"], fact["relation"] = False, None
            releases.append(lambda relation=relation: _drop(connection, (relation,)))
    with resource_cleanup(*releases):
        pass


def _targets(lake_root, day):
    return (
        raw_stk_factor_pro_path(lake_root, day.isoformat()),
        silver_stock_factor_pro_path(lake_root, day.isoformat()),
    )


def _date_digest(approval, digest, day, source, hashes, basis, is_open):
    return C.stk_factor_pro_bootstrap_date_coverage_input_digest(
        operation_id=approval.operation_id,
        approval_digest=digest,
        trade_date=day,
        is_open=is_open,
        source_complete_digest=source.source_complete_digest,
        source_rows=source.actual_rows,
        raw_file_sha256=hashes[0],
        silver_file_sha256=hashes[1],
        source_empty=source.source_empty,
        basis_files=basis,
    )


def _codes_path(staging_root, approval, day, ref):
    if ref.creator_run_id is None:
        return operation_path(staging_root, approval, ref.relative_path)
    path = (
        stk_factor_pro_run_staging_root(
            staging_root, ref.creator_run_id, day.isoformat()
        )
        / ref.relative_path
    )
    require_stk_factor_pro_safe_path(path)
    return path


def read_stk_factor_pro_bootstrap_coverage_date(
    connection,
    *,
    staging_root,
    approval,
    approval_digest,
    source_complete,
    trade_date,
    known_records,
):
    path = operation_path(staging_root, approval, f"coverage/{trade_date}/result.json")
    first = path not in known_records
    result = read_json(
        path, C.StkFactorProBootstrapDateCoverage, known_records=known_records
    )
    if result is None:
        return result
    if result.coverage_rule_version != C.STK_FACTOR_PRO_COVERAGE_RULE_VERSION:
        raise ValueError("覆盖结果规则已变，不能复用旧计数")
    if not first:
        return result
    try:
        if (
            source_complete is None
            or result.operation_id != approval.operation_id
            or result.approval_digest != approval_digest
            or result.trade_date != trade_date
            or result.source_complete_digest != source_complete.source_complete_digest
            or result.source_rows != source_complete.actual_rows
            or result.source_empty != source_complete.source_empty
            or result.input_digest
            != _date_digest(
                approval,
                approval_digest,
                trade_date,
                source_complete,
                (result.raw_file_sha256, result.silver_file_sha256),
                result.basis_files,
                result.is_open,
            )
        ):
            raise ValueError("覆盖结果与原operation/来源/输入摘要不符")
        for ref in (result.missing_codes_ref, result.extra_codes_ref):
            if ref is not None:
                referenced = _codes_path(staging_root, approval, trade_date, ref)
                if (
                    factor_known_file_sha(referenced, known_records=known_records)
                    != ref.file_sha256
                ):
                    raise ValueError("覆盖差集明细身份不符")
                if known_records[referenced][0] != ref:
                    table = _PREFIX + "detail"
                    with resource_cleanup(
                        lambda table=table: _drop(connection, (table,))
                    ):
                        connection.execute(
                            f"CREATE TEMP TABLE {table} AS SELECT * FROM {read_parquet(referenced, hive_partitioning=False)}"
                        )
                        if _schema(connection, table) != _CODE_SCHEMA:
                            raise ValueError("覆盖差集明细schema错误")
                        count, unique, invalid = connection.execute(
                            f"SELECT count(*),count(DISTINCT (ts_code,trade_date)),"
                            f"count(*) FILTER (WHERE trade_date IS DISTINCT FROM ? OR {stk_factor_pro_invalid_code_sql('ts_code')}) FROM {table}",
                            [trade_date],
                        ).fetchone()
                        if count != ref.row_count or unique != count or invalid:
                            raise ValueError("覆盖差集明细日期、代码、数量或唯一键不符")
                    known_records[referenced] = (
                        ref,
                        *known_records[referenced][1:],
                    )
    except BaseException:
        known_records.pop(path, None)
        raise
    return result


def prepare_stk_factor_pro_bootstrap_coverage_date(
    *,
    trade_date,
    inputs,
    basis_inputs,
    raw_audit,
    silver_audit,
):
    return prepare_stk_factor_pro_bootstrap_supplement_date(
        trade_date=trade_date,
        raw_audit=raw_audit,
        silver_audit=silver_audit,
        coverage_inputs=_bootstrap_date_inputs(trade_date, inputs, basis_inputs),
    )


def _bootstrap_date_inputs(trade_date, inputs, basis_inputs):
    if (
        trade_date not in inputs.natural_dates
        or basis_inputs["active_month"] != inputs.month
    ):
        raise ValueError("覆盖准备的月份或日期不符")
    if trade_date in inputs.closed_dates:
        raise ValueError("已确认休市有源属于冲突；休市空源只汇总分类")
    unknown, reason = next(
        ((k, r) for d, k, r in inputs.unknown_by_date if d == trade_date), ((), "")
    )
    relations = {"suspend": _SUSPEND}
    for fact in basis_inputs["files"].values():
        if fact["basis"].trade_date is None:
            relations[fact["basis"].kind] = fact["relation"]
    coverage_inputs = {
        "trade_date": trade_date,
        "basis_files": tuple(
            b
            for b in inputs.basis_files
            if b.trade_date is None or b.trade_date == trade_date
        ),
        "is_open": True if trade_date in inputs.open_dates else None,
        "unknown_input_kinds": unknown,
        "reason": reason,
        "relations": relations,
    }
    return coverage_inputs


def prepare_stk_factor_pro_bootstrap_supplement_date(
    *,
    trade_date,
    raw_audit,
    silver_audit,
    coverage_inputs,
):
    if (
        trade_date != coverage_inputs["trade_date"]
        or coverage_inputs["is_open"] is False
    ):
        raise ValueError("初始化补数日期与开市依据不符")
    for audit, layer in ((raw_audit, "raw"), (silver_audit, "silver")):
        if (
            not isinstance(audit, C.StkFactorProFileAudit)
            or not audit.passed
            or audit.trade_date != trade_date
            or audit.layer != layer
        ):
            raise ValueError("当前两层有效audit与日期/层不符")
    if raw_audit.row_count != silver_audit.row_count:
        raise ValueError("当前Raw/Silver数量不一致")
    return {
        **coverage_inputs,
        "raw_audit": raw_audit,
        "silver_audit": silver_audit,
        "raw_rows": raw_audit.row_count,
        "silver_rows": silver_audit.row_count,
        "raw_physical_code_count": raw_audit.row_count,
        "raw_file_sha256": raw_audit.file_sha256,
        "silver_file_sha256": silver_audit.file_sha256,
    }


def require_stk_factor_pro_bootstrap_coverage_identities(
    *, lake_root, prepared, known_records
):
    for path in _targets(lake_root, prepared["trade_date"]):
        fact = known_records.get(path)
        current = _stat(path)
        if fact is None or current != fact[2]:
            raise ValueError("当前Raw/Silver在首次确认后已改变")
    for basis in prepared["basis_files"]:
        path = _basis_path(lake_root, basis)
        fact = known_records.get(path)
        if fact is None:
            raise ValueError("覆盖依据缺少首次身份交接")
        try:
            current = _stat(path)
        except OSError:
            if not basis.valid and basis.file_sha256 is None:
                continue
            raise
        if current != fact[2]:
            raise ValueError("本地覆盖依据在首次读取后改变")


def _write_codes(
    connection,
    *,
    staging_root,
    approval,
    day,
    digest,
    kind,
    count,
    diagnostic_run,
    check_space,
    known_records,
):
    if count == 0:
        return None, ()
    if diagnostic_run is not None and day == diagnostic_run.target_trade_date:
        root = stk_factor_pro_run_staging_root(
            staging_root, diagnostic_run.creator_run_id, day.isoformat()
        )
        relative, creator = (
            f"diagnostics/day-{kind}-codes.parquet",
            diagnostic_run.creator_run_id,
        )
        path = root / relative
    else:
        if diagnostic_run is not None and day > diagnostic_run.target_trade_date:
            raise ValueError("覆盖诊断日期不能晚于本run原T")
        relative, creator = f"coverage/{day}/input={digest}/{kind}-codes.parquet", None
        path = operation_path(staging_root, approval, relative)
    require_stk_factor_pro_safe_path(path)
    relation, saved = "stk_factor_pro_coverage_" + kind, _PREFIX + "detail"
    sample = tuple(
        r[0]
        for r in connection.execute(
            f"SELECT ts_code FROM {relation} ORDER BY ts_code LIMIT 20"
        ).fetchall()
    )
    check_space("覆盖差集保存前", path=path, trade_date=day, rows=count)
    exists = path.is_file()
    temporary = path if exists else path.with_name(path.name + f".{uuid4().hex}.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with resource_cleanup(
        lambda: _drop(connection, (saved,)),
        lambda: temporary.unlink(missing_ok=True) if not exists else None,
    ):
        if not exists:
            connection.execute(
                f"COPY (SELECT ts_code,trade_date FROM {relation} ORDER BY ts_code,trade_date) TO ? (FORMAT PARQUET)",
                [str(temporary)],
            )
        digest_bytes = factor_known_file_sha(temporary, known_records=known_records)
        connection.execute(
            f"CREATE TEMP TABLE {saved} AS SELECT * FROM {read_parquet(temporary, hive_partitioning=False)}"
        )
        if _schema(connection, saved) != _CODE_SCHEMA:
            raise ValueError("覆盖差集明细schema错误")
        invalid = connection.execute(
            f"SELECT count(*) FROM {saved} WHERE trade_date IS DISTINCT FROM ? OR {stk_factor_pro_invalid_code_sql('ts_code')}",
            [day],
        ).fetchone()[0]
        difference = connection.execute(
            f"SELECT count(*) FROM ((SELECT ts_code,trade_date FROM {relation} EXCEPT ALL SELECT ts_code,trade_date FROM {saved}) UNION ALL (SELECT ts_code,trade_date FROM {saved} EXCEPT ALL SELECT ts_code,trade_date FROM {relation}))"
        ).fetchone()[0]
        if invalid or difference:
            raise ValueError("覆盖差集明细与首次差集不符")
        if not exists:
            atomic_promote(temporary, path)
            known_records.pop(temporary)
        reference = C.StkFactorProBootstrapCodesRef(
            creator, relative, digest_bytes, count
        )
        known_records[path] = (reference, digest_bytes, factor_file_identity(path))
        check_space(
            "覆盖差集已保存",
            path=path,
            trade_date=day,
            rows=count,
            event="record_saved",
        )
    return reference, sample


def compute_stk_factor_pro_bootstrap_coverage_date(
    connection,
    *,
    lake_root,
    staging_root,
    approval,
    prepared,
    raw_relation,
    diagnostic_run,
    input_digest,
    check_space,
    known_records,
):
    check_space(
        "计算本日覆盖前",
        path=operation_path(staging_root, approval, "coverage"),
        trade_date=prepared["trade_date"],
        rows=prepared["raw_rows"],
    )
    if (
        raw_relation is None
        and prepared["raw_rows"]
        and not prepared["unknown_input_kinds"]
    ):
        raise ValueError("非空当前Raw缺已有代码关系，禁止回盘补参")
    with resource_cleanup(
        lambda: release_stk_factor_pro_coverage_keys(
            connection, coverage_inputs=prepared
        )
    ):
        calculated = calculate_stk_factor_pro_coverage(
            connection,
            coverage_inputs=prepared,
            raw_relation=raw_relation,
        )
        counts = calculated["coverage_counts"]
        if counts is not None and counts.expected_count is not None:
            for kind in ("missing", "extra"):
                ref, sample = _write_codes(
                    connection,
                    staging_root=staging_root,
                    approval=approval,
                    day=prepared["trade_date"],
                    digest=input_digest,
                    kind=kind,
                    count=getattr(counts, kind + "_count"),
                    diagnostic_run=diagnostic_run,
                    check_space=check_space,
                    known_records=known_records,
                )
                calculated[kind + "_codes_ref"] = ref
                calculated[kind + "_sample_codes"] = sample
    return calculated


def evaluate_stk_factor_pro_bootstrap_coverage_date(
    *,
    prepared,
    calculated,
    approval_digest,
    input_digest,
    source_complete,
    current_publication,
    previous_result,
):
    source = source_complete
    if (
        source.trade_date != prepared["trade_date"]
        or source.approval_digest != approval_digest
    ):
        raise ValueError("最终覆盖记录原来源与批准/日期不符")
    if current_publication is not None and (
        current_publication.trade_date != prepared["trade_date"]
        or current_publication.contract_content_digest
        != C.STK_FACTOR_PRO_CONTRACT_CONTENT_DIGEST
        or current_publication.processing_version != C.STK_FACTOR_PRO_PROCESSING_VERSION
        or current_publication.raw_file_sha256 != prepared["raw_file_sha256"]
        or current_publication.silver_file_sha256 != prepared["silver_file_sha256"]
        or current_publication.silver_source_raw_sha256 != prepared["raw_file_sha256"]
    ):
        raise ValueError("补数发布与本日两层audit不符")
    counts = calculated["coverage_counts"]
    values = {
        name: getattr(counts, name) if counts is not None else None
        for name in (
            "expected_count",
            "actual_count",
            "matched_count",
            "missing_count",
            "extra_count",
            "identity_unmapped_count",
            "identity_ambiguous_count",
        )
    }
    result = C.StkFactorProBootstrapDateCoverage(
        record_version=1,
        coverage_rule_version=C.STK_FACTOR_PRO_COVERAGE_RULE_VERSION,
        operation_id=source.operation_id,
        approval_digest=approval_digest,
        trade_date=prepared["trade_date"],
        source_rows=source.actual_rows,
        raw_rows=prepared["raw_rows"],
        silver_rows=prepared["silver_rows"],
        raw_physical_code_count=prepared["raw_physical_code_count"],
        source_complete_digest=source.source_complete_digest,
        raw_file_sha256=prepared["raw_file_sha256"],
        silver_file_sha256=prepared["silver_file_sha256"],
        import_complete=True,
        source_empty=source.source_empty,
        current_publication=current_publication,
        is_open=prepared["is_open"],
        basis_files=prepared["basis_files"],
        unknown_input_kinds=calculated["unknown_input_kinds"],
        input_digest=input_digest,
        **values,
        identity_unmapped_sample_codes=counts.identity_unmapped_sample_codes
        if counts
        else (),
        identity_ambiguous_sample_codes=counts.identity_ambiguous_sample_codes
        if counts
        else (),
        coverage_complete=(counts.missing_count == 0 and counts.extra_count == 0)
        if counts and counts.missing_count is not None
        else None,
        reason=calculated["reason"] or "覆盖依据不足，无法判断",
        missing_codes_ref=calculated["missing_codes_ref"],
        extra_codes_ref=calculated["extra_codes_ref"],
        missing_sample_codes=calculated["missing_sample_codes"],
        extra_sample_codes=calculated["extra_sample_codes"],
        evaluated_at=_now(),
    )

    if (
        previous_result is not None
        and replace(result, evaluated_at=previous_result.evaluated_at)
        == previous_result
    ):
        return previous_result
    return result


def write_stk_factor_pro_bootstrap_coverage_date(
    connection,
    *,
    lake_root,
    staging_root,
    approval,
    result,
    previous_result,
    previous_result_digest,
    date_results,
    check_space,
    known_records,
):
    path = operation_path(
        staging_root, approval, f"coverage/{result.trade_date}/result.json"
    )
    old = known_records.get(path)
    approval_fact = known_records.get(
        operation_path(staging_root, approval, "approval.json")
    )
    if (
        old is None
        or old[0] != previous_result
        or old[1] != previous_result_digest
        or result.operation_id != approval.operation_id
        or approval_fact is None
        or result.approval_digest != approval_fact[1]
    ):
        raise ValueError("覆盖写入缺已交接的原日期记录/摘要")
    entry = date_results[result.trade_date]
    source = entry["source_complete"]
    if (
        source is None
        or result.source_complete_digest != source.source_complete_digest
        or result.source_rows != source.actual_rows
    ):
        raise ValueError("覆盖写入未对应本日期已核原源事实")

    def register(record, digest):
        entry["persisted_result"] = record
        entry["persisted_result_digest"] = digest
        entry["computed_result"] = None
        entry["coverage_record_current"] = True
        entry["unknown_reason"] = ""

    if result == previous_result:
        register(previous_result, previous_result_digest)
        return previous_result, previous_result_digest

    def replaced():
        entry["persisted_result"] = None
        entry["persisted_result_digest"] = None
        entry["coverage_record_current"] = False

    def observe(stage, **facts):
        saved = known_records.get(path)
        if (
            facts.get("event") == "record_saved"
            and saved is not None
            and saved[0] is result
        ):
            register(result, saved[1])
        return check_space(stage, **facts)

    return write_json(
        path,
        result,
        mutable=True,
        known_records=known_records,
        on_replaced=replaced,
        check_space=observe,
    )


def update_stk_factor_pro_bootstrap_after_publication(
    connection,
    *,
    lake_root,
    staging_root,
    approval,
    result,
    previous_result,
    previous_result_digest,
    known_records,
    date_results,
    check_space,
):
    return write_stk_factor_pro_bootstrap_coverage_date(
        connection,
        lake_root=lake_root,
        staging_root=staging_root,
        approval=approval,
        result=result,
        previous_result=previous_result,
        previous_result_digest=previous_result_digest,
        date_results=date_results,
        check_space=check_space,
        known_records=known_records,
    )


_ORIGINAL_COUNTS = ("verified_source_rows", "verified_raw_rows", "verified_silver_rows")
_CURRENT_COUNTS = ("current_raw_rows", "current_silver_rows")
_COVERAGE_COUNTS = (
    "expected_count_known_dates",
    "actual_count_known_dates",
    "matched_count_known_dates",
    "missing_count_known_dates",
    "extra_count_known_dates",
)
_SETS = (
    "known_open_dates",
    "known_closed_dates",
    "calendar_unknown_dates",
    "imported_dates",
    "source_empty_dates",
    "import_pending_dates",
    "known_coverage_dates",
    "gap_dates",
    "current_files_unverified_dates",
    "verified_current_dates",
    "open_coverage_pending_dates",
)


def new_stk_factor_pro_bootstrap_coverage_totals(*, natural_dates):
    return {
        "natural_dates": natural_dates,
        "counts": {
            name: 0 for name in (*_ORIGINAL_COUNTS, *_CURRENT_COUNTS, *_COVERAGE_COUNTS)
        },
        "sets": {name: set() for name in _SETS},
        "unknown_by_date": {},
        "date_result_digests": {},
        "version": 0,
        "saved_version": None,
    }


def refresh_stk_factor_pro_bootstrap_date_contribution(
    *, trade_date, entry, totals, is_open, approved_rows
):
    source, raw, silver = (
        entry["source_complete"],
        entry["raw_complete"],
        entry["silver_complete"],
    )
    imported = (
        source is not None
        and entry["import_complete"]
        and (source.source_empty or raw is not None and silver is not None)
    )
    original = (
        (
            source.actual_rows,
            raw.actual_rows if raw is not None else 0,
            silver.actual_rows if silver is not None else 0,
        )
        if imported
        else None
    )
    current = None
    if imported and entry["current_files_verified"]:
        a, b = entry["raw_audit"], entry["silver_audit"]
        if a is not None and b is not None:
            current = a.row_count, b.row_count
        elif source.source_empty and entry["current_publication"] is None:
            current = (0, 0)
    result = entry["persisted_result"]
    applicable = (
        result is not None and entry["coverage_record_current"] and current is not None
    )
    known = applicable and result.coverage_complete is not None and is_open is True
    numbers = (
        tuple(
            getattr(result, name)
            for name in (
                "expected_count",
                "actual_count",
                "matched_count",
                "missing_count",
                "extra_count",
            )
        )
        if known
        else None
    )
    memberships = {
        "known_open_dates"
        if is_open is True
        else "known_closed_dates"
        if is_open is False
        else "calendar_unknown_dates"
    }
    if imported:
        memberships.add("imported_dates")
        if source.source_empty:
            memberships.add("source_empty_dates")
    if not imported and not (is_open is False and approved_rows == 0):
        memberships.add("import_pending_dates")
    if imported and current is None:
        memberships.add("current_files_unverified_dates")
    if applicable or current is not None and is_open is False:
        memberships.add("verified_current_dates")
    if known:
        memberships.add("known_coverage_dates")
        if result.missing_count:
            memberships.add("gap_dates")
    if is_open is True and not known:
        memberships.add("open_coverage_pending_dates")
    unknown = None
    if is_open is not False:
        kinds = ("calendar",) if is_open is None else ()
        if not imported:
            reason = "原日期导入尚未完成"
        elif current is None:
            reason = entry["unknown_reason"] or "当前两层文件或发布依据未确认"
        elif not applicable:
            reason = entry["unknown_reason"] or "本日覆盖统计尚未完成"
        elif not known:
            kinds = tuple(sorted(set(kinds) | set(result.unknown_input_kinds)))
            reason = result.reason
        else:
            reason = ""
        if reason:
            unknown = (kinds, reason)
    digest = entry["persisted_result_digest"] if applicable else None
    contribution = {
        "original": original,
        "current": current,
        "known": numbers,
        "sets": frozenset(memberships),
        "unknown": unknown,
        "result_digest": digest,
    }
    _replace_stk_factor_pro_bootstrap_contribution(
        trade_date=trade_date,
        entry=entry,
        totals=totals,
        contribution=contribution,
    )


def _replace_stk_factor_pro_bootstrap_contribution(
    *, trade_date, entry, totals, contribution
):
    unknown, digest = contribution["unknown"], contribution["result_digest"]
    previous = entry["previous_contribution"]
    if contribution == previous:
        return
    for group, names in (
        ("original", _ORIGINAL_COUNTS),
        ("current", _CURRENT_COUNTS),
        ("known", _COVERAGE_COUNTS),
    ):
        before, after = (
            previous[group] if previous is not None else None,
            contribution[group],
        )
        if before != after:
            for index, name in enumerate(names):
                totals["counts"][name] += (after[index] if after is not None else 0) - (
                    before[index] if before is not None else 0
                )
    old_sets = previous["sets"] if previous is not None else frozenset()
    for name in old_sets - contribution["sets"]:
        totals["sets"][name].discard(trade_date)
    for name in contribution["sets"] - old_sets:
        totals["sets"][name].add(trade_date)
    if unknown is None:
        totals["unknown_by_date"].pop(trade_date, None)
    else:
        totals["unknown_by_date"][trade_date] = unknown
    if digest is None:
        totals["date_result_digests"].pop(trade_date, None)
    else:
        totals["date_result_digests"][trade_date] = digest
    entry["previous_contribution"] = contribution
    totals["version"] += 1


def summarize_stk_factor_pro_bootstrap_coverage(
    *,
    staging_root,
    approval,
    approval_digest,
    totals,
    previous_summary,
    previous_summary_digest,
    check_space,
    known_records,
):
    if totals["saved_version"] == totals["version"]:
        return previous_summary, previous_summary_digest
    path = operation_path(staging_root, approval, "coverage/summary.json")
    prior_fact = known_records.get(path)
    if (
        prior_fact is None
        or prior_fact[0] != previous_summary
        or prior_fact[1] != previous_summary_digest
    ):
        raise ValueError("汇总缺首次交接的原summary及摘要")
    sets, counts = totals["sets"], totals["counts"]
    determined = not (
        sets["calendar_unknown_dates"]
        or sets["import_pending_dates"]
        or sets["current_files_unverified_dates"]
        or sets["open_coverage_pending_dates"]
    )
    current_valid = not (
        sets["import_pending_dates"] or sets["current_files_unverified_dates"]
    )
    result = C.StkFactorProBootstrapCoverageSummary(
        record_version=1,
        operation_id=approval.operation_id,
        approval_digest=approval_digest,
        start_trade_date=approval.start_trade_date,
        end_trade_date=approval.end_trade_date,
        evaluated_at=previous_summary.evaluated_at
        if previous_summary is not None
        else _now(),
        **{
            name: tuple(sorted(sets[name]))
            for name in (
                "known_open_dates",
                "known_closed_dates",
                "calendar_unknown_dates",
                "imported_dates",
                "source_empty_dates",
                "import_pending_dates",
                "known_coverage_dates",
                "gap_dates",
                "current_files_unverified_dates",
            )
        },
        coverage_unknown_dates=tuple(
            (day, *value) for day, value in sorted(totals["unknown_by_date"].items())
        ),
        **{name: counts[name] for name in (*_ORIGINAL_COUNTS, *_COVERAGE_COUNTS)},
        current_raw_rows=counts["current_raw_rows"] if current_valid else None,
        current_silver_rows=counts["current_silver_rows"] if current_valid else None,
        date_result_digests=tuple(sorted(totals["date_result_digests"].items())),
        all_coverage_determined=determined,
        total_missing_count=counts["missing_count_known_dates"] if determined else None,
        all_expected_present=(counts["missing_count_known_dates"] == 0)
        if determined
        else None,
    )
    if result == previous_summary:
        totals["saved_version"] = totals["version"]
        return previous_summary, previous_summary_digest
    if previous_summary is not None:
        result = replace(result, evaluated_at=_now())
    saved = write_json(
        path, result, mutable=True, check_space=check_space, known_records=known_records
    )
    totals["saved_version"] = totals["version"]
    return saved
