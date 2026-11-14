"""Historical coverage gold cases from the ordinary daily producer contract."""

from datetime import date

import pytest

from orchestrator.audits.stk_factor_pro_coverage import (
    compare_stk_factor_pro_missing_coverage,
    prepare_stk_factor_pro_missing_coverage,
    release_stk_factor_pro_missing_coverage,
    reuse_stk_factor_pro_missing_coverage,
)
from orchestrator.defs.duckdb_sql import silver_stock_daily_select
from tests.stk_factor_pro_test_support import connection

DAY, NEXT = date(2025, 6, 10), date(2025, 6, 11)
A, B, IPO, EXTRA = "000001.SZ", "603003.SH", "601000.SH", "920010.BJ"


def inputs(conn, *, days=(DAY,), life=None, identities=(), quotes=None, actual=()):
    # Producers: SILVER_STOCK_DAILY/LIFECYCLE/IDENTITY_MAP schemas.
    conn.execute("CREATE TEMP TABLE days(trade_date DATE)")
    conn.executemany("INSERT INTO days VALUES (?)", [(d,) for d in days])
    conn.execute("CREATE TEMP TABLE life(ts_code VARCHAR,list_date DATE)")
    if life is None:
        life = ((A, date(2000, 1, 1)), (B, date(2012, 8, 17)))
    if life:
        conn.executemany("INSERT INTO life VALUES (?,?)", life)
    conn.execute(
        "CREATE TEMP TABLE identities(latest_ts_code VARCHAR,source_ts_code VARCHAR,valid_from DATE,valid_to DATE)"
    )
    if identities:
        conn.executemany("INSERT INTO identities VALUES (?,?,?,?)", identities)
    conn.execute("CREATE TEMP TABLE quotes(trade_date DATE,ts_code VARCHAR)")
    if quotes is None:
        quotes = ((DAY, A), (DAY, B))
    if quotes:
        conn.executemany("INSERT INTO quotes VALUES (?,?)", quotes)
    conn.execute("CREATE TEMP TABLE actual(trade_date DATE,ts_code VARCHAR)")
    if actual:
        conn.executemany("INSERT INTO actual VALUES (?,?)", actual)


def prepare(conn):
    return prepare_stk_factor_pro_missing_coverage(
        conn,
        dates_relation="days",
        quote_relation="quotes",
        lifecycle_relation="life",
        identity_relation="identities",
        actual_relation="actual",
    )


def observed(conn, relations):
    return (
        conn.execute(
            f"SELECT * FROM {relations['daily_relation']} ORDER BY trade_date"
        ).fetchall(),
        conn.execute(
            f"SELECT * FROM {relations['missing_relation']} ORDER BY trade_date,ts_code"
        ).fetchall(),
    )


@pytest.mark.parametrize("extra", [EXTRA, "UNRELATED", "T600018.SH", None])
def test_extra_records_do_not_block_required_codes(tmp_path, extra):
    with connection(tmp_path) as conn:
        inputs(conn, actual=((DAY, A), (DAY, B), (DAY, extra)))
        assert observed(conn, prepare(conn)) == ([(DAY, 2, 2, 0)], [])
        release_stk_factor_pro_missing_coverage(conn)
        assert not conn.execute(
            "SELECT table_name FROM duckdb_tables() WHERE table_name LIKE 'stk_factor_pro_missing_audit_%'"
        ).fetchall()


def test_same_count_does_not_hide_missing_required_code(tmp_path):
    with connection(tmp_path) as conn:
        inputs(conn, actual=((DAY, A), (DAY, EXTRA)))
        assert observed(conn, prepare(conn)) == ([(DAY, 2, 1, 1)], [(DAY, B)])


@pytest.mark.parametrize(
    "code,day",
    [
        ("002260.SZ", date(2019, 5, 15)),
        ("603897.SH", date(2025, 11, 4)),
        ("603056.SH", date(2026, 1, 12)),
        ("605028.SH", date(2026, 1, 13)),
        ("688005.SH", date(2026, 1, 15)),
        ("603616.SH", date(2026, 1, 22)),
        ("603159.SH", date(2026, 6, 16)),
        ("002731.SZ", date(2026, 7, 6)),
        ("601238.SH", date(2026, 9, 15)),
    ],
)
def test_no_daily_bar_does_not_require_technical_factor(tmp_path, code, day):
    # LLD 22.30: all lack ordinary daily bars; the last eight have saved S/R.
    with connection(tmp_path) as conn:
        inputs(
            conn,
            days=(day,),
            life=((A, date(2000, 1, 1)), (code, date(2008, 1, 1))),
            quotes=((day, A),),
            actual=((day, A),),
        )
        assert observed(conn, prepare(conn)) == ([(day, 1, 1, 0)], [])


@pytest.mark.parametrize("present", [False, True])
def test_actual_resume_with_daily_bar_requires_factor(tmp_path, present):
    # 603003.SH / DAY: its actual daily bar decides inclusion, not S/R flags.
    with connection(tmp_path) as conn:
        inputs(conn, actual=((DAY, A), (DAY, B)) if present else ((DAY, A),))
        assert observed(conn, prepare(conn)) == (
            [(DAY, 2, 2 if present else 1, 0 if present else 1)],
            [] if present else [(DAY, B)],
        )


def test_ipo_first_day_optional_next_daily_bar_required(tmp_path):
    with connection(tmp_path) as conn:
        inputs(
            conn,
            days=(DAY, NEXT),
            life=((A, date(2000, 1, 1)), (IPO, DAY)),
            quotes=((DAY, A), (DAY, IPO), (NEXT, A), (NEXT, IPO)),
            actual=((DAY, A), (NEXT, A)),
        )
        assert observed(conn, prepare(conn)) == (
            [(DAY, 1, 1, 0), (NEXT, 2, 1, 1)],
            [(NEXT, IPO)],
        )


@pytest.mark.parametrize("valid_to,matched", [(None, 2), (DAY, 1)])
def test_only_effective_alias_covers_daily_bar(tmp_path, valid_to, matched):
    with connection(tmp_path) as conn:
        inputs(
            conn,
            identities=((B, "600018.SH", date(2010, 1, 1), valid_to),),
            actual=((DAY, A), (DAY, "600018.SH")),
        )
        assert observed(conn, prepare(conn)) == (
            [(DAY, 2, matched, 2 - matched)],
            [] if matched == 2 else [(DAY, B)],
        )


def test_quote_identity_can_map_to_later_listed_standard(tmp_path):
    with connection(tmp_path) as conn:
        inputs(
            conn,
            life=((A, date(2000, 1, 1)), (B, date(2012, 8, 17)), (IPO, NEXT)),
            identities=((IPO, B, date(2012, 8, 17), None),),
            actual=((DAY, A), (DAY, IPO)),
        )
        assert observed(conn, prepare(conn)) == ([(DAY, 2, 2, 0)], [])


def test_missing_lifecycle_does_not_discard_daily_bar(tmp_path):
    with connection(tmp_path) as conn:
        inputs(conn, life=((A, date(2000, 1, 1)),), actual=((DAY, A),))
        assert observed(conn, prepare(conn)) == ([(DAY, 2, 1, 1)], [(DAY, B)])


def test_only_requested_dates_and_distinct_keys_count(tmp_path):
    with connection(tmp_path) as conn:
        inputs(
            conn,
            quotes=((DAY, A), (DAY, A), (NEXT, B)),
            actual=((DAY, A), (DAY, A), (NEXT, B)),
        )
        assert observed(conn, prepare(conn)) == ([(DAY, 1, 1, 0)], [])


def test_recomparison_reuses_prepared_quote_codes(tmp_path):
    with connection(tmp_path) as conn:
        inputs(conn, actual=((DAY, A),))
        assert observed(conn, prepare(conn)) == ([(DAY, 2, 1, 1)], [(DAY, B)])
        for name in ("quotes", "life", "identities"):
            conn.execute(f"DROP TABLE {name}")
        conn.execute("INSERT INTO actual VALUES (?,?)", [DAY, B])
        relations = compare_stk_factor_pro_missing_coverage(
            conn, dates_relation="days", actual_relation="actual"
        )
        assert observed(conn, relations) == ([(DAY, 2, 2, 0)], [])


@pytest.mark.parametrize("new_present", [False, True])
def test_reuse_keeps_real_missing_and_checks_only_new_codes(tmp_path, new_present):
    with connection(tmp_path) as conn:
        inputs(conn, quotes=((DAY, A), (DAY, B), (DAY, IPO)))
        prepare(conn)
        conn.execute("CREATE TABLE previous_expected(trade_date DATE,ts_code VARCHAR)")
        conn.executemany(
            "INSERT INTO previous_expected VALUES (?,?)", [(DAY, A), (DAY, B)]
        )
        conn.execute(
            "CREATE TABLE previous_missing AS SELECT * FROM previous_expected WHERE ts_code=?",
            [B],
        )
        reuse = reuse_stk_factor_pro_missing_coverage(
            conn,
            dates_relation="days",
            previous_expected_relation="previous_expected",
            previous_missing_relation="previous_missing",
        )
        assert conn.execute(f"SELECT * FROM {reuse['reused_relation']}").fetchall() == [
            (DAY, A)
        ]
        assert conn.execute(
            f"SELECT * FROM {reuse['needs_check_relation']}"
        ).fetchall() == [(DAY, IPO)]
        assert conn.execute(f"SELECT * FROM {reuse['counts_relation']}").fetchall() == [
            (DAY, 1, 1)
        ]
        conn.execute(f"INSERT INTO actual SELECT * FROM {reuse['reused_relation']}")
        if new_present:
            conn.execute("INSERT INTO actual VALUES (?,?)", [DAY, IPO])
        relations = compare_stk_factor_pro_missing_coverage(
            conn, dates_relation="days", actual_relation="actual"
        )
        assert observed(conn, relations) == (
            [(DAY, 3, 2 if new_present else 1, 1 if new_present else 2)],
            [(DAY, B)] if new_present else [(DAY, IPO), (DAY, B)],
        )


def test_old_false_missing_without_quote_is_not_carried_forward(tmp_path):
    with connection(tmp_path) as conn:
        inputs(conn, quotes=((DAY, A),))
        prepare(conn)
        conn.execute(
            "CREATE TABLE previous_expected AS SELECT * FROM (VALUES (?,?),(?,?)) v(trade_date,ts_code)",
            [DAY, A, DAY, B],
        )
        conn.execute(
            "CREATE TABLE previous_missing AS SELECT * FROM previous_expected WHERE ts_code=?",
            [B],
        )
        reuse = reuse_stk_factor_pro_missing_coverage(
            conn,
            dates_relation="days",
            previous_expected_relation="previous_expected",
            previous_missing_relation="previous_missing",
        )
        assert (
            conn.execute(f"SELECT * FROM {reuse['needs_check_relation']}").fetchall()
            == []
        )
        conn.execute(f"INSERT INTO actual SELECT * FROM {reuse['reused_relation']}")
        relations = compare_stk_factor_pro_missing_coverage(
            conn, dates_relation="days", actual_relation="actual"
        )
        assert observed(conn, relations) == ([(DAY, 1, 1, 0)], [])


def test_real_daily_producer_contract(tmp_path):
    with connection(tmp_path) as conn:
        raw, lifecycle = tmp_path / "raw.parquet", tmp_path / "life.parquet"
        conn.execute(
            "CREATE TABLE raw AS SELECT * FROM (VALUES ('000001.SZ','20250610'),('601000.SH','20250610'),('920010.BJ','20211112')) v(ts_code,trade_date)"
        )
        conn.execute(
            'COPY (SELECT *,1.0 AS "open",1.0 AS "high",1.0 AS "low",1.0 AS "close",1.0 pre_close,0.0 AS "change",0.0 pct_chg,1.0 vol,1.0 amount FROM raw) TO ? (FORMAT PARQUET)',
            [str(raw)],
        )
        conn.execute(
            "COPY (SELECT * FROM (VALUES ('000001.SZ',DATE '2000-01-01',NULL::DATE,TRUE),('601000.SH',DATE '2025-06-10',NULL::DATE,TRUE),('920010.BJ',DATE '2020-07-27',NULL::DATE,TRUE)) v(ts_code,list_date,delist_date,is_cny_stock)) TO ? (FORMAT PARQUET)",
            [str(lifecycle)],
        )
        inputs(
            conn,
            quotes=(),
            life=((A, date(2000, 1, 1)), (IPO, DAY)),
            actual=((DAY, A),),
        )
        conn.execute(
            f"INSERT INTO quotes SELECT trade_date,ts_code FROM ({silver_stock_daily_select(raw, lifecycle)})"
        )
        assert conn.execute("DESCRIBE quotes").fetchall()[0][:2] == (
            "trade_date",
            "DATE",
        )
        assert conn.execute("SELECT * FROM quotes ORDER BY ts_code").fetchall() == [
            (DAY, A),
            (DAY, IPO),
        ]
        assert observed(conn, prepare(conn)) == ([(DAY, 1, 1, 0)], [])
