"""Small independent coverage cases using real producer schemas and file audits.

Upstream schema and domains: run_contracts.asset_column_schemas; lifecycle,
identity and final-suspend producer/check modules. A/B/C are synthetic fixtures.
"""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from orchestrator.defs.asset_guards import stk_factor_pro_readiness as R
from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_coverage as B
from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_publication as P
from orchestrator.defs.bootstrap import stk_factor_pro_history as driver
from orchestrator.defs.bootstrap.stk_factor_pro_bootstrap_records import (
    operation_path,
)
from orchestrator.defs.checks.stk_factor_pro import (
    audit_stk_factor_pro_file,
    factor_file_sha,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.io.stk_factor_pro_candidates import (
    BOOTSTRAP_DAY_SOURCE,
    RAW_EXPECTED,
    build_stk_factor_pro_raw_batch,
)
from orchestrator.defs.paths import (
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
from tests.stk_factor_pro_bootstrap_test_support import (
    approval_fixture,
    bootstrap_date_results,
    check_test_space,
    native_row,
    source_fixture,
)
from tests.stk_factor_pro_test_support import connection
from tests.test_stk_factor_pro_bootstrap_publication import release_date_work

DAY = date(2019, 10, 16)
A, B_CODE, C_CODE = "000001.SZ", "600000.SH", "000002.SZ"
EMPTY_MIDDLE_COUNTS = (
    (DAY - timedelta(days=1), 1),
    (DAY, 0),
    (DAY + timedelta(days=1), 1),
)


def parquet(conn, path, schema, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn.execute("DROP TABLE IF EXISTS coverage_fixture")
    conn.execute(
        "CREATE TEMP TABLE coverage_fixture ("
        + ",".join(f"{c.name} {c.type}" for c in schema)
        + ")"
    )
    if rows:
        conn.executemany(
            "INSERT INTO coverage_fixture VALUES ("
            + ",".join("?" for _ in schema)
            + ")",
            rows,
        )
    conn.execute("COPY coverage_fixture TO ? (FORMAT PARQUET)", [str(path)])
    conn.execute("DROP TABLE coverage_fixture")


def upstream(
    conn,
    lake,
    days=(DAY,),
    *,
    codes=(A, B_CODE, C_CODE),
    suspensions=None,
    calendar=None,
    identities=None,
    life=None,
):
    parquet(
        conn,
        silver_trade_calendar_path(lake),
        SILVER_TRADE_CALENDAR_SCHEMA,
        calendar
        if calendar is not None
        else [("SSE", d, True, d - timedelta(days=1)) for d in days],
    )
    parquet(
        conn,
        silver_stock_lifecycle_path(lake),
        SILVER_STOCK_LIFECYCLE_SCHEMA,
        life
        if life is not None
        else [
            (
                c,
                c[:6],
                c,
                "SZSE" if c.endswith("SZ") else "SSE",
                None,
                "CNY",
                True,
                "L",
                date(2010, 1, 1),
                None,
            )
            for c in codes
        ],
    )
    parquet(
        conn,
        silver_stock_identity_map_path(lake),
        SILVER_STOCK_IDENTITY_MAP_SCHEMA,
        identities
        if identities is not None
        else [
            (
                c,
                c,
                date(2010, 1, 1),
                None,
                date(2010, 1, 1),
                None,
                "stock_lifecycle",
                "confirmed",
                None,
                datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
            for c in codes
        ],
    )
    for day in days:
        rows = (suspensions or {}).get(day, ())
        parquet(
            conn,
            silver_stock_suspend_daily_path(lake, day.isoformat()),
            SILVER_STOCK_SUSPEND_DAILY_SCHEMA,
            rows,
        )


def setup(
    conn,
    tmp_path,
    *,
    codes=(A, C_CODE),
    counts=None,
    days=(DAY,),
    source_day=None,
    known_records,
    date_results,
    before_prepare=None,
    **upstream_args,
):
    counts = counts or tuple((d, len(codes)) for d in days)
    lake, staging, approval, _ = approval_fixture(
        conn,
        tmp_path,
        counts=counts,
        known_records=known_records,
    )
    upstream(conn, lake, days, **upstream_args)
    source_day = source_day or days[0]
    source = source_fixture(
        conn,
        staging_root=staging,
        approval=approval,
        rows=tuple(native_row(c, day=source_day) for c in codes),
        day=source_day,
        known_records=known_records,
    )
    raw, silver = P.publish_bootstrap_date(
        conn,
        lake_root=lake,
        staging_root=staging,
        approval=approval,
        source_complete=source,
        source_record_sha256=known_records[
            operation_path(
                staging,
                approval,
                f"source/dates/{source.trade_date}/source-complete.json",
            )
        ][1],
        source_relation=BOOTSTRAP_DAY_SOURCE,
        before_publish=lambda: None,
        check_space=check_test_space,
        known_records=known_records,
        date_results=bootstrap_date_results(date_results, source),
    )
    if before_prepare is not None:
        before_prepare(conn, lake)
    basis_inputs = {"files": {}, "months": {}, "active_month": None}
    inputs = B.prepare_stk_factor_pro_bootstrap_coverage_month(
        conn,
        lake_root=lake,
        staging_root=staging,
        approval=approval,
        month=approval.month_limits[0],
        basis_inputs=basis_inputs,
        known_records=known_records,
    )
    natural_dates = tuple(day for day, _ in counts)
    totals = B.new_stk_factor_pro_bootstrap_coverage_totals(natural_dates=natural_dates)
    for day in natural_dates:
        date_results[day] = driver._classify_date(
            conn,
            lake_root=lake,
            staging_root=staging,
            approval=approval,
            day=day,
            trusted={},
            known_records=known_records,
        )
        B.refresh_stk_factor_pro_bootstrap_date_contribution(
            trade_date=day,
            entry=date_results[day],
            totals=totals,
            is_open=True
            if day in inputs.open_dates
            else False
            if day in inputs.closed_dates
            else None,
            approved_rows=dict(counts)[day],
        )
    summary_path = operation_path(staging, approval, "coverage/summary.json")
    previous_summary = B.read_json(
        summary_path,
        C.StkFactorProBootstrapCoverageSummary,
        known_records=known_records,
    )
    return {
        "lake_root": lake,
        "staging_root": staging,
        "approval": approval,
        "inputs": inputs,
        "trade_date": source_day,
        "source_complete": source,
        "raw_audit": raw,
        "silver_audit": silver,
        "current_publication": None,
        "_raw_relation": None if raw is None else RAW_EXPECTED,
        "_diagnostic_run": None,
        "_approval_digest": known_records[
            operation_path(staging, approval, "approval.json")
        ][1],
        "_date_results": date_results,
        "_totals": totals,
        "_basis_inputs": basis_inputs,
        "_approved_counts": dict(counts),
        "_previous_summary": previous_summary,
        "_previous_summary_digest": known_records[summary_path][1],
    }


def calculate(conn, args, *, known_records):
    entry = args["_date_results"][args["trade_date"]]
    prepared = driver._prepare_bootstrap_date_coverage(
        lake_root=args["lake_root"],
        approval=args["approval"],
        approval_digest=args["_approval_digest"],
        inputs=args["inputs"],
        basis_inputs=args["_basis_inputs"],
        source=args["source_complete"],
        raw=args["raw_audit"],
        silver=args["silver_audit"],
        publication=args["current_publication"],
        date_results=args["_date_results"],
        known_records=known_records,
    )
    calculated = (
        driver._bootstrap_previous_calculation(entry["persisted_result"])
        if entry["coverage_record_current"]
        else B.compute_stk_factor_pro_bootstrap_coverage_date(
            conn,
            **{k: args[k] for k in ("lake_root", "staging_root", "approval")},
            prepared=prepared,
            raw_relation=args["_raw_relation"],
            diagnostic_run=args["_diagnostic_run"],
            input_digest=entry["coverage_input_digest"],
            check_space=check_test_space,
            known_records=known_records,
        )
    )
    result = B.evaluate_stk_factor_pro_bootstrap_coverage_date(
        prepared=prepared,
        calculated=calculated,
        approval_digest=args["_approval_digest"],
        input_digest=entry["coverage_input_digest"],
        source_complete=args["source_complete"],
        current_publication=args["current_publication"],
        previous_result=entry["persisted_result"],
    )
    entry["computed_result"] = result
    args["_prepared"] = prepared
    return result


def save(conn, args, *, known_records):
    entry = args["_date_results"][args["trade_date"]]
    result = calculate(conn, args, known_records=known_records)
    result = B.write_stk_factor_pro_bootstrap_coverage_date(
        conn,
        **{k: args[k] for k in ("lake_root", "staging_root", "approval")},
        result=result,
        previous_result=entry["persisted_result"],
        previous_result_digest=entry["persisted_result_digest"],
        date_results=args["_date_results"],
        check_space=check_test_space,
        known_records=known_records,
    )[0]
    day = args["trade_date"]
    B.refresh_stk_factor_pro_bootstrap_date_contribution(
        trade_date=day,
        entry=entry,
        totals=args["_totals"],
        is_open=True
        if day in args["inputs"].open_dates
        else False
        if day in args["inputs"].closed_dates
        else None,
        approved_rows=args["_approved_counts"][day],
    )
    return result


def update(conn, args, publication, result, *, known_records):
    entry = args["_date_results"][args["trade_date"]]
    value = B.update_stk_factor_pro_bootstrap_after_publication(
        conn,
        **{
            k: args[k]
            for k in (
                "lake_root",
                "staging_root",
                "approval",
            )
        },
        result=result,
        previous_result=entry["persisted_result"],
        previous_result_digest=entry["persisted_result_digest"],
        date_results=args["_date_results"],
        check_space=check_test_space,
        known_records=known_records,
    )[0]
    day = args["trade_date"]
    B.refresh_stk_factor_pro_bootstrap_date_contribution(
        trade_date=day,
        entry=entry,
        totals=args["_totals"],
        is_open=True
        if day in args["inputs"].open_dates
        else False
        if day in args["inputs"].closed_dates
        else None,
        approved_rows=args["_approved_counts"][day],
    )
    return value


def summary(args, *, known_records):
    result, digest = B.summarize_stk_factor_pro_bootstrap_coverage(
        **{k: args[k] for k in ("staging_root", "approval")},
        approval_digest=args["_approval_digest"],
        totals=args["_totals"],
        previous_summary=args["_previous_summary"],
        previous_summary_digest=args["_previous_summary_digest"],
        check_space=check_test_space,
        known_records=known_records,
    )
    args["_previous_summary"], args["_previous_summary_digest"] = result, digest
    return result


def initialize_coverage_context(conn, args, *, known_records, trusted):
    """Use the real controller's initial classification, including known events."""
    basis_inputs = {"files": {}, "months": {}, "active_month": None}
    inputs = B.prepare_stk_factor_pro_bootstrap_coverage_month(
        conn,
        **{k: args[k] for k in ("lake_root", "staging_root", "approval")},
        month=args["approval"].month_limits[0],
        basis_inputs=basis_inputs,
        known_records=known_records,
    )
    dates = tuple(args["_approved_counts"])
    date_results = {}
    totals = B.new_stk_factor_pro_bootstrap_coverage_totals(natural_dates=dates)
    for day in dates:
        entry = date_results[day] = driver._classify_date(
            conn,
            **{k: args[k] for k in ("lake_root", "staging_root", "approval")},
            day=day,
            trusted=trusted,
            known_records=known_records,
        )
        B.refresh_stk_factor_pro_bootstrap_date_contribution(
            trade_date=day,
            entry=entry,
            totals=totals,
            is_open=True
            if day in inputs.open_dates
            else False
            if day in inputs.closed_dates
            else None,
            approved_rows=args["_approved_counts"][day],
        )
    summary_path = operation_path(
        args["staging_root"], args["approval"], "coverage/summary.json"
    )
    previous_summary = B.read_json(
        summary_path,
        C.StkFactorProBootstrapCoverageSummary,
        known_records=known_records,
    )
    args.update(
        inputs=inputs,
        source_complete=date_results[args["trade_date"]]["source_complete"],
        _basis_inputs=basis_inputs,
        _date_results=date_results,
        _totals=totals,
        _previous_summary=previous_summary,
        _previous_summary_digest=known_records[summary_path][1],
    )
    return known_records


def reload_coverage_context(conn, args):
    """A new test task first loads the same persistent inputs and date facts."""
    release_date_work(conn, include_source=True)
    B.release_stk_factor_pro_bootstrap_coverage_inputs(
        conn, basis_inputs=args["_basis_inputs"]
    )
    known_records = initialize_coverage_context(
        conn, args, known_records={}, trusted={}
    )
    args["_raw_relation"] = None
    date_results = args["_date_results"]
    current = date_results[args["trade_date"]]
    if current["current_files_verified"] and current["raw_audit"] is not None:
        conn.execute(
            f"CREATE TEMP TABLE {RAW_EXPECTED} AS SELECT ts_code,trade_date FROM {read_parquet(current['raw_audit'].path, hive_partitioning=False)}"
        )
        args["_raw_relation"] = RAW_EXPECTED
    return known_records


def test_literal_missing_extra_details_and_summary(tmp_path):
    date_results = {}
    known_records = {}
    with connection(tmp_path) as conn:
        args = setup(
            conn,
            tmp_path,
            suspensions={DAY: ((C_CODE, DAY, None, "S"),)},
            known_records=known_records,
            date_results=date_results,
        )
        result = save(conn, args, known_records=known_records)
        assert (
            result.expected_count,
            result.actual_count,
            result.matched_count,
            result.missing_count,
            result.extra_count,
        ) == (2, 2, 1, 1, 1)
        assert result.missing_sample_codes == (B_CODE,)
        assert result.extra_sample_codes == (C_CODE,)
        for ref, code in (
            (result.missing_codes_ref, B_CODE),
            (result.extra_codes_ref, C_CODE),
        ):
            path = operation_path(
                args["staging_root"], args["approval"], ref.relative_path
            )
            assert ref.creator_run_id is None and ref.row_count == 1
            assert [
                (name, kind)
                for name, kind, *_ in conn.execute(
                    "DESCRIBE SELECT * FROM read_parquet(?,hive_partitioning=false)",
                    [str(path)],
                ).fetchall()
            ] == [("ts_code", "VARCHAR"), ("trade_date", "DATE")]
            assert conn.execute(
                "SELECT trade_date,ts_code FROM read_parquet(?)", [str(path)]
            ).fetchall() == [(DAY, code)]
        report = summary(args, known_records=known_records)
        assert report.total_missing_count == 1 and report.all_expected_present is False
        assert report.verified_source_rows == report.current_raw_rows == 2
        assert report.import_pending_dates == ()
        assert (
            conn.execute(
                "SELECT table_name FROM duckdb_tables() WHERE table_name LIKE 'stk_factor_pro_coverage_%'"
            ).fetchall()
            == []
        )


@pytest.mark.parametrize("target_delta", [0, 1])
def test_nonzero_diagnostic_saved_once_in_run_t_or_operation_history(
    tmp_path, monkeypatch, target_delta
):
    from collections import Counter

    from orchestrator.defs.checks import stk_factor_pro as checks
    from orchestrator.defs.paths import stk_factor_pro_run_staging_root

    known_records, date_results, costs = {}, {}, Counter()
    with connection(tmp_path) as conn:
        args = setup(
            conn, tmp_path, known_records=known_records, date_results=date_results
        )
        target = DAY + timedelta(days=target_delta)
        run = C.RunIdentity(
            "coverage-run",
            None,
            target,
            target,
            target - timedelta(days=1),
            "bootstrap_supplement",
            None,
            None,
            None,
        )
        args["_diagnostic_run"] = run
        original_sha = checks.factor_file_sha

        def sha(path):
            if "missing-codes.parquet" in str(path) or "extra-codes.parquet" in str(
                path
            ):
                costs["diagnostic_sha"] += 1
            return original_sha(path)

        class DiagnosticReads:
            def __getattr__(self, key):
                return getattr(conn, key)

            def execute(self, query, parameters=None):
                text = str(query)
                if "read_parquet" in text.lower() and (
                    "missing-codes.parquet" in text + repr(parameters)
                    or "extra-codes.parquet" in text + repr(parameters)
                ):
                    costs["diagnostic_reads"] += text.lower().count("read_parquet")
                return (
                    conn.execute(query)
                    if parameters is None
                    else conn.execute(query, parameters)
                )

        monkeypatch.setattr(checks, "factor_file_sha", sha)
        result = save(DiagnosticReads(), args, known_records=known_records)
        assert (
            result.expected_count,
            result.actual_count,
            result.missing_count,
            result.extra_count,
        ) == (3, 2, 1, 0)
        ref = result.missing_codes_ref
        assert ref.row_count == 1 and result.extra_codes_ref is None
        assert costs == {"diagnostic_reads": 1, "diagnostic_sha": 1}
        run_root = stk_factor_pro_run_staging_root(
            args["staging_root"], run.creator_run_id, target.isoformat()
        )
        if target_delta == 0:
            assert ref.creator_run_id == run.creator_run_id
            path = run_root / ref.relative_path
            assert ref.relative_path == "diagnostics/day-missing-codes.parquet"
            assert not list(
                operation_path(
                    args["staging_root"], args["approval"], f"coverage/{DAY}"
                ).glob("input=*/*-codes.parquet")
            )
        else:
            assert ref.creator_run_id is None and not run_root.exists()
            assert ref.relative_path.startswith(f"coverage/{DAY}/input=")
            path = operation_path(
                args["staging_root"], args["approval"], ref.relative_path
            )
        assert conn.execute(
            "SELECT ts_code,trade_date FROM read_parquet(?,hive_partitioning=false)",
            [str(path)],
        ).fetchall() == [(B_CODE, DAY)]


@pytest.mark.parametrize("symlink_parent", [False, True])
def test_run_diagnostic_first_reader_reuses_facts_and_rejects_symlink_parent(
    tmp_path, monkeypatch, symlink_parent
):
    from collections import Counter
    from shutil import copyfile

    from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_records as records
    from orchestrator.defs.checks import stk_factor_pro as checks
    from orchestrator.defs.paths import stk_factor_pro_run_staging_root
    from tests.test_stk_factor_pro_bootstrap_process import CountingConnection

    known_records, date_results = {}, {}
    with connection(tmp_path) as conn:
        args = setup(
            conn, tmp_path, known_records=known_records, date_results=date_results
        )
        run = C.RunIdentity(
            "coverage-first-reader",
            None,
            DAY,
            DAY,
            DAY - timedelta(days=1),
            "bootstrap_supplement",
            None,
            None,
            None,
        )
        args["_diagnostic_run"] = run
        saved = save(conn, args, known_records=known_records)
        run_root = stk_factor_pro_run_staging_root(
            args["staging_root"], run.creator_run_id, DAY.isoformat()
        )
        path = run_root / saved.missing_codes_ref.relative_path
        release_date_work(conn, include_source=True)
        B.release_stk_factor_pro_bootstrap_coverage_inputs(
            conn, basis_inputs=args["_basis_inputs"]
        )
        if symlink_parent:
            outside = tmp_path / "outside-run"
            outside.mkdir()
            copyfile(path, outside / path.name)
            path.parent.rename(run_root / "retained-diagnostics")
            path.parent.symlink_to(outside, target_is_directory=True)
        known_records = {}
        source = records.read_stk_factor_pro_bootstrap_source_complete(
            conn,
            **{k: args[k] for k in ("staging_root", "approval")},
            trade_date=DAY,
            known_records=known_records,
        )
        digest = known_records[
            operation_path(args["staging_root"], args["approval"], "approval.json")
        ][1]
        costs = Counter()
        original_sha = checks.factor_file_sha

        def sha(value):
            if "missing-codes.parquet" in str(value):
                costs["diagnostic_sha"] += 1
            return original_sha(value)

        monkeypatch.setattr(checks, "factor_file_sha", sha)

        def first_reader():
            return B.read_stk_factor_pro_bootstrap_coverage_date(
                CountingConnection(conn, costs),
                **{k: args[k] for k in ("staging_root", "approval")},
                approval_digest=digest,
                source_complete=source,
                trade_date=DAY,
                known_records=known_records,
            )

        if symlink_parent:
            with pytest.raises(ValueError, match="符号链接"):
                first_reader()
            assert costs["diagnostic_parquet_sql"] == costs["diagnostic_sha"] == 0
        else:
            first = first_reader()
            assert first == saved
            assert costs["diagnostic_parquet_sql"] == costs["diagnostic_sha"] == 1
            before = dict(costs)
            assert first_reader() is first and dict(costs) == before
        assert (
            conn.execute(
                "SELECT table_name FROM duckdb_tables() WHERE temporary "
                "AND (starts_with(table_name,'stk_factor_pro_') OR starts_with(table_name,'stk_factor_bootstrap_coverage_'))"
            ).fetchall()
            == []
        )


@pytest.mark.parametrize("timing", ["09:30-10:00", "source-defined-nonempty"])
def test_intraday_not_deducted_or_invented_timing_regex(tmp_path, timing):
    date_results = {}
    known_records = {}
    with connection(tmp_path) as conn:
        args = setup(
            conn,
            tmp_path,
            suspensions={DAY: ((C_CODE, DAY, timing, "S"),)},
            known_records=known_records,
            date_results=date_results,
        )
        result = save(conn, args, known_records=known_records)
        assert (
            result.expected_count,
            result.actual_count,
            result.missing_count,
            result.extra_count,
        ) == (3, 2, 1, 0)


@pytest.mark.parametrize(
    "bad", ["missing", "wrong_date", "blank_timing", "duplicate", "wrong_schema"]
)
def test_bad_suspend_unknown_keeps_published_business_files(tmp_path, bad):
    date_results = {}
    known_records = {}

    def bad_first_input(conn, lake):
        path = silver_stock_suspend_daily_path(lake, DAY.isoformat())
        if bad == "missing":
            path.unlink()
        elif bad == "wrong_schema":
            parquet(conn, path, SILVER_TRADE_CALENDAR_SCHEMA, ())
        else:
            row = (
                C_CODE,
                DAY + timedelta(days=1) if bad == "wrong_date" else DAY,
                " " if bad == "blank_timing" else None,
                "S",
            )
            parquet(
                conn,
                path,
                SILVER_STOCK_SUSPEND_DAILY_SCHEMA,
                (row, row) if bad == "duplicate" else (row,),
            )

    with connection(tmp_path) as conn:
        args = setup(
            conn,
            tmp_path,
            known_records=known_records,
            date_results=date_results,
            before_prepare=bad_first_input,
        )
        result = save(conn, args, known_records=known_records)
        assert result.coverage_complete is None and result.expected_count is None
        assert result.unknown_input_kinds == ("suspend",)
        assert (
            result.raw_rows == 2
            and factor_file_sha(args["raw_audit"].path) == result.raw_file_sha256
        )
        assert summary(args, known_records=known_records).total_missing_count is None


def test_valid_empty_suspend_and_source_empty_are_explicit(tmp_path):
    date_results = {}
    known_records = {}
    with connection(tmp_path) as conn:
        args = setup(
            conn,
            tmp_path,
            codes=(),
            counts=EMPTY_MIDDLE_COUNTS,
            known_records=known_records,
            date_results=date_results,
        )
        result = save(conn, args, known_records=known_records)
        assert (
            result.source_rows,
            result.raw_rows,
            result.raw_physical_code_count,
        ) == (0, 0, 0)
        assert (
            result.source_empty and result.expected_count == result.missing_count == 3
        )
        assert result.actual_count == 0 and result.raw_file_sha256 is None
        report = summary(args, known_records=known_records)
        assert (
            report.source_empty_dates == (DAY,)
            and report.missing_count_known_dates == 3
        )
        assert report.total_missing_count is None  # Other approved dates not imported.


@pytest.mark.parametrize(
    "rows",
    [
        (),
        (("SSE", DAY, None, DAY - timedelta(days=1)),),
        (("SSE", DAY, True, DAY - timedelta(days=1)),) * 2,
    ],
)
def test_calendar_unknown_not_fake_closed_or_zero(tmp_path, rows):
    date_results = {}
    known_records = {}
    with connection(tmp_path) as conn:
        args = setup(
            conn,
            tmp_path,
            calendar=rows,
            known_records=known_records,
            date_results=date_results,
        )
        result = save(conn, args, known_records=known_records)
        assert (
            result.is_open is None
            and result.raw_rows == 2
            and result.coverage_complete is None
        )
        assert "calendar" in result.unknown_input_kinds
        assert summary(args, known_records=known_records).calendar_unknown_dates == (
            DAY,
        )


def test_one_calendar_gap_does_not_invalidate_other_day(tmp_path):
    date_results = {}
    known_records = {}
    days = (DAY, DAY + timedelta(days=1))
    with connection(tmp_path) as conn:
        args = setup(
            conn,
            tmp_path,
            days=days,
            calendar=(("SSE", DAY, True, DAY - timedelta(days=1)),),
            known_records=known_records,
            date_results=date_results,
        )
        assert args["inputs"].open_dates == (DAY,)
        assert args["inputs"].calendar_unknown_dates == (days[1],)
        result = save(conn, args, known_records=known_records)
        assert result.expected_count == 3
        report = summary(args, known_records=known_records)
        assert report.known_coverage_dates == (
            DAY,
        ) and report.import_pending_dates == (days[1],)
        assert report.total_missing_count is None and report.current_raw_rows is None


def test_known_closed_rejects_coverage_but_empty_not_pending(tmp_path):
    date_results = {}
    known_records = {}
    with connection(tmp_path) as conn:
        args = setup(
            conn,
            tmp_path,
            codes=(),
            counts=EMPTY_MIDDLE_COUNTS,
            calendar=(("SSE", DAY, False, DAY - timedelta(days=1)),),
            known_records=known_records,
            date_results=date_results,
        )
        with pytest.raises(ValueError, match="休市"):
            save(conn, args, known_records=known_records)
        report = summary(args, known_records=known_records)
        assert DAY not in report.import_pending_dates and report.known_closed_dates == (
            DAY,
        )
        assert report.all_expected_present is None


def test_known_closed_positive_source_conflict(tmp_path):
    date_results = {}
    known_records = {}
    with connection(tmp_path) as conn:
        args = setup(
            conn,
            tmp_path,
            calendar=(("SSE", DAY, False, DAY - timedelta(days=1)),),
            known_records=known_records,
            date_results=date_results,
        )
        with pytest.raises(ValueError, match="休市"):
            save(conn, args, known_records=known_records)
        assert not operation_path(
            args["staging_root"], args["approval"], f"coverage/{DAY}/result.json"
        ).exists()


def test_unknown_identity_and_physical_rule_rejects(tmp_path):
    date_results = {}
    known_records = {}
    with connection(tmp_path) as conn:
        identities = [
            (
                c,
                c,
                date(2010, 1, 1),
                None,
                date(2010, 1, 1),
                None,
                "stock_lifecycle",
                "confirmed",
                None,
                datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
            for c in (A, B_CODE)
        ]
        args = setup(
            conn,
            tmp_path,
            identities=identities,
            known_records=known_records,
            date_results=date_results,
        )
        result = save(conn, args, known_records=known_records)
        assert (
            result.identity_unmapped_count == 1
            and result.identity_unmapped_sample_codes == (C_CODE,)
        )
        assert (
            result.unknown_input_kinds == ("identity",) and result.missing_count is None
        )


def test_aliases_map_once_and_raw_physical_rows_not_changed(tmp_path):
    date_results = {}
    known_records = {}
    latest, alias = "920001.BJ", "830001.BJ"
    day = date(2026, 10, 16)
    with connection(tmp_path) as conn:
        identities = [
            (
                latest,
                c,
                date(2020, 1, 1),
                None,
                date(2020, 1, 1),
                None,
                "stock_lifecycle",
                "confirmed",
                None,
                datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
            for c in (latest, alias)
        ]
        args = setup(
            conn,
            tmp_path,
            codes=(latest, alias),
            days=(day,),
            identities=identities,
            life=[
                (
                    latest,
                    latest[:6],
                    latest,
                    "BSE",
                    None,
                    "CNY",
                    True,
                    "L",
                    date(2020, 1, 1),
                    None,
                )
            ],
            known_records=known_records,
            date_results=date_results,
        )
        result = save(conn, args, known_records=known_records)
        assert (
            result.source_rows,
            result.raw_rows,
            result.raw_physical_code_count,
        ) == (2, 2, 2)
        assert (result.expected_count, result.actual_count, result.missing_count) == (
            1,
            1,
            0,
        )


def test_invalid_audit_and_partial_two_layer_never_coverage(tmp_path):
    date_results = {}
    known_records = {}
    with connection(tmp_path) as conn:
        args = setup(
            conn, tmp_path, known_records=known_records, date_results=date_results
        )
        args["silver_audit"] = None
        with pytest.raises(ValueError, match="audit"):
            save(conn, args, known_records=known_records)
        assert not operation_path(
            args["staging_root"], args["approval"], "coverage/2019-10-16/result.json"
        ).exists()


def test_result_write_failure_preserves_files_and_no_summary_success(
    tmp_path, monkeypatch
):
    date_results = {}
    known_records = {}
    with connection(tmp_path) as conn:
        args = setup(
            conn, tmp_path, known_records=known_records, date_results=date_results
        )
        before = factor_file_sha(args["raw_audit"].path)
        monkeypatch.setattr(
            B,
            "write_json",
            lambda *_a, **_k: (_ for _ in ()).throw(OSError("save result")),
        )
        with pytest.raises(OSError, match="save result"):
            save(conn, args, known_records=known_records)
        assert factor_file_sha(args["raw_audit"].path) == before
        assert not operation_path(
            args["staging_root"], args["approval"], "coverage/2019-10-16/result.json"
        ).exists()
        assert (
            conn.execute(
                "SELECT table_name FROM duckdb_tables() WHERE table_name LIKE 'stk_factor_pro_coverage_%'"
            ).fetchall()
            == []
        )


def test_stale_basis_requires_local_reprepare_only(tmp_path):
    date_results = {}
    known_records = {}
    with connection(tmp_path) as conn:
        args = setup(
            conn, tmp_path, known_records=known_records, date_results=date_results
        )
        save(conn, args, known_records=known_records)
        path = silver_stock_suspend_daily_path(args["lake_root"], DAY.isoformat())
        parquet(
            conn, path, SILVER_STOCK_SUSPEND_DAILY_SCHEMA, ((C_CODE, DAY, None, "S"),)
        )
        with pytest.raises(ValueError, match="改变"):
            save(conn, args, known_records=known_records)
        known_records = reload_coverage_context(conn, args)
        result = save(conn, args, known_records=known_records)
        assert (result.missing_count, result.extra_count) == (1, 1)
        assert summary(args, known_records=known_records).total_missing_count == 1


def test_changed_current_file_stops_at_control_identity_boundary(tmp_path):
    date_results = {}
    known_records = {}
    with connection(tmp_path) as conn:
        args = setup(
            conn, tmp_path, known_records=known_records, date_results=date_results
        )
        result = save(conn, args, known_records=known_records)
        args["silver_audit"].path.write_bytes(b"changed")
        with pytest.raises(ValueError, match="改变"):
            calculate(conn, args, known_records=known_records)
        assert args["_date_results"][DAY]["persisted_result"] is result


def test_update_same_publication_reuses_counts_no_key_scan(tmp_path, monkeypatch):
    date_results = {}
    known_records = {}
    with connection(tmp_path) as conn:
        args = setup(
            conn, tmp_path, known_records=known_records, date_results=date_results
        )
        result = save(conn, args, known_records=known_records)
        publication = C.StkFactorProBootstrapCurrentPublication(
            "run-b",
            DAY,
            1,
            2,
            3,
            4,
            result.raw_file_sha256,
            result.silver_file_sha256,
            result.raw_file_sha256,
            args["approval"].contract_content_digest,
            "1",
        )
        monkeypatch.setattr(
            B,
            "evaluate_stk_factor_pro_bootstrap_coverage_date",
            lambda *_a, **_k: pytest.fail(
                "unchanged bytes and basis must not recalculate keys"
            ),
        )
        new_result = replace(result, current_publication=publication)
        updated = update(
            conn, args, publication, new_result, known_records=known_records
        )
        assert updated.current_publication == publication and updated.missing_count == 1
        assert (
            update(conn, args, publication, updated, known_records=known_records)
            == updated
        )
        assert summary(args, known_records=known_records).verified_source_rows == 2


def supplement_audits(conn, args, codes, *, known_records):
    """Real temporary files and full audits; event discovery is outside this unit test."""
    day = args["trade_date"]
    frame = build_stk_factor_pro_raw_batch(
        rows=tuple(native_row(c, day=day) for c in codes),
        source_fields=C.STK_FACTOR_PRO_SOURCE_COLUMNS,
        source="prod_postgres",
        expected_dates=(day,),
    )
    conn.register("coverage_supplement_input", frame)
    try:
        projection = ",".join(
            f'CAST("{name}" AS {kind}) AS "{name}"'
            for name, kind in C.STK_FACTOR_PRO_RAW_COLUMN_TYPES.items()
        )
        conn.execute(
            f"CREATE TEMP TABLE {RAW_EXPECTED} AS SELECT {projection} FROM coverage_supplement_input"
        )
        conn.execute(
            f"CREATE TEMP TABLE coverage_supplement_silver AS SELECT * REPLACE (strptime(trade_date,'%Y%m%d')::DATE AS trade_date) FROM {RAW_EXPECTED}"
        )
        audits = []
        for layer, path in zip(
            ("raw", "silver"), B._targets(args["lake_root"], day), strict=True
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            relation = RAW_EXPECTED if layer == "raw" else "coverage_supplement_silver"
            conn.execute(
                f"COPY (SELECT * FROM {relation} ORDER BY ts_code) TO ? (FORMAT PARQUET)",
                [str(path)],
            )
            audits.append(
                audit_stk_factor_pro_file(
                    conn,
                    path=path,
                    expected_relation=relation,
                    target_trade_date=day,
                    layer=layer,
                    known_records=known_records,
                )
            )
        # Independent literal values ensure business data did not change shape.
        assert conn.execute(
            f"SELECT ts_code,trade_date,macd_bfq,pe FROM {read_parquet(audits[1].path, hive_partitioning=False)} ORDER BY ts_code"
        ).fetchall() == [(c, day, -1.25, None) for c in sorted(codes)]
        return tuple(audits)
    finally:
        conn.unregister("coverage_supplement_input")
        conn.execute("DROP TABLE IF EXISTS coverage_supplement_silver")


@pytest.mark.parametrize("original_codes", [(A, C_CODE), ()])
def test_supplement_current_counts_update_original_facts_unchanged(
    tmp_path, original_codes
):
    date_results = {}
    known_records = {}
    with connection(tmp_path) as conn:
        args = setup(
            conn,
            tmp_path,
            codes=original_codes,
            counts=EMPTY_MIDDLE_COUNTS if not original_codes else None,
            days=tuple(d for d, _ in EMPTY_MIDDLE_COUNTS)
            if not original_codes
            else (DAY,),
            source_day=DAY,
            known_records=known_records,
            date_results=date_results,
        )
        if not original_codes:
            days = tuple(d for d, _ in EMPTY_MIDDLE_COUNTS)
            for d in (days[0], days[2]):
                release_date_work(conn, include_source=True)
                source = source_fixture(
                    conn,
                    staging_root=args["staging_root"],
                    approval=args["approval"],
                    rows=(native_row(A, day=d),),
                    day=d,
                    attempt=d.strftime("%Y%m%d") + "b" * 24,
                    known_records=known_records,
                )
                raw, silver = P.publish_bootstrap_date(
                    conn,
                    **{k: args[k] for k in ("lake_root", "staging_root", "approval")},
                    source_complete=source,
                    source_record_sha256=known_records[
                        operation_path(
                            args["staging_root"],
                            args["approval"],
                            f"source/dates/{source.trade_date}/source-complete.json",
                        )
                    ][1],
                    source_relation=BOOTSTRAP_DAY_SOURCE,
                    before_publish=lambda: None,
                    check_space=check_test_space,
                    known_records=known_records,
                    date_results=bootstrap_date_results(date_results, source),
                )
                other = {
                    **args,
                    "trade_date": d,
                    "source_complete": source,
                    "raw_audit": raw,
                    "silver_audit": silver,
                    "_raw_relation": None if raw is None else RAW_EXPECTED,
                }
                save(conn, other, known_records=known_records)
        save(conn, args, known_records=known_records)
        root = B.operation_path(
            args["staging_root"], args["approval"], "approval.json"
        ).parent
        originals = {
            p: p.read_bytes()
            for prefix in ("source/dates", "publication")
            for p in (root / prefix).rglob("*.json")
        }
        # The supplement is a new execution, with its own first file observations.
        release_date_work(conn, include_source=True)
        B.release_stk_factor_pro_bootstrap_coverage_inputs(
            conn, basis_inputs=args["_basis_inputs"]
        )
        known_records = {}
        raw, silver = supplement_audits(
            conn, args, (A, B_CODE, C_CODE), known_records=known_records
        )
        publication = C.StkFactorProBootstrapCurrentPublication(
            "supplement-run",
            DAY,
            11,
            12,
            13,
            14,
            raw.file_sha256,
            silver.file_sha256,
            raw.file_sha256,
            args["approval"].contract_content_digest,
            "1",
        )
        initialize_coverage_context(
            conn,
            args,
            known_records=known_records,
            trusted={DAY: (publication, raw, silver)},
        )
        for day, entry in args["_date_results"].items():
            if day == DAY:
                continue
            # The new task's real controller visits every existing completed
            # date. These unchanged dates reuse their loaded result, zero SQL.
            other = {
                **args,
                "trade_date": day,
                "source_complete": entry["source_complete"],
                "raw_audit": entry["raw_audit"],
                "silver_audit": entry["silver_audit"],
                "current_publication": entry["current_publication"],
                "_raw_relation": None,
            }
            save(conn, other, known_records=known_records)
        args.update(
            raw_audit=raw,
            silver_audit=silver,
            current_publication=publication,
            _raw_relation=RAW_EXPECTED,
        )
        calculated = calculate(conn, args, known_records=known_records)
        updated = update(
            conn, args, publication, calculated, known_records=known_records
        )
        assert (
            updated.source_rows == len(original_codes)
            and updated.raw_rows == updated.silver_rows == 3
        )
        assert (
            updated.source_empty is (not bool(original_codes))
            and updated.missing_count == 0
        )
        assert all(p.read_bytes() == before for p, before in originals.items())
        report = summary(args, known_records=known_records)
        assert (
            report.verified_source_rows
            == report.verified_raw_rows
            == report.verified_silver_rows
            == 2
        )
        assert (
            report.current_raw_rows
            == report.current_silver_rows
            == (5 if not original_codes else 3)
        )
        assert report.source_empty_dates == ((DAY,) if not original_codes else ())
        assert report.total_missing_count == (4 if not original_codes else 0)


def test_wrong_current_publication_contract_or_raw_binding_rejected(tmp_path):
    date_results = {}
    known_records = {}
    with connection(tmp_path) as conn:
        args = setup(
            conn, tmp_path, known_records=known_records, date_results=date_results
        )
        result = save(conn, args, known_records=known_records)
        publication = C.StkFactorProBootstrapCurrentPublication(
            "run-b",
            DAY,
            1,
            2,
            3,
            4,
            result.raw_file_sha256,
            result.silver_file_sha256,
            result.raw_file_sha256,
            args["approval"].contract_content_digest,
            "1",
        )
        with pytest.raises(ValueError, match="来源Raw"):
            replace(publication, silver_source_raw_sha256="f" * 64)
        for wrong in (replace(publication, contract_content_digest="f" * 64),):
            with pytest.raises(ValueError, match="补数发布与本日两层audit不符"):
                B.evaluate_stk_factor_pro_bootstrap_coverage_date(
                    prepared=args["_prepared"],
                    calculated=driver._bootstrap_previous_calculation(result),
                    approval_digest=args["_approval_digest"],
                    input_digest=result.input_digest,
                    source_complete=args["source_complete"],
                    current_publication=wrong,
                    previous_result=result,
                )


@pytest.mark.parametrize("data_changed", [False, True])
def test_result_save_failure_keeps_only_still_applicable_previous_coverage(
    tmp_path, monkeypatch, data_changed
):
    from collections import Counter
    from pathlib import Path

    from orchestrator.defs.checks import stk_factor_pro as checks
    from tests.test_stk_factor_pro_bootstrap_process import (
        CountingConnection,
        IsolatedInstance,
        NoProd,
    )

    known_records, date_results = {}, {}
    five_codes = (A, B_CODE, C_CODE, "000003.SZ", "000004.SZ")
    with connection(tmp_path) as conn:
        args = setup(
            conn,
            tmp_path,
            codes=(A, B_CODE, C_CODE),
            before_prepare=(lambda con, lake: upstream(con, lake, codes=five_codes))
            if data_changed
            else None,
            known_records=known_records,
            date_results=date_results,
        )
        save(conn, args, known_records=known_records)
        original_summary = summary(args, known_records=known_records)
        result_path = operation_path(
            args["staging_root"], args["approval"], f"coverage/{DAY}/result.json"
        )
        original_bytes = result_path.read_bytes()
        original_digest = args["_date_results"][DAY]["persisted_result_digest"]
        calls, costs, reads = [], Counter(), Counter()
        build_keys = R.compare_stk_factor_pro_coverage_keys

        def counted_keys(*values, **kwargs):
            calls.append(True)
            return build_keys(*values, **kwargs)

        if data_changed:
            release_date_work(conn, include_source=True)
            B.release_stk_factor_pro_bootstrap_coverage_inputs(
                conn, basis_inputs=args["_basis_inputs"]
            )
            known_records = {}
            raw, silver = supplement_audits(
                conn, args, five_codes, known_records=known_records
            )
        else:
            raw, silver = args["raw_audit"], args["silver_audit"]
        publication = C.StkFactorProBootstrapCurrentPublication(
            "supplement-save",
            DAY,
            11,
            12,
            13,
            14,
            raw.file_sha256,
            silver.file_sha256,
            raw.file_sha256,
            args["approval"].contract_content_digest,
            C.STK_FACTOR_PRO_PROCESSING_VERSION,
        )
        release_date_work(conn, include_source=True)
        if not data_changed:
            B.release_stk_factor_pro_bootstrap_coverage_inputs(
                conn, basis_inputs=args["_basis_inputs"]
            )
        real_write = B.write_json
        read_bytes, classify, prepare_month = (
            Path.read_bytes,
            driver._classify_date,
            driver.prepare_stk_factor_pro_bootstrap_coverage_month,
        )
        original_sha = checks.factor_file_sha

        def sha(path):
            if "missing-codes.parquet" in str(path) or "extra-codes.parquet" in str(
                path
            ):
                costs["diagnostic_sha"] += 1
            return original_sha(path)

        def fail_result(path, record, **kwargs):
            if path == result_path:
                assert (record.source_rows, record.raw_rows, record.missing_count) == (
                    3,
                    5 if data_changed else 3,
                    0,
                )
                raise OSError("result save")
            if path.name == "summary.json":
                costs["summary_writes"] += 1
            return real_write(path, record, **kwargs)

        def read_once(path):
            reads[path] += 1
            return read_bytes(path)

        def classify_once(*values, **kwargs):
            costs["classify"] += 1
            return classify(*values, **kwargs)

        def prepare_once(*values, **kwargs):
            costs["prepare_month"] += 1
            return prepare_month(*values, **kwargs)

        with monkeypatch.context() as scoped:
            scoped.setattr(Path, "read_bytes", read_once)
            scoped.setattr(checks, "factor_file_sha", sha)
            scoped.setattr(B, "write_json", fail_result)
            scoped.setattr(R, "compare_stk_factor_pro_coverage_keys", counted_keys)
            scoped.setattr(driver, "_classify_date", classify_once)
            scoped.setattr(
                driver, "prepare_stk_factor_pro_bootstrap_coverage_month", prepare_once
            )
            with pytest.raises(OSError, match="result save"):
                driver._run_stk_factor_pro_bootstrap(
                    CountingConnection(conn, costs),
                    **{k: args[k] for k in ("lake_root", "staging_root")},
                    operation_id=args["approval"].operation_id,
                    instance=IsolatedInstance(),
                    prod_postgres=NoProd(),
                    current_publications=((publication, raw, silver),),
                )
        report = B.read_json(
            operation_path(
                args["staging_root"], args["approval"], "coverage/summary.json"
            ),
            C.StkFactorProBootstrapCoverageSummary,
            known_records={},
        )
        assert calls == ([True] if data_changed else [])
        assert costs["classify"] == costs["prepare_month"] == 1
        assert costs["summary_writes"] == int(data_changed)
        assert costs["source_parquet_sql"] == 0 and all(n == 1 for n in reads.values())
        assert (
            costs["diagnostic_parquet_sql"]
            == costs["diagnostic_sha"]
            == int(data_changed)
        )
        assert result_path.read_bytes() == original_bytes
        assert report.imported_dates == (DAY,)
        assert (
            report.verified_source_rows
            == report.verified_raw_rows
            == report.verified_silver_rows
            == 3
        )
        assert (
            report.current_raw_rows
            == report.current_silver_rows
            == (5 if data_changed else 3)
        )
        if data_changed:
            assert (
                report.total_missing_count is None and report.date_result_digests == ()
            )
            assert report.coverage_unknown_dates
        else:
            assert report == original_summary and report.total_missing_count == 0
            assert report.date_result_digests == ((DAY, original_digest),)
        assert (
            conn.execute(
                "SELECT table_name FROM duckdb_tables() WHERE temporary "
                "AND (starts_with(table_name,'stk_factor_pro_') OR starts_with(table_name,'stk_factor_bootstrap_coverage_'))"
            ).fetchall()
            == []
        )


def test_replay_zero_keys_zero_result_rewrites_and_global_hash_reuse(
    tmp_path, monkeypatch
):
    date_results = {}
    known_records = {}
    with connection(tmp_path) as conn:
        hashes = []
        original_sha = R.factor_file_sha
        monkeypatch.setattr(
            R,
            "factor_file_sha",
            lambda path: (hashes.append(path), original_sha(path))[1],
        )
        args = setup(
            conn,
            tmp_path,
            codes=(A, B_CODE, C_CODE),
            known_records=known_records,
            date_results=date_results,
        )
        calls = []
        original_keys = R.compare_stk_factor_pro_coverage_keys
        monkeypatch.setattr(
            R,
            "compare_stk_factor_pro_coverage_keys",
            lambda *a, **k: (calls.append(1), original_keys(*a, **k))[1],
        )
        except_count = []

        class ZeroDiagnostics:
            def __getattr__(self, name):
                return getattr(conn, name)

            def execute(self, sql, parameters=None):
                except_count.extend([1] * str(sql).upper().count("EXCEPT"))
                assert not (
                    "read_parquet" in str(sql).lower()
                    and (
                        "missing-codes.parquet" in str(sql) + repr(parameters)
                        or "extra-codes.parquet" in str(sql) + repr(parameters)
                    )
                )
                return (
                    conn.execute(sql)
                    if parameters is None
                    else conn.execute(sql, parameters)
                )

        observed = ZeroDiagnostics()
        result = save(observed, args, known_records=known_records)
        assert len(calls) == 1
        assert len(except_count) == 5  # L-S, eligible-F, actual-F, missing, extra.
        assert result.missing_count == result.extra_count == 0
        assert result.missing_codes_ref is result.extra_codes_ref is None
        assert not operation_path(
            args["staging_root"],
            args["approval"],
            f"coverage/{DAY}/input={result.input_digest}",
        ).exists()
        assert not [
            path
            for path in hashes
            if path.name in ("missing-codes.parquet", "extra-codes.parquet")
        ]
        before = len(hashes)
        global_paths = (
            silver_trade_calendar_path(args["lake_root"]),
            silver_stock_lifecycle_path(args["lake_root"]),
            silver_stock_identity_map_path(args["lake_root"]),
        )
        assert [hashes.count(p) for p in global_paths] == [1, 1, 1]
        monkeypatch.setattr(
            B,
            "write_json",
            lambda *_a, **_k: pytest.fail("unchanged result must not be replaced"),
        )
        assert save(observed, args, known_records=known_records) == result
        assert len(calls) == 1
        assert len(except_count) == 5
        assert all(p not in hashes[before:] for p in global_paths)
        # Summary receives this task's totals and never reads known inputs again.
        monkeypatch.undo()
        hashes = []
        monkeypatch.setattr(
            R,
            "factor_file_sha",
            lambda path: (hashes.append(path), original_sha(path))[1],
        )
        monkeypatch.setattr(
            B, "read_json", lambda *_a, **_k: pytest.fail("summary reread a record")
        )
        report = summary(args, known_records=known_records)
        assert [hashes.count(p) for p in global_paths] == [0, 0, 0]
        monkeypatch.setattr(
            B,
            "write_json",
            lambda *_a, **_k: pytest.fail("unchanged summary must not be rewritten"),
        )
        assert summary(args, known_records=known_records) is report


@pytest.mark.parametrize("kind", ["lifecycle", "identity"])
def test_original_upstream_physical_rules_not_hidden_by_filters(tmp_path, kind):
    date_results = {}
    known_records = {}

    def bad_first_input(conn, lake):
        path = (
            silver_stock_lifecycle_path(lake)
            if kind == "lifecycle"
            else silver_stock_identity_map_path(lake)
        )
        conn.execute(
            f"CREATE TEMP TABLE bad_basis AS SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
        )
        if kind == "lifecycle":
            conn.execute("UPDATE bad_basis SET list_date=NULL WHERE ts_code=?", [A])
        else:
            conn.execute("INSERT INTO bad_basis SELECT * FROM bad_basis LIMIT 1")
        conn.execute("COPY bad_basis TO ? (FORMAT PARQUET)", [str(path)])

    with connection(tmp_path) as conn:
        args = setup(
            conn,
            tmp_path,
            known_records=known_records,
            date_results=date_results,
            before_prepare=bad_first_input,
        )
        result = save(conn, args, known_records=known_records)
        assert result.expected_count is None and kind in result.unknown_input_kinds
        assert result.raw_rows == 2


@pytest.mark.parametrize("edge", ["self_expired", "not_started"])
def test_identity_validity_end_exclusive_and_no_self_fallback(tmp_path, edge):
    date_results = {}
    known_records = {}
    with connection(tmp_path) as conn:
        identities = [
            (
                c,
                c,
                DAY + timedelta(days=1)
                if edge == "not_started" and c == A
                else date(2010, 1, 1),
                DAY if edge == "self_expired" and c == A else None,
                date(2010, 1, 1),
                None,
                "stock_lifecycle",
                "confirmed",
                None,
                datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
            for c in (A, B_CODE, C_CODE)
        ]
        args = setup(
            conn,
            tmp_path,
            identities=identities,
            known_records=known_records,
            date_results=date_results,
        )
        result = save(conn, args, known_records=known_records)
        assert (
            result.identity_unmapped_count == 1
            and result.identity_unmapped_sample_codes == (A,)
        )
        assert result.coverage_complete is None


def test_bse_not_expected_before_market_open_and_listing_end_exclusive(tmp_path):
    date_results = {}
    known_records = {}
    bj = "830001.BJ"
    with connection(tmp_path) as conn:
        life = [
            (A, A[:6], A, "SZSE", None, "CNY", True, "L", DAY, None),
            (
                B_CODE,
                B_CODE[:6],
                B_CODE,
                "SSE",
                None,
                "CNY",
                True,
                "D",
                date(2010, 1, 1),
                DAY,
            ),
            (bj, bj[:6], bj, "BSE", None, "CNY", True, "L", date(2010, 1, 1), None),
        ]
        args = setup(
            conn,
            tmp_path,
            codes=(A, bj),
            life=life,
            identities=[
                (
                    c,
                    c,
                    date(2010, 1, 1),
                    None,
                    date(2010, 1, 1),
                    None,
                    "stock_lifecycle",
                    "confirmed",
                    None,
                    datetime(2026, 1, 1, tzinfo=timezone.utc),
                )
                for c in (A, B_CODE, bj)
            ],
            known_records=known_records,
            date_results=date_results,
        )
        result = save(conn, args, known_records=known_records)
        assert (
            result.expected_count,
            result.actual_count,
            result.matched_count,
            result.missing_count,
            result.extra_count,
        ) == (0, 1, 0, 0, 1)  # A is optional on its listing day; BJ is extra.
        assert result.extra_sample_codes == (bj,)


def test_transfer_mismatch_not_misreported_as_market_gap(tmp_path):
    date_results = {}
    known_records = {}
    with connection(tmp_path) as conn:
        args = setup(
            conn, tmp_path, known_records=known_records, date_results=date_results
        )
        release_date_work(conn, include_source=True)
        known_records = {}
        raw, silver = supplement_audits(conn, args, (A,), known_records=known_records)
        with pytest.raises(ValueError, match="首次导入数量与原来源不符"):
            save(
                conn,
                {**args, "raw_audit": raw, "silver_audit": silver},
                known_records=known_records,
            )
        assert not operation_path(
            args["staging_root"], args["approval"], "coverage/2019-10-16/result.json"
        ).exists()


def test_summary_write_failure_keeps_result_and_business_files(tmp_path, monkeypatch):
    date_results = {}
    known_records = {}
    with connection(tmp_path) as conn:
        args = setup(
            conn, tmp_path, known_records=known_records, date_results=date_results
        )
        result = save(conn, args, known_records=known_records)
        monkeypatch.setattr(
            B,
            "write_json",
            lambda *_a, **_k: (_ for _ in ()).throw(OSError("summary save")),
        )
        with pytest.raises(OSError, match="summary save"):
            summary(args, known_records=known_records)
        assert factor_file_sha(args["raw_audit"].path) == result.raw_file_sha256
        assert not operation_path(
            args["staging_root"], args["approval"], "coverage/summary.json"
        ).exists()


def test_cleanup_all_tables_preserves_primary_failure(tmp_path, monkeypatch):
    date_results = {}
    known_records = {}
    with connection(tmp_path) as conn:
        args = setup(
            conn, tmp_path, known_records=known_records, date_results=date_results
        )
        monkeypatch.setattr(
            R,
            "compare_stk_factor_pro_coverage_keys",
            lambda *_a, **_k: (_ for _ in ()).throw(
                KeyboardInterrupt("primary cancel")
            ),
        )
        executed = []

        class WrappedConnection:
            def execute(self, query, *a, **k):
                executed.append(query)
                if query.startswith("DROP TABLE IF EXISTS ") and query.endswith(
                    "stk_factor_pro_coverage_listed_input"
                ):
                    raise OSError("cleanup one")
                if query.startswith("DROP TABLE IF EXISTS ") and query.endswith(
                    "stk_factor_pro_coverage_suspend_input"
                ):
                    raise RuntimeError("cleanup two")
                return conn.execute(query, *a, **k)

        with pytest.raises(KeyboardInterrupt, match="primary cancel") as caught:
            save(WrappedConnection(), args, known_records=known_records)
        assert "覆盖计算清理同时失败：OSError" in caught.value.__notes__
        assert any(q.endswith(R.STK_FACTOR_PRO_COVERAGE_TABLES[-1]) for q in executed)


def test_release_month_preserves_global_tables_and_bounded_identity_cache(
    tmp_path, monkeypatch
):
    date_results = {}
    known_records = {}
    days = (date(2019, 10, 31), date(2019, 11, 1))
    with connection(tmp_path) as conn:
        args = setup(
            conn,
            tmp_path,
            days=days,
            known_records=known_records,
            date_results=date_results,
        )
        save(conn, args, known_records=known_records)
        B.release_stk_factor_pro_bootstrap_coverage_month(
            conn, basis_inputs=args["_basis_inputs"]
        )
        names = {
            r[0]
            for r in conn.execute(
                "SELECT table_name FROM duckdb_tables() WHERE temporary"
            ).fetchall()
        }
        assert B._SUSPEND not in names
        assert all(
            B._PREFIX + kind in names for kind in ("calendar", "lifecycle", "identity")
        )
        assert args["_basis_inputs"]["active_month"] is None
        original = R.factor_file_sha
        hashes = []
        monkeypatch.setattr(
            R, "factor_file_sha", lambda p: (hashes.append(p), original(p))[1]
        )
        args["inputs"] = B.prepare_stk_factor_pro_bootstrap_coverage_month(
            conn,
            **{k: args[k] for k in ("lake_root", "staging_root", "approval")},
            month=args["approval"].month_limits[1],
            basis_inputs=args["_basis_inputs"],
            known_records=known_records,
        )
        assert args["inputs"].open_dates == (days[1],)
        assert all(
            p not in hashes
            for p in (
                silver_trade_calendar_path(args["lake_root"]),
                silver_stock_lifecycle_path(args["lake_root"]),
                silver_stock_identity_map_path(args["lake_root"]),
            )
        )


def test_release_attempts_all_tables_after_multiple_cleanup_failures(tmp_path):
    date_results = {}
    known_records = {}
    with connection(tmp_path) as conn:
        args = setup(
            conn, tmp_path, known_records=known_records, date_results=date_results
        )
        dropped = []

        class WrappedConnection:
            def execute(self, query, *a, **k):
                if query.startswith("DROP TABLE IF EXISTS "):
                    dropped.append(query.split()[-1])
                    if query.endswith(B._SUSPEND):
                        raise OSError("first cleanup")
                    if query.endswith(B._PREFIX + "calendar"):
                        raise RuntimeError("second cleanup")
                return conn.execute(query, *a, **k)

        with pytest.raises(OSError, match="first cleanup"):
            B.release_stk_factor_pro_bootstrap_coverage_inputs(
                WrappedConnection(), basis_inputs=args["_basis_inputs"]
            )
        assert dropped == [
            B._SUSPEND,
            B._PREFIX + "calendar",
            B._PREFIX + "lifecycle",
            B._PREFIX + "identity",
        ]


@pytest.mark.parametrize(
    "failure",
    ["silver", "target-fsync", "complete", "evaluate", "result-before", "result-fsync"],
)
def test_real_control_failure_summarizes_registered_facts_without_reauditing(
    tmp_path, monkeypatch, failure
):
    import json
    from collections import Counter
    from pathlib import Path

    from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_records as records
    from orchestrator.defs.paths import (
        raw_stk_factor_pro_path,
        silver_stock_factor_pro_path,
    )
    from tests.test_stk_factor_pro_bootstrap_process import (
        CountingConnection,
        IsolatedInstance,
    )
    from tests.test_stk_factor_pro_bootstrap_source import FakeProd

    costs = Counter()
    with connection(tmp_path) as conn:
        lake, staging, approval, source_identity = approval_fixture(
            conn, tmp_path, known_records={}
        )
        upstream(conn, lake, codes=(A,))
        remote = FakeProd(approval, source_identity, ((DAY, 1),), [native_row()])
        raw_path = raw_stk_factor_pro_path(lake, DAY.isoformat())
        silver_path = silver_stock_factor_pro_path(lake, DAY.isoformat())
        root = records.operation_root(staging, approval)
        result_path = root / f"coverage/{DAY}/result.json"
        complete_path = root / f"publication/{DAY}/raw/complete.json"
        observed_reads = Counter()
        read_bytes = Path.read_bytes
        classify = driver._classify_date
        prepare_month = driver.prepare_stk_factor_pro_bootstrap_coverage_month
        build_keys = R.compare_stk_factor_pro_coverage_keys
        write_json = B.write_json
        fsync_directory = records.fsync_directory
        write_complete = P.write_stk_factor_pro_bootstrap_publication_complete
        build_silver = P.build_stk_factor_pro_silver_candidate
        evaluate = driver.evaluate_stk_factor_pro_bootstrap_coverage_date

        def read_once(path):
            observed_reads[path] += 1
            return read_bytes(path)

        def classify_once(*args, **kwargs):
            costs["classify"] += 1
            return classify(*args, **kwargs)

        def prepare_once(*args, **kwargs):
            costs["prepare_month"] += 1
            return prepare_month(*args, **kwargs)

        def keys_once(*args, **kwargs):
            costs["coverage_keys"] += 1
            return build_keys(*args, **kwargs)

        def save_record(path, record, **kwargs):
            if path.name == "summary.json":
                costs["summary_writes"] += 1
            if failure == "result-before" and path == result_path:
                raise OSError(failure)
            return write_json(path, record, **kwargs)

        def sync(path):
            if (
                failure == "target-fsync"
                and path == raw_path.parent
                and raw_path.exists()
            ):
                raise OSError(failure)
            if (
                failure == "result-fsync"
                and path == result_path.parent
                and result_path.exists()
            ):
                raise OSError(failure)
            return fsync_directory(path)

        def complete(**kwargs):
            if failure == "complete" and kwargs["record"].layer == "raw":
                raise OSError(failure)
            return write_complete(**kwargs)

        def silver(*args, **kwargs):
            if failure == "silver":
                raise OSError(failure)
            return build_silver(*args, **kwargs)

        def evaluated(*args, **kwargs):
            if failure == "evaluate":
                raise OSError(failure)
            return evaluate(*args, **kwargs)

        monkeypatch.setattr(Path, "read_bytes", read_once)
        monkeypatch.setattr(driver, "_classify_date", classify_once)
        monkeypatch.setattr(
            driver, "prepare_stk_factor_pro_bootstrap_coverage_month", prepare_once
        )
        monkeypatch.setattr(R, "compare_stk_factor_pro_coverage_keys", keys_once)
        monkeypatch.setattr(B, "write_json", save_record)
        monkeypatch.setattr(records, "fsync_directory", sync)
        monkeypatch.setattr(
            P, "write_stk_factor_pro_bootstrap_publication_complete", complete
        )
        monkeypatch.setattr(P, "build_stk_factor_pro_silver_candidate", silver)
        monkeypatch.setattr(
            driver, "evaluate_stk_factor_pro_bootstrap_coverage_date", evaluated
        )
        with pytest.raises(OSError, match=failure):
            driver._run_stk_factor_pro_bootstrap(
                CountingConnection(conn, costs),
                lake_root=lake,
                staging_root=staging,
                operation_id=approval.operation_id,
                instance=IsolatedInstance(),
                prod_postgres=remote,
            )
        assert (
            costs["classify"] == costs["prepare_month"] == costs["summary_writes"] == 1
        )
        assert costs["coverage_keys"] == int(
            failure in ("evaluate", "result-before", "result-fsync")
        )
        assert costs["source_parquet_sql"] == 1
        assert all(count == 1 for count in observed_reads.values())
        report = json.loads((root / "coverage/summary.json").read_text())
        assert raw_path.is_file()
        layers_complete = failure in ("evaluate", "result-before", "result-fsync")
        assert silver_path.exists() is layers_complete
        assert complete_path.exists() is (
            failure != "target-fsync" and failure != "complete"
        )
        assert report["imported_dates"] == (
            [DAY.isoformat()] if layers_complete else []
        )
        assert report["import_pending_dates"] == (
            [] if layers_complete else [DAY.isoformat()]
        )
        assert report["verified_source_rows"] == int(layers_complete)
        assert report["total_missing_count"] is None
        assert report["date_result_digests"] == []
        assert result_path.exists() is (failure == "result-fsync")
        assert (
            conn.execute(
                "SELECT table_name FROM duckdb_tables() WHERE temporary "
                "AND (starts_with(table_name,'stk_factor_pro_') OR starts_with(table_name,'stk_factor_bootstrap_coverage_'))"
            ).fetchall()
            == []
        )


def test_month_coverage_uses_only_target_day_suspend(tmp_path):
    """A next-day unmapped suspension must not change today's known coverage."""
    later = DAY + timedelta(days=1)
    with connection(tmp_path) as conn:
        known = {}
        args = setup(
            conn,
            tmp_path,
            days=(DAY, later),
            codes=(A,),
            suspensions={later: (("000004.SZ", later, None, "S"),)},
            known_records=known,
            date_results={},
        )
        current = calculate(conn, args, known_records=known)
        assert (
            current.expected_count,
            current.actual_count,
            current.missing_count,
        ) == (3, 1, 2)
        assert current.unknown_input_kinds == ()


@pytest.mark.parametrize("include_first_day", [False, True])
def test_first_day_optional_counts_keep_original_and_physical_rows(
    tmp_path, include_first_day
):
    # Producer-schema lifecycle facts are independent of the coverage algorithm.
    life = [
        (c, c[:6], c, "SZSE" if c.endswith("SZ") else "SSE", None,
         "CNY", True, "L", DAY if c == C_CODE else date(2010, 1, 1), None)
        for c in (A, B_CODE, C_CODE)
    ]
    codes = (A, B_CODE, C_CODE) if include_first_day else (A, B_CODE)
    known, date_results = {}, {}
    with connection(tmp_path) as conn:
        args = setup(
            conn, tmp_path, codes=codes, life=life,
            known_records=known, date_results=date_results,
        )
        value = save(conn, args, known_records=known)
        assert value.coverage_rule_version == "1" and value.coverage_complete is True
        assert (
            value.expected_count, value.actual_count, value.matched_count,
            value.missing_count, value.extra_count,
        ) == (2, 2, 2, 0, 0)
        assert (value.source_rows, value.raw_rows, value.silver_rows, value.raw_physical_code_count) == (len(codes),) * 4
        report = summary(args, known_records=known)
        assert report.expected_count_known_dates == report.actual_count_known_dates == 2
        assert report.verified_source_rows == report.current_raw_rows == report.current_silver_rows == len(codes)
        assert report.total_missing_count == 0 and report.extra_count_known_dates == 0
        assert conn.execute(
            f"SELECT ts_code FROM {read_parquet(args['raw_audit'].path, hive_partitioning=False)} ORDER BY ts_code"
        ).fetchall() == [(c,) for c in sorted(codes)]
        B.release_stk_factor_pro_bootstrap_coverage_inputs(
            conn, basis_inputs=args["_basis_inputs"]
        )


def test_bootstrap_extra_only_is_incomplete_without_deleting_source_rows(tmp_path):
    known = {}
    with connection(tmp_path) as conn:
        args = setup(
            conn, tmp_path, codes=(A, B_CODE, C_CODE),
            suspensions={DAY: [(C_CODE, DAY, None, "S")]},
            known_records=known, date_results={},
        )
        value = save(conn, args, known_records=known)
        assert (value.expected_count, value.actual_count, value.missing_count, value.extra_count) == (2, 3, 0, 1)
        assert value.coverage_complete is False
        assert value.source_rows == value.raw_rows == value.silver_rows == 3
        report = summary(args, known_records=known)
        assert report.total_missing_count == 0 and report.extra_count_known_dates == 1
        emitted = []
        progress = driver._BootstrapProgress(args["approval"].operation_id)
        progress.emit = lambda event, **fields: emitted.append((event, fields))
        progress.finish(report)
        assert emitted[-1][1]["coverage_state"] == "incomplete"
        B.release_stk_factor_pro_bootstrap_coverage_inputs(
            conn, basis_inputs=args["_basis_inputs"]
        )


def test_coverage_rule_change_cannot_reuse_cached_date_record(tmp_path, monkeypatch):
    known = {}
    with connection(tmp_path) as conn:
        args = setup(
            conn, tmp_path, codes=(A, B_CODE, C_CODE),
            known_records=known, date_results={},
        )
        value = save(conn, args, known_records=known)
        original_month_digest = args["inputs"].input_digest
        with monkeypatch.context() as scoped:
            scoped.setattr(C, "STK_FACTOR_PRO_COVERAGE_RULE_VERSION", "2")
            with pytest.raises(ValueError, match="规则已变"):
                B.read_stk_factor_pro_bootstrap_coverage_date(
                    conn, staging_root=args["staging_root"], approval=args["approval"],
                    approval_digest=args["_approval_digest"],
                    source_complete=args["source_complete"], trade_date=DAY,
                    known_records=known,
                )
            assert B._date_digest(
                args["approval"], args["_approval_digest"], DAY,
                args["source_complete"],
                (value.raw_file_sha256, value.silver_file_sha256),
                value.basis_files, value.is_open,
            ) != value.input_digest
            inputs = args["inputs"]
            assert C.stk_factor_pro_bootstrap_month_basis_digest(
                operation_id=inputs.operation_id, approval_digest=args["_approval_digest"],
                month=inputs.month, natural_dates=inputs.natural_dates,
                open_dates=inputs.open_dates, closed_dates=inputs.closed_dates,
                calendar_unknown_dates=inputs.calendar_unknown_dates,
                basis_files=inputs.basis_files,
            ) != original_month_digest
        B.release_stk_factor_pro_bootstrap_coverage_inputs(
            conn, basis_inputs=args["_basis_inputs"]
        )
