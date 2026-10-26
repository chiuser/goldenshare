"""Explicit synthetic administrator approval and Prod DATE/float carriers (LLD 10)."""

from dataclasses import replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from orchestrator.defs.bootstrap.stk_factor_pro_bootstrap_records import (
    approval_sha,
    operation_path,
    write_json,
    write_stk_factor_pro_bootstrap_source_complete,
)
from orchestrator.defs.checks.stk_factor_pro import factor_file_sha
from orchestrator.defs.io.stk_factor_pro_candidates import (
    build_stk_factor_pro_raw_batch,
    write_stk_factor_pro_raw_fragment,
)
from orchestrator.defs.run_contracts import stk_factor_pro as C
from tests.stk_factor_pro_test_support import contract, row


def native_row(code="000001.SZ", day=date(2019, 10, 16), **values):
    original = row(code, day.strftime("%Y%m%d"), **values)
    return tuple(
        day if i == 1 else (float(value) if value is not None and i >= 2 else value)
        for i, value in enumerate(original)
    )


def approval_fixture(
    connection, tmp_path, *, counts=((date(2019, 10, 16), 1),), operation="bootstrap-a"
):
    # Counts/evidence are externally authored test approval, never created by executor.
    from orchestrator.defs.paths import stk_factor_pro_bootstrap_operation_root

    staging, lake = tmp_path / "staging", tmp_path / "lake"
    staging.mkdir(exist_ok=True)
    lake.mkdir(exist_ok=True)
    root = stk_factor_pro_bootstrap_operation_root(staging, operation)
    root.mkdir(parents=True)
    columns = tuple(
        (name, "text" if i == 0 else "date" if i == 1 else "double precision", i >= 2)
        for i, name in enumerate(C.STK_FACTOR_PRO_SOURCE_COLUMNS)
    )
    identity = C.StkFactorProSourceIdentity(
        "example.invalid",
        5432,
        "fixture",
        "raw_tushare",
        "stk_factor_pro",
        columns,
        contract().contract_content_digest,
    )
    identity_digest = C.stk_factor_pro_bootstrap_source_identity_digest(identity)
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE fixture_counts(trade_date DATE,row_count BIGINT)"
    )
    for d, n in counts:
        connection.execute("INSERT INTO fixture_counts VALUES (?,?)", [d, n])
    counts_path = root / "daily-counts.parquet"
    connection.execute("COPY fixture_counts TO ? (FORMAT PARQUET)", [str(counts_path)])
    sample = C.StkFactorProBootstrapSourceSample(
        1,
        operation,
        identity_digest,
        identity.contract_content_digest,
        counts[0][0],
        ("000001.SZ",),
        1,
        tuple(C.STK_FACTOR_PRO_SOURCE_COLUMNS),
        min(counts[0][1], 1),
        columns,
        True,
        now,
    )
    write_json(root / "source-sample.json", sample)
    evidence = C.StkFactorProBootstrapSourceEvidence(
        1,
        operation,
        identity,
        identity_digest,
        identity.contract_content_digest,
        counts[0][0],
        counts[-1][0],
        sum(n for _, n in counts),
        "daily-counts.parquet",
        factor_file_sha(counts_path),
        now - timedelta(days=1),
        now + timedelta(days=1),
        "synthetic source is static",
        now,
        "source-sample.json",
        factor_file_sha(root / "source-sample.json"),
    )
    write_json(root / "source-evidence.json", evidence)
    month_limits = []
    start = counts[0][0]
    end = counts[-1][0] + timedelta(days=1)
    while start < end:
        following = (
            date(start.year + 1, 1, 1)
            if start.month == 12
            else date(start.year, start.month + 1, 1)
        )
        stop = min(following, end)
        month_limits.append(
            C.StkFactorProBootstrapMonthLimit(
                start, stop, sum(n for d, n in counts if start <= d < stop)
            )
        )
        start = stop
    approval = C.StkFactorProBootstrapApproval(
        1,
        operation,
        counts[0][0],
        counts[-1][0],
        counts[-1][0],
        evidence.source_maintenance_start,
        evidence.source_maintenance_end,
        identity_digest,
        identity.contract_content_digest,
        "daily-counts.parquet",
        factor_file_sha(counts_path),
        "source-evidence.json",
        factor_file_sha(root / "source-evidence.json"),
        tuple(month_limits),
        30000,
    )
    write_json(root / "approval.json", approval)
    return lake, staging, approval, identity


def source_fixture(
    connection, *, staging_root, approval, rows, day=None, attempt="a" * 32
):
    from orchestrator.defs.checks.stk_factor_pro import factor_content_sha
    from orchestrator.defs.duckdb_sql import read_parquet

    day = day or approval.start_trade_date
    month = next(
        m for m in approval.month_limits if m.month_start <= day < m.month_end_exclusive
    )
    relative = f"source/month={month.month_start:%Y-%m}/attempt_id={attempt}/fragment-000001.parquet"
    path = operation_path(staging_root, approval, relative)
    refs = ()
    if rows:
        frame = build_stk_factor_pro_raw_batch(
            rows=rows,
            source_fields=C.STK_FACTOR_PRO_SOURCE_COLUMNS,
            source="prod_postgres",
            expected_dates=(day,),
        )
        fragment = write_stk_factor_pro_raw_fragment(
            connection=connection,
            frame=frame,
            candidate_path=path,
            expected_row_count=len(rows),
        )
        refs = (C.StkFactorProBootstrapFragmentRef(1, attempt, fragment),)
        connection.execute(
            f"CREATE OR REPLACE TEMP VIEW fixture_day_source AS SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
        )
        content = factor_content_sha(connection, "fixture_day_source")
        connection.execute("DROP VIEW fixture_day_source")
    else:
        import hashlib

        content = hashlib.sha256(b"").hexdigest()
    selected = tuple(
        month.month_start + timedelta(days=i)
        for i in range((month.month_end_exclusive - month.month_start).days)
    )
    source = C.StkFactorProBootstrapSourceComplete(
        1,
        approval.operation_id,
        approval_sha(staging_root, approval),
        approval.source_identity_digest,
        approval.contract_content_digest,
        approval.source_cutoff_trade_date,
        month.month_start,
        month.month_end_exclusive,
        attempt,
        C.stk_factor_pro_bootstrap_query_digest(
            approval, approval_sha(staging_root, approval), month, selected
        ),
        selected,
        month.row_upper_bound,
        day,
        len(rows),
        len(rows),
        refs,
        C.fragments_manifest_digest(refs),
        C.stk_factor_pro_schema_digest("raw"),
        content,
        1,
        "eof",
        None,
        not bool(rows),
        "0" * 64,
        datetime.now(ZoneInfo("Asia/Shanghai")),
    )
    source = replace(
        source,
        source_complete_digest=C.stk_factor_pro_bootstrap_source_complete_digest(
            source
        ),
    )
    return write_stk_factor_pro_bootstrap_source_complete(
        connection,
        staging_root=staging_root,
        approval=approval,
        record=source,
        check_space=check_test_space,
    )


def check_test_space(stage, *, path, rows=None, **facts):
    """Real temp-filesystem check; only full-operation planning is replaced.

    Entry integration tests use the real operation guard instead. This explicit
    seam does not prove cumulative budgets, which have independent literal tests.
    """
    from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_records as records

    number = rows if type(rows) is int else 0
    estimate = records.estimate_bootstrap_space(
        pending_source_rows_by_month=(),
        remaining_layer_rows=(),
        work_rows=(number, number),
        pending_fetch_rows=0,
        remaining_date_count=1,
    )
    directory = path if path.is_dir() else path.parent
    records.require_bootstrap_space(
        operation_id="isolated-bootstrap",
        stage=stage,
        estimate=estimate,
        staging_root=directory,
        temp_directory=directory,
    )
