"""Invalid basis is unknown; real execution errors still fail (LLD 17.8.4).

Schemas and basic rows come from the existing real-producer-schema fixtures.
Only the named corrupt basis cells are intentionally invalid. Expected dates,
codes, counts and unknown kinds below are independent literals.
"""

from datetime import date, datetime, timedelta, timezone
from time import perf_counter

import duckdb
import pytest

from orchestrator.defs.asset_guards import stk_factor_pro_readiness as R
from orchestrator.defs.asset_guards.stk_factor_pro_readiness import (
    stk_factor_pro_invalid_code_sql,
)
from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_coverage as B
from orchestrator.defs.bootstrap import stk_factor_pro_history as H
from orchestrator.defs.bootstrap.stk_factor_pro_bootstrap_records import (
    operation_path,
    read_json,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.paths import (
    raw_stk_factor_pro_path,
    silver_stock_factor_pro_path,
    silver_stock_identity_map_path,
    silver_stock_lifecycle_path,
    silver_stock_suspend_daily_path,
)
from orchestrator.defs.run_contracts import stk_factor_pro as C
from tests.stk_factor_pro_bootstrap_test_support import approval_fixture, native_row
from tests.stk_factor_pro_test_support import connection
from tests.test_stk_factor_pro_bootstrap import Instance
from tests.test_stk_factor_pro_bootstrap_coverage import upstream
from tests.test_stk_factor_pro_bootstrap_source import FakeProd

DAY = date(2019, 10, 16)
DAYS = (DAY, DAY + timedelta(days=1))
A = "000001.SZ"


def prepare_case(conn, tmp_path, *, known_records):
    counts = ((DAYS[0], 1), (DAYS[1], 1))
    lake, staging, approval, identity = approval_fixture(
        conn, tmp_path, counts=counts, known_records=known_records
    )
    upstream(conn, lake, days=DAYS, codes=(A,))
    remote = FakeProd(approval, identity, counts, [native_row(A, day=d) for d in DAYS])
    return lake, staging, approval, remote


def rewrite_column(conn, path, column, value):
    # The original producer schema remains intact, only a deliberate bad cell changes.
    conn.execute(
        f"CREATE OR REPLACE TEMP TABLE bad_coverage_input AS SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
    )
    conn.execute(f"UPDATE bad_coverage_input SET {column}=?", [value])
    conn.execute("COPY bad_coverage_input TO ? (FORMAT PARQUET)", [str(path)])
    conn.execute("DROP TABLE bad_coverage_input")


def prepare(conn, lake, staging, approval, *, known_records):
    return B.prepare_stk_factor_pro_bootstrap_coverage_month(
        conn,
        lake_root=lake,
        staging_root=staging,
        approval=approval,
        month=approval.month_limits[0],
        basis_inputs={"files": {}, "months": {}, "active_month": None},
        known_records=known_records,
    )


def run_case(lake, staging, approval, remote):
    # The preceding input assertion is a separate observation, not task memory.
    # The real operation must first read its own necessary inputs and facts.
    with connection(staging.parent) as execution:
        return H._run_stk_factor_pro_bootstrap(
            execution,
            lake_root=lake,
            staging_root=staging,
            operation_id=approval.operation_id,
            instance=Instance(),
            prod_postgres=remote,
        )


def test_history_first_bad_lifecycle_schema_is_not_read_again_by_coverage(
    tmp_path, monkeypatch
):
    from orchestrator.defs.checks import stk_factor_pro as checks
    from orchestrator.defs.io import stk_factor_pro_history as history
    from tests.stk_factor_pro_history_test_support import write_factor_file

    known_records = {}
    with connection(tmp_path) as conn:
        lake, staging, approval, _ = prepare_case(
            conn, tmp_path, known_records=known_records
        )
        lifecycle = silver_stock_lifecycle_path(lake)
        conn.execute("CREATE TEMP TABLE first_bad_schema(ts_code VARCHAR)")
        conn.execute("INSERT INTO first_bad_schema VALUES (?)", [A])
        conn.execute("COPY first_bad_schema TO ? (FORMAT PARQUET)", [str(lifecycle)])
        refs = tuple(
            write_factor_file(conn, lake, day, ((A, 1.0),))
            for day in (DAY, DAY - timedelta(days=1))
        )
        reads, hashes = [], []
        original_sha = checks.factor_file_sha

        def file_sha(path):
            if path == lifecycle:
                hashes.append(path)
            return original_sha(path)

        class ObservedConnection:
            def execute(self, query, *args, **kwargs):
                if "read_parquet" in str(query) and str(lifecycle) in str(query):
                    reads.append(str(query))
                return conn.execute(query, *args, **kwargs)

        monkeypatch.setattr(checks, "factor_file_sha", file_sha)
        observed = ObservedConnection()
        basis_inputs = {"files": {}, "months": {}, "active_month": None}
        try:
            _, lifecycle_relation = history.prepare_stk_factor_pro_history_inputs(
                observed,
                identity=C.RunIdentity(
                    "bad-life-schema",
                    None,
                    DAY,
                    DAY,
                    DAY - timedelta(days=1),
                    "today",
                    0,
                ),
                lake_root=lake,
                factor_t=refs[0],
                factor_p=refs[1],
                known_records=known_records,
                check_cancel=lambda: None,
            )
            assert lifecycle_relation is None
            assert known_records[lifecycle][0] == (None, 1, (("ts_code", "VARCHAR"),))
            inputs = B.prepare_stk_factor_pro_bootstrap_coverage_month(
                observed,
                lake_root=lake,
                staging_root=staging,
                approval=approval,
                month=approval.month_limits[0],
                basis_inputs=basis_inputs,
                known_records=known_records,
            )
            assert len(reads) == len(hashes) == 1
            assert tuple(kinds for _, kinds, _ in inputs.unknown_by_date) == (
                ("lifecycle",),
                ("lifecycle",),
            )
        finally:
            B.release_stk_factor_pro_bootstrap_coverage_inputs(
                conn, basis_inputs=basis_inputs
            )
            history.release_stk_factor_pro_history_inputs(conn)


def assert_days_faithful(conn, lake, staging, approval, unknown_days, *, known_records):
    for day in DAYS:
        for layer in ("raw", "silver"):
            path = (
                raw_stk_factor_pro_path
                if layer == "raw"
                else silver_stock_factor_pro_path
            )(lake, day.isoformat())
            expected_date = day.strftime("%Y%m%d") if layer == "raw" else day
            assert conn.execute(
                f"SELECT ts_code,trade_date,close FROM {read_parquet(path, hive_partitioning=False)}"
            ).fetchall() == [(A, expected_date, 10.0)]
            assert (
                len(
                    conn.execute(
                        f"DESCRIBE SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
                    ).fetchall()
                )
                == 261
            )
        result = read_json(
            operation_path(
                staging, approval, f"coverage/{day.isoformat()}/result.json"
            ),
            C.StkFactorProBootstrapDateCoverage,
            known_records=known_records,
        )
        assert result.source_rows == result.raw_rows == result.silver_rows == 1
        if day in unknown_days:
            assert result.coverage_complete is None
            assert result.expected_count is result.actual_count is None
            assert result.missing_count is result.extra_count is None
        else:
            assert result.coverage_complete is True
            assert result.missing_count == result.extra_count == 0


@pytest.mark.parametrize(
    "bad", ["lifecycle", "source_ts_code", "latest_ts_code", "both"]
)
def test_bad_codes_are_unknown_and_both_days_still_import(tmp_path, bad):
    known_records = {}
    with connection(tmp_path) as conn:
        lake, staging, approval, remote = prepare_case(
            conn, tmp_path, known_records=known_records
        )
        if bad in ("lifecycle", "both"):
            rewrite_column(
                conn, silver_stock_lifecycle_path(lake), "ts_code", "INVALID"
            )
        if bad != "lifecycle":
            rewrite_column(
                conn,
                silver_stock_identity_map_path(lake),
                "latest_ts_code" if bad == "both" else bad,
                "INVALID",
            )
        inputs = prepare(conn, lake, staging, approval, known_records=known_records)
        expected = (
            ("identity", "lifecycle")
            if bad == "both"
            else ("lifecycle" if bad == "lifecycle" else "identity",)
        )
        assert tuple((d, kinds) for d, kinds, _ in inputs.unknown_by_date) == (
            (DAYS[0], expected),
            (DAYS[1], expected),
        )
        identity = next(b for b in inputs.basis_files if b.kind == "identity")
        # Code format now belongs to the affected dates, not the entire snapshot.
        assert identity.valid
        assert any(
            "INVALID" in reason and "1行" in reason
            for _, _, reason in inputs.unknown_by_date
        )
        summary = run_case(lake, staging, approval, remote)
        assert (
            summary.verified_source_rows
            == summary.verified_raw_rows
            == summary.verified_silver_rows
            == 2
        )
        assert summary.total_missing_count is None
        assert_days_faithful(
            conn, lake, staging, approval, set(DAYS), known_records=known_records
        )


def test_bad_suspension_affects_only_its_day(tmp_path):
    known_records = {}
    with connection(tmp_path) as conn:
        lake, staging, approval, remote = prepare_case(
            conn, tmp_path, known_records=known_records
        )
        # Add one deliberately malformed row to the first day's real 4-column file.
        path = silver_stock_suspend_daily_path(lake, DAYS[0].isoformat())
        conn.execute(
            f"CREATE TEMP TABLE bad_suspend AS SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
        )
        conn.execute("INSERT INTO bad_suspend VALUES ('INVALID',?,'S',NULL)", [DAYS[0]])
        conn.execute("COPY bad_suspend TO ? (FORMAT PARQUET)", [str(path)])
        inputs = prepare(conn, lake, staging, approval, known_records=known_records)
        assert tuple((d, kinds) for d, kinds, _ in inputs.unknown_by_date) == (
            (DAYS[0], ("suspend",)),
        )
        run_case(lake, staging, approval, remote)
        assert_days_faithful(
            conn, lake, staging, approval, {DAYS[0]}, known_records=known_records
        )


def test_valid_inputs_import_both_days_and_do_not_become_unknown(tmp_path):
    known_records = {}
    with connection(tmp_path) as conn:
        lake, staging, approval, remote = prepare_case(
            conn, tmp_path, known_records=known_records
        )
        assert (
            prepare(
                conn, lake, staging, approval, known_records=known_records
            ).unknown_by_date
            == ()
        )
        summary = run_case(lake, staging, approval, remote)
        assert summary.all_coverage_determined and summary.total_missing_count == 0
        assert_days_faithful(
            conn, lake, staging, approval, set(), known_records=known_records
        )


@pytest.mark.parametrize("entry", ["bootstrap", "daily"])
def test_retired_historical_identity_does_not_block_2017(
    tmp_path, entry, record_property, monkeypatch
):
    # Existing bounded DG lookup: these are two independent self identities.
    # This test preserves both upstream records, rather than changing T600018.SH.
    day, old, current = date(2017, 1, 3), "T600018.SH", "600018.SH"
    with connection(tmp_path) as conn:
        known = {}
        counts = ((day, 1),)
        lake, staging, approval, source_identity = approval_fixture(
            conn, tmp_path, counts=counts, known_records=known
        )
        life = [
            (
                old,
                "T600018",
                "上港集箱(退)",
                "SSE",
                None,
                "CNY",
                True,
                "D",
                date(2000, 7, 19),
                date(2006, 10, 20),
            ),
            (
                current,
                "600018",
                "上港集团",
                "SSE",
                None,
                "CNY",
                True,
                "L",
                date(2006, 10, 26),
                None,
            ),
        ]
        identities = [
            (
                code,
                code,
                first,
                last,
                first,
                last,
                "stock_lifecycle",
                "confirmed",
                "historical stock lifecycle self mapping",
                datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
            for code, first, last in (
                (old, date(2000, 7, 19), date(2006, 10, 20)),
                (current, date(2006, 10, 26), None),
            )
        ]
        upstream(conn, lake, (day,), life=life, identities=identities)
        if entry == "bootstrap":
            remote = FakeProd(
                approval, source_identity, counts, [native_row(current, day=day)]
            )
            summary = run_case(lake, staging, approval, remote)
            assert summary.all_coverage_determined
            assert (
                summary.verified_source_rows
                == summary.verified_raw_rows
                == summary.verified_silver_rows
                == 1
            )
            result = read_json(
                operation_path(staging, approval, f"coverage/{day}/result.json"),
                C.StkFactorProBootstrapDateCoverage,
                known_records=known,
            )
            assert (
                result.expected_count,
                result.actual_count,
                result.matched_count,
                result.missing_count,
                result.extra_count,
            ) == (1, 1, 1, 0, 0)
        else:
            inherited, reads, hashes, code_queries = {}, [], [], []
            file_sha = R.factor_file_sha

            def counted_sha(path):
                hashes.append(path)
                return file_sha(path)

            monkeypatch.setattr(R, "factor_file_sha", counted_sha)

            class ObservedConnection:
                def execute(self, query, *args, **kwargs):
                    if "read_parquet" in query:
                        reads.append(query)
                    if "relevant_codes" in query:
                        code_queries.append(query)
                    return conn.execute(query, *args, **kwargs)

            observed = ObservedConnection()
            started = perf_counter()
            inputs = R.prepare_stk_factor_pro_coverage_inputs(
                observed,
                lake_root=lake,
                trade_date=day,
                inherited_facts=inherited,
                known_records=known,
            )
            assert inputs["unknown_input_kinds"] == ()
            record_property("daily_prepare_seconds", perf_counter() - started)
            assert (
                len(code_queries) == 4
            )  # Three format counts plus one reference count.
            assert (
                len(reads) == 4
            )  # Calendar/lifecycle/identity/this day's final suspend.
            assert (
                R.prepare_stk_factor_pro_coverage_inputs(
                    observed,
                    lake_root=lake,
                    trade_date=day,
                    inherited_facts=inherited,
                    known_records=known,
                )
                is inputs
            )
            conn.execute(
                "CREATE TEMP TABLE actual_day(ts_code VARCHAR,trade_date VARCHAR)"
            )
            conn.execute("INSERT INTO actual_day VALUES ('600018.SH','20170103')")
            calculated = R.calculate_stk_factor_pro_coverage(
                observed, coverage_inputs=inputs, raw_relation="actual_day"
            )
            assert calculated["unknown_input_kinds"] == ()
            result = calculated["coverage_counts"]
            assert (
                result.expected_count,
                result.actual_count,
                result.matched_count,
                result.missing_count,
                result.extra_count,
            ) == (1, 1, 1, 0, 0)
            assert conn.execute(
                "SELECT ts_code FROM stk_factor_pro_coverage_expected"
            ).fetchall() == [(current,)]
            assert len(reads) == 4
            assert len(hashes) == 4
            assert len(code_queries) == 4  # Reuse the original date preparation.
            record_property("basis_parquet_reads", len(reads))
            record_property("basis_file_hashes", len(hashes))
            record_property("date_code_queries", len(code_queries))
            R.release_stk_factor_pro_coverage_inputs(conn, inherited_facts=inherited)
        # Neither producer input is edited or reduced by the consumer.
        for path in (
            silver_stock_lifecycle_path(lake),
            silver_stock_identity_map_path(lake),
        ):
            assert (
                conn.execute(
                    f"SELECT count(*) FROM {read_parquet(path, hive_partitioning=False)}"
                ).fetchone()[0]
                == 2
            )


@pytest.mark.parametrize(
    "kind", ["lifecycle", "source_ts_code", "latest_ts_code", "reference"]
)
@pytest.mark.parametrize("window", ["ended", "future", "ends_second_day"])
def test_code_errors_only_affect_dates_in_effective_interval(tmp_path, kind, window):
    # Synthetic bad code intentionally fails the consumer rule. Date boundaries
    # and expected unknown days below are literal, independent of the selector.
    with connection(tmp_path) as conn:
        known = {}
        lake, staging, approval, remote = prepare_case(
            conn, tmp_path, known_records=known
        )
        first, last = {
            "ended": (date(2000, 1, 1), DAY),
            "future": (DAYS[1] + timedelta(days=1), None),
            "ends_second_day": (date(2010, 1, 1), DAYS[1]),
        }[window]
        life = [
            (
                A,
                "000001",
                "synthetic A",
                "SZSE",
                None,
                "CNY",
                True,
                "L",
                date(2010, 1, 1),
                None,
            ),
            (
                "INVALID",
                "INVALID",
                "deliberate bad code",
                "SSE",
                None,
                "CNY",
                True,
                "D",
                first if kind == "lifecycle" else date(2000, 1, 1),
                last if kind == "lifecycle" else date(2006, 10, 20),
            ),
        ]
        identities = [
            (
                A,
                A,
                date(2010, 1, 1),
                None,
                date(2010, 1, 1),
                None,
                "stock_lifecycle",
                "confirmed",
                None,
                datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
        ]
        if kind != "lifecycle":
            identities.append(
                (
                    A
                    if kind == "source_ts_code"
                    else ("600999.SH" if kind == "reference" else "INVALID"),
                    "INVALID" if kind == "source_ts_code" else "600000.SH",
                    first,
                    last,
                    first,
                    last,
                    "stock_lifecycle",
                    "confirmed",
                    None,
                    datetime(2026, 1, 1, tzinfo=timezone.utc),
                )
            )
        upstream(conn, lake, DAYS, life=life, identities=identities)
        inputs = prepare(conn, lake, staging, approval, known_records=known)
        expected_kind = "lifecycle" if kind == "lifecycle" else "identity"
        expected_unknown = (
            ((DAY, (expected_kind,)),) if window == "ends_second_day" else ()
        )
        assert (
            tuple((d, kinds) for d, kinds, _ in inputs.unknown_by_date)
            == expected_unknown
        ), inputs.unknown_by_date
        assert all(
            b.valid for b in inputs.basis_files if b.kind in ("lifecycle", "identity")
        )
        run_case(lake, staging, approval, remote)
        assert_days_faithful(
            conn,
            lake,
            staging,
            approval,
            {DAY} if window == "ends_second_day" else set(),
            known_records=known,
        )


@pytest.mark.parametrize("bad", ["missing", "schema", "parquet"])
def test_bad_basis_file_keeps_legal_import_and_only_lifecycle_unknown(tmp_path, bad):
    known_records = {}
    with connection(tmp_path) as conn:
        lake, staging, approval, remote = prepare_case(
            conn, tmp_path, known_records=known_records
        )
        path = silver_stock_lifecycle_path(lake)
        if bad == "missing":
            path.unlink()
        elif bad == "schema":
            conn.execute(
                "COPY (SELECT '000001.SZ'::VARCHAR AS ts_code) TO ? (FORMAT PARQUET)",
                [str(path)],
            )
        else:
            path.write_bytes(b"deliberately not parquet")
        inputs = prepare(conn, lake, staging, approval, known_records=known_records)
        assert tuple(kinds for _, kinds, _ in inputs.unknown_by_date) == (
            ("lifecycle",),
            ("lifecycle",),
        )
        assert next(b for b in inputs.basis_files if b.kind == "identity").valid
        run_case(lake, staging, approval, remote)
        assert_days_faithful(
            conn, lake, staging, approval, set(DAYS), known_records=known_records
        )


@pytest.mark.parametrize(
    "error_type",
    [
        duckdb.InternalException,
        duckdb.BinderException,
        duckdb.CatalogException,
        duckdb.OutOfMemoryException,
        ValueError,
    ],
)
def test_unexpected_execution_error_is_not_reported_as_unknown(tmp_path, error_type):
    known_records = {}
    with connection(tmp_path) as conn:
        lake, staging, approval, _ = prepare_case(
            conn, tmp_path, known_records=known_records
        )

        class FailingConnection:
            def execute(self, query, *args, **kwargs):
                if query.startswith(
                    "SELECT count(*) FROM stk_factor_bootstrap_coverage_lifecycle"
                ):
                    raise error_type("unexpected execution error")
                return conn.execute(query, *args, **kwargs)

        with pytest.raises(error_type, match="unexpected execution error"):
            prepare(
                FailingConnection(),
                lake,
                staging,
                approval,
                known_records=known_records,
            )


def test_unexpected_error_at_file_read_boundary_still_propagates(tmp_path, monkeypatch):
    known_records = {}
    with connection(tmp_path) as conn:
        lake, staging, approval, _ = prepare_case(
            conn, tmp_path, known_records=known_records
        )
        real_schema = R._schema

        def broken_schema(connection, relation):
            if relation == "stk_factor_bootstrap_coverage_lifecycle":
                raise duckdb.InternalException("unexpected file reader bug")
            return real_schema(connection, relation)

        monkeypatch.setattr(R, "_schema", broken_schema)
        with pytest.raises(
            duckdb.InternalException, match="unexpected file reader bug"
        ):
            prepare(conn, lake, staging, approval, known_records=known_records)


def test_unreadable_basis_is_classified_without_swallowing_other_errors(
    tmp_path, monkeypatch
):
    known_records = {}
    with connection(tmp_path) as conn:
        lake, staging, approval, _ = prepare_case(
            conn, tmp_path, known_records=known_records
        )
        lifecycle = silver_stock_lifecycle_path(lake)
        real_sha = R.factor_file_sha

        def unreadable(path):
            if path == lifecycle:
                raise PermissionError("deliberately unreadable input")
            return real_sha(path)

        monkeypatch.setattr(R, "factor_file_sha", unreadable)
        inputs = prepare(conn, lake, staging, approval, known_records=known_records)
        assert tuple(kinds for _, kinds, _ in inputs.unknown_by_date) == (
            ("lifecycle",),
            ("lifecycle",),
        )


def test_bad_code_reason_is_counted_but_sample_is_bounded(tmp_path):
    known_records = {}
    with connection(tmp_path) as conn:
        lake, staging, approval, _ = prepare_case(
            conn, tmp_path, known_records=known_records
        )
        life = [
            (
                f"BAD{i:02d}",
                str(i),
                "synthetic",
                "SSE",
                None,
                "CNY",
                True,
                "L",
                date(2010, 1, 1),
                None,
            )
            for i in range(25)
        ]
        upstream(conn, lake, days=DAYS, codes=(A,), life=life)
        inputs = prepare(conn, lake, staging, approval, known_records=known_records)
        reason = inputs.unknown_by_date[0][2]
        assert "非法代码25行" in reason
        assert "BAD00" in reason and "BAD19" in reason
        assert "BAD20" not in reason and "BAD24" not in reason


def test_shared_code_predicate_matches_literal_contract_and_rejects_sql(tmp_path):
    with connection(tmp_path) as conn:
        conn.execute("CREATE TEMP TABLE literal_codes(ts_code VARCHAR)")
        conn.executemany(
            "INSERT INTO literal_codes VALUES (?)",
            [
                (v,)
                for v in (
                    "000001.SZ",
                    "600000.SH",
                    "920001.BJ",
                    "000001xSZ",
                    "INVALID",
                    "",
                    None,
                )
            ],
        )
        bad = conn.execute(
            f"SELECT ts_code FROM literal_codes WHERE {stk_factor_pro_invalid_code_sql('ts_code')} ORDER BY ts_code NULLS FIRST"
        ).fetchall()
        assert bad == [(None,), ("",), ("000001xSZ",), ("INVALID",)]
        with pytest.raises(ValueError):
            stk_factor_pro_invalid_code_sql("ts_code); DROP TABLE literal_codes")
