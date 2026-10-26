"""Invalid basis is unknown; real execution errors still fail (LLD 17.8.4).

Schemas and basic rows come from the existing real-producer-schema fixtures.
Only the named corrupt basis cells are intentionally invalid. Expected dates,
codes, counts and unknown kinds below are independent literals.
"""

from datetime import date, timedelta

import duckdb
import pytest

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


def prepare_case(conn, tmp_path):
    counts = ((DAYS[0], 1), (DAYS[1], 1))
    lake, staging, approval, identity = approval_fixture(conn, tmp_path, counts=counts)
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


def prepare(conn, lake, staging, approval):
    return B.prepare_stk_factor_pro_bootstrap_coverage_month(
        conn,
        lake_root=lake,
        staging_root=staging,
        approval=approval,
        month=approval.month_limits[0],
    )


def run_case(conn, lake, staging, approval, remote):
    return H._run_stk_factor_pro_bootstrap(
        conn,
        lake_root=lake,
        staging_root=staging,
        operation_id=approval.operation_id,
        instance=Instance(),
        prod_postgres=remote,
    )


def assert_days_faithful(conn, lake, staging, approval, unknown_days):
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
    with connection(tmp_path) as conn:
        lake, staging, approval, remote = prepare_case(conn, tmp_path)
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
        inputs = prepare(conn, lake, staging, approval)
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
        assert identity.valid is (bad == "lifecycle")
        assert any(
            "INVALID" in reason and "1行" in reason
            for _, _, reason in inputs.unknown_by_date
        )
        summary = run_case(conn, lake, staging, approval, remote)
        assert (
            summary.verified_source_rows
            == summary.verified_raw_rows
            == summary.verified_silver_rows
            == 2
        )
        assert summary.total_missing_count is None
        assert_days_faithful(conn, lake, staging, approval, set(DAYS))


def test_bad_suspension_affects_only_its_day(tmp_path):
    with connection(tmp_path) as conn:
        lake, staging, approval, remote = prepare_case(conn, tmp_path)
        # Add one deliberately malformed row to the first day's real 4-column file.
        path = silver_stock_suspend_daily_path(lake, DAYS[0].isoformat())
        conn.execute(
            f"CREATE TEMP TABLE bad_suspend AS SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
        )
        conn.execute("INSERT INTO bad_suspend VALUES ('INVALID',?,'S',NULL)", [DAYS[0]])
        conn.execute("COPY bad_suspend TO ? (FORMAT PARQUET)", [str(path)])
        inputs = prepare(conn, lake, staging, approval)
        assert tuple((d, kinds) for d, kinds, _ in inputs.unknown_by_date) == (
            (DAYS[0], ("suspend",)),
        )
        run_case(conn, lake, staging, approval, remote)
        assert_days_faithful(conn, lake, staging, approval, {DAYS[0]})


def test_valid_inputs_import_both_days_and_do_not_become_unknown(tmp_path):
    with connection(tmp_path) as conn:
        lake, staging, approval, remote = prepare_case(conn, tmp_path)
        assert prepare(conn, lake, staging, approval).unknown_by_date == ()
        summary = run_case(conn, lake, staging, approval, remote)
        assert summary.all_coverage_determined and summary.total_missing_count == 0
        assert_days_faithful(conn, lake, staging, approval, set())


@pytest.mark.parametrize("bad", ["missing", "schema", "parquet"])
def test_bad_basis_file_keeps_legal_import_and_only_lifecycle_unknown(tmp_path, bad):
    with connection(tmp_path) as conn:
        lake, staging, approval, remote = prepare_case(conn, tmp_path)
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
        inputs = prepare(conn, lake, staging, approval)
        assert tuple(kinds for _, kinds, _ in inputs.unknown_by_date) == (
            ("lifecycle",),
            ("lifecycle",),
        )
        assert next(b for b in inputs.basis_files if b.kind == "identity").valid
        run_case(conn, lake, staging, approval, remote)
        assert_days_faithful(conn, lake, staging, approval, set(DAYS))


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
    with connection(tmp_path) as conn:
        lake, staging, approval, _ = prepare_case(conn, tmp_path)

        class FailingConnection:
            def execute(self, query, *args, **kwargs):
                if query.startswith(
                    "SELECT count(*) FROM stk_factor_bootstrap_coverage_lifecycle"
                ):
                    raise error_type("unexpected execution error")
                return conn.execute(query, *args, **kwargs)

        with pytest.raises(error_type, match="unexpected execution error"):
            prepare(FailingConnection(), lake, staging, approval)


def test_unexpected_error_at_file_read_boundary_still_propagates(tmp_path, monkeypatch):
    with connection(tmp_path) as conn:
        lake, staging, approval, _ = prepare_case(conn, tmp_path)
        real_schema = B._schema

        def broken_schema(connection, relation):
            if "stock_lifecycle" in relation:
                raise duckdb.InternalException("unexpected file reader bug")
            return real_schema(connection, relation)

        monkeypatch.setattr(B, "_schema", broken_schema)
        with pytest.raises(
            duckdb.InternalException, match="unexpected file reader bug"
        ):
            prepare(conn, lake, staging, approval)


def test_unreadable_basis_is_classified_without_swallowing_other_errors(
    tmp_path, monkeypatch
):
    with connection(tmp_path) as conn:
        lake, staging, approval, _ = prepare_case(conn, tmp_path)
        lifecycle = silver_stock_lifecycle_path(lake)
        real_sha = B.factor_file_sha

        def unreadable(path):
            if path == lifecycle:
                raise PermissionError("deliberately unreadable input")
            return real_sha(path)

        monkeypatch.setattr(B, "factor_file_sha", unreadable)
        inputs = prepare(conn, lake, staging, approval)
        assert tuple(kinds for _, kinds, _ in inputs.unknown_by_date) == (
            ("lifecycle",),
            ("lifecycle",),
        )


def test_bad_code_reason_is_counted_but_sample_is_bounded(tmp_path):
    with connection(tmp_path) as conn:
        lake, staging, approval, _ = prepare_case(conn, tmp_path)
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
        inputs = prepare(conn, lake, staging, approval)
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
