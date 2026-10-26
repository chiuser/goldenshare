"""Earliest dates follow LLD 5.1.1; fixtures contain independent Raw keys only."""

from datetime import date

import pytest

from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.io.stk_factor_pro_history import (
    resolve_stk_factor_pro_history_starts,
)
from orchestrator.defs.paths import raw_stk_factor_pro_path
from orchestrator.defs.run_contracts.stk_factor_pro import StkFactorProHistoryStart
from tests.stk_factor_pro_history_test_support import connection, roots

T, OLD, NEW = date(2026, 10, 16), date(2015, 1, 5), date(2020, 1, 6)
A, B, C = "000001.SZ", "600000.SH", "000002.SZ"


class CountConnection:
    def __init__(self, conn):
        self.conn, self.aggregates = conn, []

    def execute(self, sql, parameters=None):
        if "min(CAST(try_strptime" in sql:
            self.aggregates.append((sql, parameters))
        return (
            self.conn.execute(sql, parameters)
            if parameters is not None
            else self.conn.execute(sql)
        )


def write_keys(conn, lake, day, codes=(A, B), raw_day=None):
    path = raw_stk_factor_pro_path(lake, day.isoformat())
    path.parent.mkdir(parents=True, exist_ok=True)
    conn.execute(
        copy_query_to_parquet(
            "SELECT unnest(?::VARCHAR[]) AS ts_code, ?::VARCHAR AS trade_date", path
        ),
        [list(codes), raw_day or day.strftime("%Y%m%d")],
    )


def resolve(conn, lake, *, known=(), dates=(), codes=(A, B, C), cancel=lambda: None):
    return resolve_stk_factor_pro_history_starts(
        conn,
        lake_root=lake,
        target_trade_date=T,
        codes=codes,
        known_starts=known,
        approved_raw_dates=dates,
        check_cancel=cancel,
    )


def test_single_bounded_aggregate_for_unknown_codes_and_earliest_known_kept(tmp_path):
    lake, _ = roots(tmp_path)
    with connection(tmp_path) as actual:
        conn = CountConnection(actual)
        write_keys(actual, lake, OLD, (A, B))
        write_keys(actual, lake, NEW, (A, B))
        known = (StkFactorProHistoryStart(A, OLD, 2, OLD),)
        values = resolve(conn, lake, known=known, dates=(NEW, OLD))
        assert values == (
            StkFactorProHistoryStart(A, OLD, 2, OLD),
            StkFactorProHistoryStart(C, None, None, None),
            StkFactorProHistoryStart(B, OLD, 1, OLD),
        )
        assert len(conn.aggregates) == 1
        assert conn.aggregates[0][1][-1] == [C, B]
        assert actual.execute("SHOW TABLES").fetchall() == []


def test_trusted_known_dates_do_not_scan_irrelevant_missing_files(tmp_path):
    lake, _ = roots(tmp_path)
    with connection(tmp_path) as actual:
        conn = CountConnection(actual)
        known = (StkFactorProHistoryStart(A, OLD, 1, OLD),)
        assert resolve(conn, lake, known=known, dates=(NEW,), codes=(A,)) == known
        assert conn.aggregates == []


def test_no_approved_range_or_no_rows_stays_unknown(tmp_path):
    lake, _ = roots(tmp_path)
    with connection(tmp_path) as actual:
        assert resolve(actual, lake, codes=(C,)) == (
            StkFactorProHistoryStart(C, None, None, None),
        )
        write_keys(actual, lake, OLD, (A,))
        assert resolve(actual, lake, codes=(C,), dates=(OLD,)) == (
            StkFactorProHistoryStart(C, None, None, None),
        )


@pytest.mark.parametrize("raw_day", ["20150106", "20150230", "2015-01-05", ""])
def test_bad_raw_date_does_not_create_later_or_fabricated_start(tmp_path, raw_day):
    lake, _ = roots(tmp_path)
    with connection(tmp_path) as actual:
        write_keys(actual, lake, OLD, raw_day=raw_day if raw_day else "bad")
        with pytest.raises(ValueError, match="日期"):
            resolve(actual, lake, dates=(OLD,))


def test_missing_approved_file_cannot_silently_shorten_history(tmp_path):
    lake, _ = roots(tmp_path)
    with connection(tmp_path) as actual, pytest.raises(ValueError, match="文件缺失"):
        write_keys(actual, lake, NEW)
        resolve(actual, lake, dates=(OLD, NEW))


@pytest.mark.parametrize(
    "kind",
    ["code_duplicate", "date_duplicate", "date_text", "future", "known_duplicate"],
)
def test_start_input_contract_is_closed(tmp_path, kind):
    lake, _ = roots(tmp_path)
    options = {}
    if kind == "code_duplicate":
        options["codes"] = (A, A)
    elif kind == "date_duplicate":
        options["dates"] = (OLD, OLD)
    elif kind == "date_text":
        options["dates"] = ("2015-01-05",)
    elif kind == "future":
        future = date(2026, 10, 17)
        options["known"] = (StkFactorProHistoryStart(A, future, 1, future),)
    else:
        item = StkFactorProHistoryStart(A, OLD, 1, OLD)
        options["known"] = (item, item)
    with connection(tmp_path) as actual, pytest.raises((ValueError, TypeError)):
        resolve(actual, lake, **options)
