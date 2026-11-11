from datetime import date

import pytest

from orchestrator.defs.asset_guards.stk_factor_pro_readiness import (
    _build_stk_factor_pro_coverage_keys,
    build_stk_factor_pro_coverage_keys,
    compare_stk_factor_pro_coverage_keys,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    SILVER_STOCK_IDENTITY_MAP_SCHEMA,
)
from tests.stk_factor_pro_test_support import DAY, connection

A, B, C = "000001.SZ", "600000.SH", "000002.SZ"


def prepare(
    conn, *, listed=(A, B, C), suspended=(C,), optional=(), actual=(A, C), mappings=None
):
    # Input fields follow the real lifecycle/suspend producer projections and
    # current identity schema. These are deliberately synthetic market facts.
    for name, codes in (
        ("listed", listed),
        ("full_suspend", suspended),
        ("first_day", optional),
        ("actual", actual),
    ):
        conn.execute(f"CREATE TEMP TABLE {name}(trade_date DATE,ts_code VARCHAR)")
        for code in codes:
            conn.execute(f"INSERT INTO {name} VALUES (?,?)", [DAY, code])
    columns = ", ".join(
        f'"{col.name}" {col.type}' for col in SILVER_STOCK_IDENTITY_MAP_SCHEMA
    )
    conn.execute(f"CREATE TEMP TABLE identities({columns})")
    mappings = [(code, code) for code in (A, B, C)] if mappings is None else mappings
    for source, latest in mappings:
        conn.execute(
            "INSERT INTO identities VALUES (?,?,DATE '1990-01-01',NULL,DATE '1990-01-01',NULL,'stock_lifecycle','confirmed','synthetic test',TIMESTAMPTZ '2026-10-16 19:00:00+08')",
            [latest, source],
        )


def coverage(conn):
    return build_stk_factor_pro_coverage_keys(
        conn,
        target_trade_date=DAY,
        listed_relation="listed",
        full_suspend_relation="full_suspend",
        optional_relation="first_day",
        actual_relation="actual",
        identity_relation="identities",
    )


def test_same_count_wrong_stock_does_not_hide_missing(tmp_path):
    with connection(tmp_path) as conn:
        prepare(conn)
        value = coverage(conn)
        assert (
            value.expected_count,
            value.actual_count,
            value.matched_count,
            value.missing_count,
            value.extra_count,
        ) == (2, 2, 1, 1, 1)
        assert conn.execute(
            "SELECT * FROM stk_factor_pro_coverage_missing"
        ).fetchall() == [(DAY, B)]
        assert conn.execute(
            "SELECT * FROM stk_factor_pro_coverage_extra"
        ).fetchall() == [(DAY, C)]


def test_valid_alias_and_duplicate_source_codes_unify_only_for_coverage(tmp_path):
    alias = "000003.SZ"
    with connection(tmp_path) as conn:
        prepare(
            conn,
            listed=(A, B),
            suspended=(),
            actual=(alias, A, B),
            mappings=[(A, A), (B, B), (alias, A)],
        )
        value = coverage(conn)
        assert (
            value.expected_count,
            value.actual_count,
            value.missing_count,
            value.extra_count,
        ) == (2, 2, 0, 0)
        assert conn.execute("SELECT count(*) FROM actual").fetchone()[0] == 3
        assert conn.execute("SELECT ts_code FROM actual ORDER BY 1").fetchall() == [
            (A,),
            (alias,),
            (B,),
        ]


@pytest.mark.parametrize("kind", ["missing", "expired", "not_started", "ambiguous"])
def test_identity_problem_is_unknown_and_clears_previous_differences(tmp_path, kind):
    with connection(tmp_path) as conn:
        prepare(conn)
        assert coverage(conn).missing_count == 1
        if kind == "missing":
            conn.execute("DELETE FROM identities WHERE source_ts_code=?", [B])
        elif kind == "expired":
            conn.execute(
                "UPDATE identities SET valid_to=? WHERE source_ts_code=?", [DAY, B]
            )
        elif kind == "not_started":
            conn.execute(
                "UPDATE identities SET valid_from=DATE '2026-10-17' WHERE source_ts_code=?",
                [B],
            )
        else:
            conn.execute(
                "INSERT INTO identities SELECT * FROM identities WHERE source_ts_code=?",
                [B],
            )
        value = coverage(conn)
        assert (
            value.expected_count is None
            and value.missing_count is None
            and value.actual_count is None
        )
        assert value.identity_unmapped_count == (0 if kind == "ambiguous" else 1)
        assert value.identity_ambiguous_count == (1 if kind == "ambiguous" else 0)
        assert "stk_factor_pro_coverage_missing" not in {
            row[0] for row in conn.execute("SHOW TABLES").fetchall()
        }


def test_full_day_suspension_excluded_intraday_stays_in_listed_input(tmp_path):
    with connection(tmp_path) as conn:
        prepare(conn, suspended=(C,), actual=(A, B))
        assert coverage(conn).missing_count == 0
        # B was intraday suspended: producer excludes it from full_suspend,
        # so its absent source row is still missing, not an excuse for coverage.
        conn.execute("DELETE FROM actual WHERE ts_code=?", [B])
        assert coverage(conn).missing_count == 1


def test_empty_actual_has_real_missing_count_no_fake_green(tmp_path):
    with connection(tmp_path) as conn:
        prepare(conn, actual=())
        value = coverage(conn)
        assert (
            value.expected_count,
            value.actual_count,
            value.missing_count,
            value.extra_count,
        ) == (2, 0, 2, 0)


def test_verified_projections_compute_once_without_repeating_input_audit(tmp_path):
    # Literal producer-schema projections above are already valid; this isolates
    # the internal path rather than claiming a source or Dagster integration.
    with connection(tmp_path) as conn:
        prepare(conn)
        queries = []

        class ObservedConnection:
            def execute(self, query, *args, **kwargs):
                queries.append(str(query))
                return conn.execute(query, *args, **kwargs)

        value = _build_stk_factor_pro_coverage_keys(
            ObservedConnection(),
            target_trade_date=DAY,
            listed_relation="listed",
            full_suspend_relation="full_suspend",
            optional_relation="first_day",
            actual_relation="actual",
            identity_relation="identities",
        )
        assert (
            value.expected_count,
            value.actual_count,
            value.matched_count,
            value.missing_count,
            value.extra_count,
        ) == (2, 2, 1, 1, 1)
        assert not any(
            query.startswith("DESCRIBE") or "trade_date IS DISTINCT FROM" in query
            for query in queries
        )
        assert (
            sum(
                query.startswith("CREATE TEMP TABLE stk_factor_pro_coverage_mapping AS")
                for query in queries
            )
            == 1
        )


@pytest.mark.parametrize(
    "kind", ["wrong_date", "null_code", "sql_identifier", "wrong_type"]
)
def test_invalid_internal_inputs_rejected(tmp_path, kind):
    with connection(tmp_path) as conn:
        prepare(conn)
        if kind == "wrong_date":
            conn.execute("UPDATE actual SET trade_date=DATE '2026-10-15'")
        elif kind == "null_code":
            conn.execute("UPDATE actual SET ts_code=NULL")
        elif kind == "wrong_type":
            conn.execute("ALTER TABLE actual ALTER trade_date TYPE VARCHAR")
        with pytest.raises(ValueError):
            if kind == "sql_identifier":
                build_stk_factor_pro_coverage_keys(
                    conn,
                    target_trade_date=date(2026, 10, 16),
                    listed_relation="listed; DROP TABLE actual",
                    full_suspend_relation="full_suspend",
                    optional_relation="first_day",
                    actual_relation="actual",
                    identity_relation="identities",
                )
            else:
                coverage(conn)


@pytest.mark.parametrize("actual", [(A, B), (A, B, C)])
def test_listing_day_record_is_optional_and_returned_rows_are_preserved(tmp_path, actual):
    # Literal first-day projection: C is listed today; A and B were already listed.
    with connection(tmp_path) as conn:
        prepare(conn, suspended=(), optional=(C,), actual=actual)
        value = coverage(conn)
        assert (
            value.expected_count, value.actual_count, value.matched_count,
            value.missing_count, value.extra_count,
        ) == (2, 2, 2, 0, 0)
        assert conn.execute("SELECT ts_code FROM actual ORDER BY 1").fetchall() == [
            (code,) for code in sorted(actual)
        ]


def test_stock_becomes_required_on_next_trading_day(tmp_path):
    with connection(tmp_path) as conn:
        # C remains listed but no longer appears in today's first-day projection.
        prepare(conn, suspended=(), optional=(), actual=(A, B))
        value = coverage(conn)
        assert (value.expected_count, value.actual_count, value.missing_count) == (3, 2, 1)
        assert conn.execute("SELECT ts_code FROM stk_factor_pro_coverage_missing").fetchall() == [(C,)]


@pytest.mark.parametrize("listed,suspended", [((A, B, C), (C,)), ((A, B), ())])
def test_optional_projection_cannot_exempt_suspended_or_unlisted_codes(
    tmp_path, listed, suspended
):
    with connection(tmp_path) as conn:
        prepare(conn, listed=listed, suspended=suspended, optional=(C,), actual=(A, B, C))
        value = coverage(conn)
        assert (value.expected_count, value.actual_count, value.missing_count, value.extra_count) == (2, 3, 0, 1)
        assert conn.execute("SELECT ts_code FROM stk_factor_pro_coverage_extra").fetchall() == [(C,)]


def test_optional_stock_does_not_hide_missing_required_stock(tmp_path):
    with connection(tmp_path) as conn:
        prepare(conn, suspended=(), optional=(C,), actual=(A, C))
        value = coverage(conn)
        assert (value.expected_count, value.actual_count, value.missing_count, value.extra_count) == (2, 1, 1, 0)
        assert conn.execute("SELECT ts_code FROM stk_factor_pro_coverage_missing").fetchall() == [(B,)]


def test_first_day_alias_uses_same_effective_identity(tmp_path):
    alias = "920827.BJ"
    with connection(tmp_path) as conn:
        prepare(
            conn, suspended=(), optional=(C,), actual=(A, B, alias),
            mappings=[(A, A), (B, B), (C, C), (alias, C)],
        )
        value = coverage(conn)
        assert (value.expected_count, value.actual_count, value.missing_count, value.extra_count) == (2, 2, 0, 0)
        assert conn.execute("SELECT count(*) FROM actual").fetchone()[0] == 3


def test_prepared_expected_keys_reused_for_different_actual_inputs(tmp_path):
    with connection(tmp_path) as conn:
        prepare(conn, suspended=(), optional=(C,), actual=(A, B))
        queries = []

        class ObservedConnection:
            def execute(self, query, *args, **kwargs):
                queries.append(str(query))
                return conn.execute(query, *args, **kwargs)

        observed = ObservedConnection()
        first = _build_stk_factor_pro_coverage_keys(
            observed, target_trade_date=DAY, listed_relation="listed",
            full_suspend_relation="full_suspend", optional_relation="first_day",
            actual_relation="actual", identity_relation="identities",
        )
        conn.execute("INSERT INTO actual VALUES (?,?)", [DAY, C])
        second = compare_stk_factor_pro_coverage_keys(
            observed, target_trade_date=DAY,
            expected_relation="stk_factor_pro_coverage_expected",
            optional_relation="stk_factor_pro_coverage_optional",
            basis_mapping_relation="stk_factor_pro_coverage_mapping",
            actual_relation="actual", identity_relation="identities",
        )
        assert (first.missing_count, first.extra_count) == (0, 0)
        assert (second.expected_count, second.actual_count, second.missing_count, second.extra_count) == (2, 2, 0, 0)
        assert sum(q.startswith("CREATE TEMP TABLE stk_factor_pro_coverage_expected AS") for q in queries) == 1
        assert sum(q.startswith("CREATE TEMP TABLE stk_factor_pro_coverage_mapping AS") for q in queries) == 1
        assert not any(q.startswith("DESCRIBE") for q in queries)


@pytest.mark.parametrize("kind", ["wrong_date", "null_code", "wrong_type"])
def test_first_day_projection_obeys_the_same_input_contract(tmp_path, kind):
    with connection(tmp_path) as conn:
        prepare(conn, suspended=(), optional=(C,), actual=(A, B))
        if kind == "wrong_date":
            conn.execute("UPDATE first_day SET trade_date=DATE '2026-10-15'")
        elif kind == "null_code":
            conn.execute("UPDATE first_day SET ts_code=NULL")
        else:
            conn.execute("ALTER TABLE first_day ALTER trade_date TYPE VARCHAR")
        with pytest.raises(ValueError):
            coverage(conn)


def test_unknown_identities_count_unique_codes_from_basis_and_actual(tmp_path):
    unknown = "300001.SZ"
    with connection(tmp_path) as conn:
        prepare(conn, actual=(A, unknown), mappings=[(A, A), (C, C)])
        value = coverage(conn)
        assert value.expected_count is value.actual_count is None
        assert value.identity_unmapped_count == 2
        assert value.identity_unmapped_sample_codes == (unknown, B)
        assert value.identity_ambiguous_count == 0
