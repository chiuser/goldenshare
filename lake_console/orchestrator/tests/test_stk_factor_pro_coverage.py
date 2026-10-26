from datetime import date

import pytest

from orchestrator.defs.asset_guards.stk_factor_pro_readiness import (
    build_stk_factor_pro_coverage_keys,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    SILVER_STOCK_IDENTITY_MAP_SCHEMA,
)
from tests.stk_factor_pro_test_support import DAY, connection

A, B, C = "000001.SZ", "600000.SH", "000002.SZ"


def prepare(conn, *, listed=(A, B, C), suspended=(C,), actual=(A, C), mappings=None):
    # Input fields follow the real lifecycle/suspend producer projections and
    # current identity schema. These are deliberately synthetic market facts.
    for name, codes in (
        ("listed", listed),
        ("full_suspend", suspended),
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
                    actual_relation="actual",
                    identity_relation="identities",
                )
            else:
                coverage(conn)
