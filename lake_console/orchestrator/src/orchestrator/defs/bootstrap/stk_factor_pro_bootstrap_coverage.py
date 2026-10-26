"""Local bootstrap coverage. No event discovery, source export or business writes."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import duckdb

from orchestrator.defs.asset_guards.stk_factor_pro_readiness import (
    build_stk_factor_pro_coverage_keys,
)
from orchestrator.defs.assets.stock_identity_map import (
    STOCK_IDENTITY_ALLOWED_CONFIDENCE,
    STOCK_IDENTITY_ALLOWED_SOURCES,
)
from orchestrator.defs.bootstrap.stk_factor_pro_bootstrap_publication import (
    read_stk_factor_pro_bootstrap_publication,
)
from orchestrator.defs.bootstrap.stk_factor_pro_bootstrap_records import (
    approval_sha,
    atomic_promote,
    operation_path,
    read_json,
    read_stk_factor_pro_bootstrap_source_complete,
    resource_cleanup,
    write_json,
)
from orchestrator.defs.checks.stk_factor_pro import factor_file_sha
from orchestrator.defs.duckdb_sql import BJ_MARKET_OPEN_DATE, read_parquet
from orchestrator.defs.io.stk_factor_pro_candidates import (
    require_stk_factor_pro_safe_path,
)
from orchestrator.defs.paths import (
    raw_stk_factor_pro_path,
    silver_stock_factor_pro_path,
    silver_stock_identity_map_path,
    silver_stock_lifecycle_path,
    silver_stock_suspend_daily_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.run_contracts import stk_factor_pro as C
from orchestrator.defs.run_contracts.asset_column_schemas import (
    SILVER_STOCK_IDENTITY_MAP_SCHEMA,
    SILVER_STOCK_LIFECYCLE_SCHEMA,
    SILVER_STOCK_SUSPEND_DAILY_SCHEMA,
    SILVER_TRADE_CALENDAR_SCHEMA,
)
from orchestrator.tushare_download.contract_registry import content_digest

_GLOBALS = {
    "calendar": (silver_trade_calendar_path, SILVER_TRADE_CALENDAR_SCHEMA),
    "lifecycle": (silver_stock_lifecycle_path, SILVER_STOCK_LIFECYCLE_SCHEMA),
    "identity": (silver_stock_identity_map_path, SILVER_STOCK_IDENTITY_MAP_SCHEMA),
}
_PREFIX = "stk_factor_bootstrap_coverage_"
_CACHE = _PREFIX + "cache"
_MONTH = _PREFIX + "month"
_IDENTITIES = _PREFIX + "file_identities"
_SUSPEND = _PREFIX + "suspend"
_DAILY = tuple(_PREFIX + suffix for suffix in ("listed", "full_suspend", "actual"))
_PURE_TABLES = tuple(
    "stk_factor_pro_coverage_" + suffix
    for suffix in (
        "missing",
        "extra",
        "mapping",
        "expected",
        "listed",
        "suspend",
        "actual",
    )
)
_CODE_SCHEMA = (("trade_date", "DATE"), ("ts_code", "VARCHAR"))


def _now():
    return datetime.now(ZoneInfo("Asia/Shanghai"))


def _days(first, last_exclusive):
    return tuple(
        first + timedelta(days=i) for i in range((last_exclusive - first).days)
    )


def _schema(connection, relation):
    return tuple(
        (r[0], r[1])
        for r in connection.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()
    )


def _drop(connection, names):
    # Each callback is separate: a cleanup failure must not prevent later releases.
    with resource_cleanup(
        *(
            lambda name=n: connection.execute(f"DROP TABLE IF EXISTS {name}")
            for n in names
        )
    ):
        pass


def _file_sha(path):
    require_stk_factor_pro_safe_path(path)
    return factor_file_sha(path) if path.is_file() else None


def _basis_path(lake_root, basis):
    if basis.kind == "suspend":
        return silver_stock_suspend_daily_path(lake_root, basis.trade_date.isoformat())
    return _GLOBALS[basis.kind][0](lake_root)


def _stat(path):
    require_stk_factor_pro_safe_path(path)
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def _cached_sha(connection, path):
    """The borrowed connection owns this cache; no process-global state or lock."""
    connection.execute(
        f"CREATE TEMP TABLE IF NOT EXISTS {_IDENTITIES} (path VARCHAR,signature VARCHAR,sha VARCHAR)"
    )
    before = _stat(path)
    cached = connection.execute(
        f"SELECT signature,sha FROM {_IDENTITIES} WHERE path=?", [str(path)]
    ).fetchone()
    signature = str(before)
    if cached is not None and cached[0] == signature:
        return cached[1]
    sha = _file_sha(path)
    if _stat(path) != before:
        raise ValueError("覆盖输入核摘要期间改变")
    connection.execute(f"DELETE FROM {_IDENTITIES} WHERE path=?", [str(path)])
    connection.execute(
        f"INSERT INTO {_IDENTITIES} VALUES (?,?,?)", [str(path), signature, sha]
    )
    return sha


def _observed_sha(path, cache=None, connection=None):
    if cache is not None and path in cache:
        return cache[path]
    value = _cached_sha(connection, path) if connection is not None else _file_sha(path)
    if cache is not None:
        cache[path] = value
    return value


def _basis_current(lake_root, basis_files, cache=None, connection=None):
    for basis in basis_files:
        try:
            current = _observed_sha(_basis_path(lake_root, basis), cache, connection)
        except OSError:
            if not basis.valid and basis.file_sha256 is None:
                continue
            return False
        if current != basis.file_sha256:
            return False
    return True


def _validate_lifecycle(connection, table):
    required = ("ts_code", "symbol", "name", "exchange", "curr_type", "list_status")
    empty = " OR ".join(f"{name} IS NULL OR trim({name})=''" for name in required)
    invalid = connection.execute(
        f"SELECT count(*) FROM {table} WHERE {empty} OR is_cny_stock IS DISTINCT FROM true "
        "OR curr_type IS DISTINCT FROM 'CNY' OR list_date IS NULL "
        "OR (delist_date IS NOT NULL AND delist_date<list_date)"
    ).fetchone()[0]
    duplicates = connection.execute(
        f"SELECT count(*) FROM (SELECT ts_code FROM {table} GROUP BY ts_code HAVING count(*)>1)"
    ).fetchone()[0]
    if invalid or duplicates:
        raise ValueError("生命周期必需字段、股票域、日期或唯一键不符")


def _validate_identity(connection, table):
    invalid = connection.execute(
        f"SELECT count(*) FROM {table} i WHERE source_ts_code IS NULL OR trim(source_ts_code)='' "
        "OR latest_ts_code IS NULL OR trim(latest_ts_code)='' OR valid_from IS NULL "
        "OR (valid_to IS NOT NULL AND valid_to<valid_from) "
        f"OR NOT EXISTS (SELECT 1 FROM {_PREFIX}lifecycle l WHERE l.ts_code=i.latest_ts_code) "
        "OR identity_source IS NULL OR identity_source NOT IN (SELECT unnest(?::VARCHAR[])) "
        "OR confidence IS NULL OR confidence NOT IN (SELECT unnest(?::VARCHAR[]))",
        [
            sorted(STOCK_IDENTITY_ALLOWED_SOURCES),
            sorted(STOCK_IDENTITY_ALLOWED_CONFIDENCE),
        ],
    ).fetchone()[0]
    duplicates = connection.execute(
        f"SELECT count(*) FROM (SELECT source_ts_code FROM {table} GROUP BY source_ts_code HAVING count(*)>1)"
    ).fetchone()[0]
    if invalid or duplicates:
        raise ValueError("身份映射字段、来源域、日期、唯一键或生命周期引用不符")
    # Producer seed completeness is checked by stock_identity_map_checks; this
    # consumer verifies the four approved physical inputs, not a fifth seed file.


def _load_basis(connection, *, path, kind, trade_date=None, dependency=""):
    table = _PREFIX + ("probe" if kind == "suspend" else kind)
    expected = (
        SILVER_STOCK_SUSPEND_DAILY_SCHEMA if kind == "suspend" else _GLOBALS[kind][1]
    )
    try:
        before = _cached_sha(connection, path)
    except OSError as error:
        return C.StkFactorProBootstrapBasisFile(
            kind, trade_date, None, None, None, False
        ), f"{kind}依据无法读取：{error}"
    if kind != "suspend":
        cached = connection.execute(
            f"SELECT file_sha,schema_digest,rows,valid,reason FROM {_CACHE} WHERE kind=? AND path=? AND dependency=?",
            [kind, str(path), dependency],
        ).fetchone()
        if cached is not None and cached[0] == before:
            return C.StkFactorProBootstrapBasisFile(kind, None, *cached[:4]), cached[4]
    schema_digest = row_count = None
    valid, reason = False, f"{kind}依据文件不存在"
    try:
        if before is not None:
            query = read_parquet(path, hive_partitioning=False)
            observed = _schema(connection, query)
            schema_digest = content_digest(observed)
            if observed != tuple((c.name, c.type) for c in expected):
                raise ValueError(f"{kind}依据schema不符")
            connection.execute(
                f"CREATE OR REPLACE TEMP TABLE {table} AS SELECT * FROM {query}"
            )
            row_count = connection.execute(f"SELECT count(*) FROM {table}").fetchone()[
                0
            ]
            if kind == "calendar":
                # Per-day duplicates/missing/NULL flags only invalidate that day.
                if connection.execute(
                    f"SELECT count(*) FROM {table} WHERE exchange IS NULL OR trim(exchange)='' "
                    "OR trade_date IS NULL"
                ).fetchone()[0]:
                    raise ValueError("日历含无法归属日期的行")
            elif kind == "lifecycle":
                if not row_count:
                    raise ValueError("生命周期为空")
                _validate_lifecycle(connection, table)
            elif kind == "identity":
                if not row_count:
                    raise ValueError("身份映射为空")
                _validate_identity(connection, table)
            else:
                invalid = connection.execute(
                    f"SELECT count(*) FROM {table} WHERE ts_code IS NULL OR trim(ts_code)='' "
                    "OR trade_date IS DISTINCT FROM ? OR suspend_type IS NULL OR suspend_type NOT IN ('S','R') "
                    "OR (suspend_timing IS NOT NULL AND trim(suspend_timing)='')",
                    [trade_date],
                ).fetchone()[0]
                duplicates = connection.execute(
                    f"SELECT count(*) FROM (SELECT ts_code,trade_date,suspend_type,coalesce(suspend_timing,'') "
                    f"FROM {table} GROUP BY ALL HAVING count(*)>1)"
                ).fetchone()[0]
                # duckdb_sql._suspend_d_normalized_from_sql maps blank timing to
                # NULL. Nonempty timing stays intraday; there is no HH:MM regex.
                if invalid or duplicates:
                    raise ValueError("最终停牌日期、类型、时段或业务键不符")
            valid, reason = True, ""
    except (OSError, ValueError, duckdb.Error) as error:
        valid, reason = False, f"{kind}依据无效：{error}"
    if _cached_sha(connection, path) != before:
        _drop(connection, (table,))
        raise ValueError("覆盖依据读取期间改变，请仅重新准备本地依据")
    basis = C.StkFactorProBootstrapBasisFile(
        kind, trade_date, before, schema_digest, row_count, valid
    )
    if not valid:
        _drop(connection, (table,))
    if kind != "suspend":
        connection.execute(f"DELETE FROM {_CACHE} WHERE kind=?", [kind])
        connection.execute(
            f"INSERT INTO {_CACHE} VALUES (?,?,?,?,?,?,?,?,?)",
            [
                kind,
                str(path),
                dependency,
                before,
                schema_digest,
                row_count,
                valid,
                reason,
                "",
            ],
        )
    return basis, reason


def _month_digest(approval, approval_digest, inputs):
    return C.stk_factor_pro_bootstrap_month_basis_digest(
        operation_id=approval.operation_id,
        approval_digest=approval_digest,
        month=inputs.month,
        natural_dates=inputs.natural_dates,
        open_dates=inputs.open_dates,
        closed_dates=inputs.closed_dates,
        calendar_unknown_dates=inputs.calendar_unknown_dates,
        basis_files=inputs.basis_files,
    )


def prepare_stk_factor_pro_bootstrap_coverage_month(
    connection,
    *,
    lake_root,
    staging_root,
    approval,
    month,
):
    digest = approval_sha(staging_root, approval)
    if month not in approval.month_limits:
        raise ValueError("覆盖月份不属于本次批准")
    connection.execute(
        f"CREATE TEMP TABLE IF NOT EXISTS {_CACHE} (kind VARCHAR,path VARCHAR,dependency VARCHAR,"
        "file_sha VARCHAR,schema_digest VARCHAR,rows BIGINT,valid BOOLEAN,reason VARCHAR,reserved VARCHAR)"
    )
    connection.execute(
        f"CREATE TEMP TABLE IF NOT EXISTS {_IDENTITIES} (path VARCHAR,signature VARCHAR,sha VARCHAR)"
    )
    _drop(connection, (_MONTH, _SUSPEND, _PREFIX + "probe"))
    dates = _days(month.month_start, month.month_end_exclusive)
    files, issues = [], {d: {} for d in dates}
    by_kind = {}
    for kind in ("calendar", "lifecycle", "identity"):
        dependency = str(by_kind.get("lifecycle")) if kind == "identity" else ""
        if kind == "identity" and not by_kind["lifecycle"].valid:
            # Validate schema/rows as possible, but never reference an invalid
            # lifecycle table left over from another preparation.
            basis = C.StkFactorProBootstrapBasisFile(
                kind,
                None,
                _cached_sha(connection, _GLOBALS[kind][0](lake_root)),
                None,
                None,
                False,
            )
            reason = "生命周期无效，无法核验身份映射引用"
        else:
            basis, reason = _load_basis(
                connection,
                path=_GLOBALS[kind][0](lake_root),
                kind=kind,
                dependency=dependency,
            )
        by_kind[kind] = basis
        files.append(basis)
        if not basis.valid:
            for day in dates:
                issues[day][kind] = reason
    open_dates, closed_dates, unknown_dates = [], [], []
    for day in dates:
        flags = (
            connection.execute(
                f"SELECT is_open FROM {_PREFIX}calendar WHERE exchange='SSE' AND trade_date=?",
                [day],
            ).fetchall()
            if by_kind["calendar"].valid
            else ()
        )
        if len(flags) != 1 or flags[0][0] is None:
            unknown_dates.append(day)
            issues[day]["calendar"] = issues[day].get(
                "calendar", "日历本日缺失、重复或开市标志为空"
            )
        else:
            (open_dates if flags[0][0] else closed_dates).append(day)
    columns = ",".join(f"{c.name} {c.type}" for c in SILVER_STOCK_SUSPEND_DAILY_SCHEMA)
    connection.execute(f"CREATE TEMP TABLE {_SUSPEND} ({columns})")
    with resource_cleanup(lambda: _drop(connection, (_PREFIX + "probe",))):
        for day in dates:
            basis, reason = _load_basis(
                connection,
                path=silver_stock_suspend_daily_path(lake_root, day.isoformat()),
                kind="suspend",
                trade_date=day,
            )
            files.append(basis)
            if basis.valid:
                connection.execute(
                    f"INSERT INTO {_SUSPEND} SELECT * FROM {_PREFIX}probe"
                )
            else:
                issues[day]["suspend"] = reason
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
    connection.execute(
        f"CREATE TEMP TABLE {_MONTH} AS SELECT ?::VARCHAR AS input_digest",
        [result.input_digest],
    )
    return result


def release_stk_factor_pro_bootstrap_coverage_month(connection):
    """Release month/day working rows, retaining only the three global inputs."""
    with resource_cleanup(
        lambda: _drop(
            connection,
            (
                _MONTH,
                _SUSPEND,
                _PREFIX + "probe",
                _PREFIX + "detail",
                *_DAILY,
                *_PURE_TABLES,
            ),
        ),
        lambda: connection.execute(
            f"DELETE FROM {_IDENTITIES} WHERE path NOT IN (SELECT path FROM {_CACHE})"
        ),
    ):
        pass


def _require_inputs(
    connection, *, lake_root, staging_root, approval, inputs, trade_date
):
    digest = approval_sha(staging_root, approval)
    if (
        inputs.operation_id != approval.operation_id
        or inputs.month not in approval.month_limits
        or trade_date not in inputs.natural_dates
        or _month_digest(approval, digest, inputs) != inputs.input_digest
        or connection.execute(f"SELECT input_digest FROM {_MONTH}").fetchone()[0]
        != inputs.input_digest
    ):
        raise ValueError("覆盖月份、日期、摘要或当前连接关系不符")
    basis = tuple(
        b
        for b in inputs.basis_files
        if b.trade_date is None or b.trade_date == trade_date
    )
    if not _basis_current(lake_root, basis, connection=connection):
        raise ValueError("本地覆盖依据已改变，请重新准备，不重新导出来源")
    return digest, basis


def _targets(lake_root, day):
    return (
        raw_stk_factor_pro_path(lake_root, day.isoformat()),
        silver_stock_factor_pro_path(lake_root, day.isoformat()),
    )


def _source(staging_root, approval, day, expected=None):
    source = read_stk_factor_pro_bootstrap_source_complete(
        None, staging_root=staging_root, approval=approval, trade_date=day
    )
    if source is None or (expected is not None and source != expected):
        raise ValueError("缺少相符的原bootstrap完整日源")
    return source


def _original_publications(*, lake_root, staging_root, approval, source):
    records = tuple(
        read_stk_factor_pro_bootstrap_publication(
            lake_root=lake_root,
            staging_root=staging_root,
            approval=approval,
            trade_date=source.trade_date,
            layer=layer,
        )
        for layer in ("raw", "silver")
    )
    if source.source_empty:
        if any(
            intent is not None or complete is not None for intent, complete in records
        ):
            raise ValueError("原空源不应存在原两层发布记录")
        return None, None
    if any(
        complete is None
        or complete.source_complete_digest != source.source_complete_digest
        or complete.actual_rows != source.actual_rows
        for _, complete in records
    ):
        raise ValueError("原导入两层尚未完成或与完整日源数量不符")
    if records[1][0].raw_file_sha256 != records[0][1].actual_file_sha256:
        raise ValueError("原Silver未绑定原Raw")
    return records[0][1], records[1][1]


def _current_files(
    *,
    lake_root,
    staging_root,
    approval,
    source,
    raw_audit,
    silver_audit,
    current_publication,
    connection=None,
):
    original = _original_publications(
        lake_root=lake_root, staging_root=staging_root, approval=approval, source=source
    )
    paths = _targets(lake_root, source.trade_date)
    hashes = tuple(_observed_sha(p, connection=connection) for p in paths)
    if source.source_empty and current_publication is None:
        if any(hashes) or raw_audit is not None or silver_audit is not None:
            raise ValueError("首次空源不能借用已有业务文件或伪造audit")
        return 0, 0, None, None
    for layer, path, sha, audit in zip(
        ("raw", "silver"), paths, hashes, (raw_audit, silver_audit), strict=True
    ):
        if (
            not isinstance(audit, C.StkFactorProFileAudit)
            or not audit.passed
            or audit.trade_date != source.trade_date
            or audit.layer != layer
            or audit.path != path
            or sha is None
            or audit.file_sha256 != sha
        ):
            raise ValueError("当前两层正式文件与有效audit不符")
    if raw_audit.row_count != silver_audit.row_count:
        raise ValueError("当前Raw/Silver数量不一致")
    if current_publication is None:
        if (raw_audit, silver_audit) != tuple(r.audit for r in original):
            raise ValueError("首次导入audit不等于原两层完成事实")
    elif (
        current_publication.trade_date != source.trade_date
        or current_publication.contract_content_digest
        != approval.contract_content_digest
        or current_publication.processing_version != C.STK_FACTOR_PRO_PROCESSING_VERSION
        or (current_publication.raw_file_sha256, current_publication.silver_file_sha256)
        != hashes
        or current_publication.silver_source_raw_sha256 != hashes[0]
    ):
        raise ValueError("补数发布引用与日期/契约/两层文件/Raw来源不符")
    return raw_audit.row_count, silver_audit.row_count, *hashes


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


def _validate_codes(connection, path, *, day, count):
    table = _PREFIX + "detail"
    connection.execute(
        f"CREATE OR REPLACE TEMP TABLE {table} AS SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
    )
    with resource_cleanup(lambda: _drop(connection, (table,))):
        if _schema(connection, table) != _CODE_SCHEMA:
            raise ValueError("覆盖差集明细schema错误")
        observed, invalid, unique = connection.execute(
            f"SELECT count(*),count(*) FILTER (WHERE trade_date IS DISTINCT FROM ? OR ts_code IS NULL "
            f"OR NOT regexp_full_match(ts_code,'[0-9]{{6}}\\.(SH|SZ|BJ)')),count(DISTINCT (trade_date,ts_code)) FROM {table}",
            [day],
        ).fetchone()
        if observed != count or invalid or unique != count:
            raise ValueError("覆盖差集明细日期、代码、数量或唯一键不符")


def _write_codes(connection, *, staging_root, approval, day, digest, kind, count):
    if not count:
        return None, ()
    relative = f"coverage/{day.isoformat()}/input={digest}/{kind}-codes.parquet"
    path = operation_path(staging_root, approval, relative)
    relation = "stk_factor_pro_coverage_" + kind
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{uuid4().hex}.tmp")
    with resource_cleanup(lambda: temporary.unlink(missing_ok=True)):
        connection.execute(
            f"COPY (SELECT trade_date,ts_code FROM {relation} ORDER BY trade_date,ts_code) TO ? (FORMAT PARQUET)",
            [str(temporary)],
        )
        _validate_codes(connection, temporary, day=day, count=count)
        if path.exists():
            _validate_codes(connection, path, day=day, count=count)
            mismatch = connection.execute(
                f"SELECT count(*) FROM ((SELECT * FROM {read_parquet(path, hive_partitioning=False)} EXCEPT SELECT * FROM {relation}) "
                f"UNION ALL (SELECT * FROM {relation} EXCEPT SELECT * FROM {read_parquet(path, hive_partitioning=False)}))"
            ).fetchone()[0]
            if mismatch:
                raise ValueError("同一覆盖输入摘要已有不同差集")
        else:
            atomic_promote(temporary, path)
    sample = tuple(
        r[0]
        for r in connection.execute(
            f"SELECT ts_code FROM {relation} ORDER BY ts_code LIMIT 20"
        ).fetchall()
    )
    return C.StkFactorProBootstrapCodesRef(
        relative, factor_file_sha(path), count
    ), sample


def evaluate_stk_factor_pro_bootstrap_coverage_date(
    connection,
    *,
    lake_root,
    staging_root,
    approval,
    inputs,
    trade_date,
    source_complete,
    raw_audit,
    silver_audit,
    current_publication,
):
    digest, basis = _require_inputs(
        connection,
        lake_root=lake_root,
        staging_root=staging_root,
        approval=approval,
        inputs=inputs,
        trade_date=trade_date,
    )
    source = _source(staging_root, approval, trade_date, source_complete)
    if trade_date in inputs.closed_dates:
        raise ValueError("已确认休市有源属于冲突；休市空源只汇总分类，不生成覆盖记录")
    raw_rows, silver_rows, raw_sha, silver_sha = _current_files(
        lake_root=lake_root,
        staging_root=staging_root,
        approval=approval,
        source=source,
        raw_audit=raw_audit,
        silver_audit=silver_audit,
        current_publication=current_publication,
        connection=connection,
    )
    is_open = True if trade_date in inputs.open_dates else None
    input_digest = _date_digest(
        approval, digest, trade_date, source, (raw_sha, silver_sha), basis, is_open
    )
    previous = read_json(
        operation_path(
            staging_root, approval, f"coverage/{trade_date.isoformat()}/result.json"
        ),
        C.StkFactorProBootstrapDateCoverage,
    )
    if previous is not None and previous.input_digest == input_digest:
        _verify_result(
            lake_root=lake_root,
            staging_root=staging_root,
            approval=approval,
            result=previous,
            source=source,
            connection=connection,
        )
        if previous.current_publication == current_publication:
            return previous
        return replace(
            previous, current_publication=current_publication, evaluated_at=_now()
        )
    issues = next(
        ((k, r) for d, k, r in inputs.unknown_by_date if d == trade_date), ((), "")
    )
    unknown, reason = issues
    counts = None
    refs, samples = (None, None), ((), ())
    with resource_cleanup(lambda: _drop(connection, (*_DAILY, *_PURE_TABLES))):
        actual = _DAILY[2]
        if raw_sha is None:
            connection.execute(
                f"CREATE TEMP TABLE {actual} (trade_date DATE,ts_code VARCHAR)"
            )
        else:
            connection.execute(
                f"CREATE TEMP TABLE {actual} AS SELECT DISTINCT strptime(trade_date,'%Y%m%d')::DATE AS trade_date,ts_code FROM {read_parquet(_targets(lake_root, trade_date)[0], hive_partitioning=False)}"
            )
        physical = connection.execute(f"SELECT count(*) FROM {actual}").fetchone()[0]
        if not unknown:
            connection.execute(
                f"CREATE TEMP TABLE {_DAILY[0]} AS SELECT DISTINCT ?::DATE AS trade_date,ts_code FROM {_PREFIX}lifecycle WHERE list_date<=? AND (delist_date IS NULL OR ?<delist_date) AND (NOT ends_with(ts_code,'.BJ') OR ?>=CAST(? AS DATE))",
                [trade_date, trade_date, trade_date, trade_date, BJ_MARKET_OPEN_DATE],
            )
            connection.execute(
                f"CREATE TEMP TABLE {_DAILY[1]} AS SELECT DISTINCT trade_date,ts_code FROM {_SUSPEND} WHERE trade_date=? AND suspend_type='S' AND suspend_timing IS NULL",
                [trade_date],
            )
            counts = build_stk_factor_pro_coverage_keys(
                connection,
                target_trade_date=trade_date,
                listed_relation=_DAILY[0],
                full_suspend_relation=_DAILY[1],
                actual_relation=actual,
                identity_relation=_PREFIX + "identity",
            )
            reason = counts.reason
            if counts.expected_count is None:
                unknown = ("identity",)
            else:
                detail = tuple(
                    _write_codes(
                        connection,
                        staging_root=staging_root,
                        approval=approval,
                        day=trade_date,
                        digest=input_digest,
                        kind=k,
                        count=n,
                    )
                    for k, n in (
                        ("missing", counts.missing_count),
                        ("extra", counts.extra_count),
                    )
                )
                refs, samples = tuple(d[0] for d in detail), tuple(d[1] for d in detail)
        if not _basis_current(lake_root, basis, connection=connection) or tuple(
            _cached_sha(connection, p) for p in _targets(lake_root, trade_date)
        ) != (raw_sha, silver_sha):
            raise ValueError("统计时依据或正式文件发生变化，不保存过期结论")
        fields = {
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
        return C.StkFactorProBootstrapDateCoverage(
            record_version=1,
            operation_id=approval.operation_id,
            approval_digest=digest,
            trade_date=trade_date,
            source_rows=source.actual_rows,
            raw_rows=raw_rows,
            silver_rows=silver_rows,
            raw_physical_code_count=physical,
            source_complete_digest=source.source_complete_digest,
            raw_file_sha256=raw_sha,
            silver_file_sha256=silver_sha,
            import_complete=True,
            source_empty=source.source_empty,
            current_publication=current_publication,
            is_open=is_open,
            basis_files=basis,
            unknown_input_kinds=tuple(unknown),
            input_digest=input_digest,
            **fields,
            identity_unmapped_sample_codes=counts.identity_unmapped_sample_codes
            if counts
            else (),
            identity_ambiguous_sample_codes=counts.identity_ambiguous_sample_codes
            if counts
            else (),
            coverage_complete=(counts.missing_count == 0)
            if counts and counts.missing_count is not None
            else None,
            reason=reason or "覆盖依据不足，无法判断",
            missing_codes_ref=refs[0],
            extra_codes_ref=refs[1],
            missing_sample_codes=samples[0],
            extra_sample_codes=samples[1],
            evaluated_at=_now(),
        )


def _verify_result(
    *,
    lake_root,
    staging_root,
    approval,
    result,
    source=None,
    file_shas=None,
    connection=None,
    verify_basis=True,
):
    source = source or _source(staging_root, approval, result.trade_date)
    digest = approval_sha(staging_root, approval)
    if (
        result.operation_id != approval.operation_id
        or result.approval_digest != digest
        or result.source_complete_digest != source.source_complete_digest
        or result.source_rows != source.actual_rows
        or result.source_empty != source.source_empty
        or _date_digest(
            approval,
            digest,
            result.trade_date,
            source,
            (result.raw_file_sha256, result.silver_file_sha256),
            result.basis_files,
            result.is_open,
        )
        != result.input_digest
    ):
        raise ValueError("覆盖结果与原operation/来源/输入摘要不符")
    original = _original_publications(
        lake_root=lake_root, staging_root=staging_root, approval=approval, source=source
    )
    if result.current_publication is None:
        if (result.raw_rows, result.silver_rows) != (
            source.actual_rows,
            source.actual_rows,
        ):
            raise ValueError("原覆盖数量与忠实导入不符")
        if not source.source_empty and (
            result.raw_file_sha256,
            result.silver_file_sha256,
        ) != tuple(r.actual_file_sha256 for r in original):
            raise ValueError("原覆盖不对应原导入完成文件")
    if verify_basis and not _basis_current(
        lake_root, result.basis_files, file_shas, connection
    ):
        raise ValueError("覆盖依据身份已改变")
    if tuple(
        _observed_sha(p, file_shas, connection)
        for p in _targets(lake_root, result.trade_date)
    ) != (
        result.raw_file_sha256,
        result.silver_file_sha256,
    ):
        raise ValueError("覆盖结果不对应当前正式文件")
    if result.current_publication is not None and (
        result.current_publication.contract_content_digest
        != approval.contract_content_digest
        or result.current_publication.silver_source_raw_sha256 != result.raw_file_sha256
    ):
        raise ValueError("当前补数发布契约或Raw来源不符")
    for ref in (result.missing_codes_ref, result.extra_codes_ref):
        if (
            ref is not None
            and _observed_sha(
                operation_path(staging_root, approval, ref.relative_path),
                file_shas,
                connection,
            )
            != ref.file_sha256
        ):
            raise ValueError("覆盖差集明细身份不符")


def write_stk_factor_pro_bootstrap_coverage_date(
    connection,
    *,
    lake_root,
    staging_root,
    approval,
    result,
):
    _verify_result(
        lake_root=lake_root,
        staging_root=staging_root,
        approval=approval,
        result=result,
        connection=connection,
    )
    path = operation_path(
        staging_root, approval, f"coverage/{result.trade_date.isoformat()}/result.json"
    )
    if read_json(path, C.StkFactorProBootstrapDateCoverage) == result:
        return result
    for ref in (result.missing_codes_ref, result.extra_codes_ref):
        if ref is not None:
            _validate_codes(
                connection,
                operation_path(staging_root, approval, ref.relative_path),
                day=result.trade_date,
                count=ref.row_count,
            )
    _verify_result(
        lake_root=lake_root,
        staging_root=staging_root,
        approval=approval,
        result=result,
        connection=connection,
    )
    return write_json(
        path,
        result,
        mutable=True,
    )


def update_stk_factor_pro_bootstrap_after_publication(
    connection,
    *,
    lake_root,
    staging_root,
    approval,
    inputs,
    publication,
    raw_audit,
    silver_audit,
):
    day = publication.trade_date
    digest, basis = _require_inputs(
        connection,
        lake_root=lake_root,
        staging_root=staging_root,
        approval=approval,
        inputs=inputs,
        trade_date=day,
    )
    source = _source(staging_root, approval, day)
    _, _, raw_sha, silver_sha = _current_files(
        lake_root=lake_root,
        staging_root=staging_root,
        approval=approval,
        source=source,
        raw_audit=raw_audit,
        silver_audit=silver_audit,
        current_publication=publication,
        connection=connection,
    )
    expected = _date_digest(
        approval,
        digest,
        day,
        source,
        (raw_sha, silver_sha),
        basis,
        True if day in inputs.open_dates else None,
    )
    path = operation_path(
        staging_root, approval, f"coverage/{day.isoformat()}/result.json"
    )
    old = read_json(path, C.StkFactorProBootstrapDateCoverage)
    if old is not None and old.input_digest == expected:
        _verify_result(
            lake_root=lake_root,
            staging_root=staging_root,
            approval=approval,
            result=old,
            source=source,
            connection=connection,
        )
        if old.current_publication == publication:
            return old
        return write_stk_factor_pro_bootstrap_coverage_date(
            connection,
            lake_root=lake_root,
            staging_root=staging_root,
            approval=approval,
            result=replace(old, current_publication=publication, evaluated_at=_now()),
        )
    result = evaluate_stk_factor_pro_bootstrap_coverage_date(
        connection,
        lake_root=lake_root,
        staging_root=staging_root,
        approval=approval,
        inputs=inputs,
        trade_date=day,
        source_complete=source,
        raw_audit=raw_audit,
        silver_audit=silver_audit,
        current_publication=publication,
    )
    return write_stk_factor_pro_bootstrap_coverage_date(
        connection,
        lake_root=lake_root,
        staging_root=staging_root,
        approval=approval,
        result=result,
    )


def summarize_stk_factor_pro_bootstrap_coverage(
    *,
    lake_root,
    staging_root,
    approval,
    verified_import_dates,
    verified_current_dates,
    inputs,
):
    digest = approval_sha(staging_root, approval)
    natural = _days(
        approval.start_trade_date, approval.end_trade_date + timedelta(days=1)
    )
    if tuple(i.month for i in inputs) != approval.month_limits or any(
        i.operation_id != approval.operation_id
        or _month_digest(approval, digest, i) != i.input_digest
        for i in inputs
    ):
        raise ValueError("汇总月份必须完整对应本次批准，且摘要有效")
    for dates in (verified_import_dates, verified_current_dates):
        if (
            type(dates) is not tuple
            or dates != tuple(sorted(set(dates)))
            or not set(dates) <= set(natural)
        ):
            raise ValueError("汇总已核日期必须在批准范围内升序唯一")
    if not set(verified_current_dates) <= set(verified_import_dates):
        raise ValueError("当前日期必须属于原已完成导入日期")
    by_date = {d: i for i in inputs for d in i.natural_dates}
    file_shas = {}
    open_dates, closed_dates, calendar_unknown = [], [], []
    for day in natural:
        item = by_date[day]
        calendar = next(b for b in item.basis_files if b.kind == "calendar")
        if (
            not _basis_current(lake_root, (calendar,), file_shas)
            or day in item.calendar_unknown_dates
        ):
            calendar_unknown.append(day)
        elif day in item.open_dates:
            open_dates.append(day)
        else:
            closed_dates.append(day)
    originals = [0, 0, 0]
    current = [0, 0]
    source_empty, known, gaps, unverified, result_digests, unknown = (
        [],
        [],
        [],
        [],
        [],
        [],
    )
    totals = [0, 0, 0, 0, 0]
    for day in natural:
        item = by_date[day]
        if day not in verified_import_dates:
            if day not in closed_dates:
                kinds = ("calendar",) if day in calendar_unknown else ()
                unknown.append((day, kinds, "原日期导入尚未完成"))
            continue
        source = _source(staging_root, approval, day)
        raw, silver = _original_publications(
            lake_root=lake_root,
            staging_root=staging_root,
            approval=approval,
            source=source,
        )
        originals[0] += source.actual_rows
        originals[1] += raw.actual_rows if raw else 0
        originals[2] += silver.actual_rows if silver else 0
        if source.source_empty:
            source_empty.append(day)
        if day in closed_dates:
            if source.actual_rows:
                raise ValueError("已确认休市但原来源有数据")
            continue
        path = operation_path(
            staging_root, approval, f"coverage/{day.isoformat()}/result.json"
        )
        result = read_json(path, C.StkFactorProBootstrapDateCoverage)
        if result is not None:
            result_digests.append((day, factor_file_sha(path)))
        reason, kinds = "当前两层文件或发布依据未确认", ()
        valid = day in verified_current_dates and result is not None
        if valid:
            try:
                basis = tuple(
                    b
                    for b in item.basis_files
                    if b.trade_date is None or b.trade_date == day
                )
                kinds = tuple(
                    sorted(
                        {
                            b.kind
                            for b in basis
                            if b not in result.basis_files
                            or not _basis_current(lake_root, (b,), file_shas)
                        }
                    )
                )
                _verify_result(
                    lake_root=lake_root,
                    staging_root=staging_root,
                    approval=approval,
                    result=result,
                    source=source,
                    file_shas=file_shas,
                )
                basis = tuple(
                    b
                    for b in item.basis_files
                    if b.trade_date is None or b.trade_date == day
                )
                valid = basis == result.basis_files
                if not valid:
                    reason = "覆盖依据版本已改变，需要本地重新计算"
                    kinds = tuple(
                        sorted({b.kind for b in basis if b not in result.basis_files})
                    )
            except (ValueError, OSError) as error:
                valid, reason = False, str(error)
        if not valid:
            # Failed basis identity does not invalidate unchanged physical files.
            physical = result is not None and day in verified_current_dates
            if physical:
                try:
                    _verify_result(
                        lake_root=lake_root,
                        staging_root=staging_root,
                        approval=approval,
                        result=result,
                        source=source,
                        file_shas=file_shas,
                        verify_basis=False,
                    )
                except (ValueError, OSError):
                    physical = False
            if not physical:
                unverified.append(day)
            else:
                current[0] += result.raw_rows
                current[1] += result.silver_rows
            if day in calendar_unknown:
                kinds = tuple(sorted(set(kinds) | {"calendar"}))
            unknown.append((day, kinds, reason))
            continue
        current[0] += result.raw_rows
        current[1] += result.silver_rows
        if result.coverage_complete is None or day in calendar_unknown:
            unknown.append(
                (day, result.unknown_input_kinds or ("calendar",), result.reason)
            )
            continue
        known.append(day)
        if result.missing_count:
            gaps.append(day)
        for index, name in enumerate(
            (
                "expected_count",
                "actual_count",
                "matched_count",
                "missing_count",
                "extra_count",
            )
        ):
            totals[index] += getattr(result, name)
    pending = tuple(
        d for d in natural if d not in closed_dates and d not in verified_import_dates
    )
    determined = (
        not calendar_unknown
        and not pending
        and not unverified
        and set(open_dates) <= set(known)
    )
    result = C.StkFactorProBootstrapCoverageSummary(
        record_version=1,
        operation_id=approval.operation_id,
        approval_digest=digest,
        start_trade_date=approval.start_trade_date,
        end_trade_date=approval.end_trade_date,
        evaluated_at=_now(),
        known_open_dates=tuple(open_dates),
        known_closed_dates=tuple(closed_dates),
        calendar_unknown_dates=tuple(calendar_unknown),
        imported_dates=verified_import_dates,
        source_empty_dates=tuple(source_empty),
        import_pending_dates=pending,
        known_coverage_dates=tuple(known),
        coverage_unknown_dates=tuple(unknown),
        gap_dates=tuple(gaps),
        verified_source_rows=originals[0],
        verified_raw_rows=originals[1],
        verified_silver_rows=originals[2],
        current_raw_rows=None if pending or unverified else current[0],
        current_silver_rows=None if pending or unverified else current[1],
        current_files_unverified_dates=tuple(unverified),
        date_result_digests=tuple(result_digests),
        expected_count_known_dates=totals[0],
        actual_count_known_dates=totals[1],
        matched_count_known_dates=totals[2],
        missing_count_known_dates=totals[3],
        extra_count_known_dates=totals[4],
        all_coverage_determined=determined,
        total_missing_count=totals[3] if determined else None,
        all_expected_present=totals[3] == 0 if determined else None,
    )
    if any(_file_sha(path) != sha for path, sha in file_shas.items()):
        raise ValueError("覆盖汇总期间输入发生改变，请仅重算本地统计")
    return write_json(
        operation_path(staging_root, approval, "coverage/summary.json"),
        result,
        mutable=True,
    )
