from dataclasses import replace

import duckdb
import pytest

from scripts.research.index_market.chan.stock_chan_rank import (
    SPEC, connection, endpoint_source_sql, execute, historical_pool_sql, match_controls,
)


def test_shsz_survivors_exclude_delisted_even_when_listed_at_signal():
    with duckdb.connect(':memory:') as c:
        c.execute('''CREATE TABLE life(ts_code VARCHAR,name VARCHAR,exchange VARCHAR,
            list_date DATE,delist_date DATE,is_cny_stock BOOLEAN)''')
        c.execute("""INSERT INTO life VALUES
            ('600000.SH','a','SSE','2000-01-01','2026-06-01',true),
            ('000001.SZ','b','SZSE','2000-01-01',NULL,true),
            ('920001.BJ','c','BSE','2000-01-01',NULL,true),
            ('900001.SH','d','SSE','2000-01-01',NULL,false),
            ('600001.SH','e','SSE','2026-03-01',NULL,true),
            ('600002.SH','f','SSE','2000-01-01','2026-02-26',true),
            ('600003.SH','g','SSE','2000-01-01','2026-09-12',true),
            ('600004.SH','h','SSE','2000-01-01','2026-09-13',true)""")
        rows = c.execute(historical_pool_sql(), ['2026-02-26']*2+[SPEC.universe_asof]).fetchall()
    assert {r[0] for r in rows} == {'000001.SZ','600004.SH'}


def test_fixed_matching_ties_missing_and_no_replacement():
    rows = [dict(ts_code=code,prior_amount=amt) for code,amt in
            [('a',10),('b',10),('c',None),('d',11),('e',9),('f',100),('g',8)]]
    pairs = match_controls(rows, 3)
    assert [p['control'] for p in pairs] == ['d','e',None]
    assert pairs[-1]['reason'] == 'prior_history_unavailable'


def test_control_distance_does_not_use_future_gain():
    rows = [dict(ts_code=str(i), prior_amount=i*10, gross_change=1-i) for i in range(4)]
    expected = match_controls(rows, 2)
    for row in rows:
        row['gross_change'] *= -100
    assert match_controls(rows, 2) == expected


def test_rank_rejects_insufficient_and_changed_scope(tmp_path):
    with pytest.raises(ValueError, match='insufficient'):
        match_controls([], 50)
    for spec in (replace(SPEC,start='2010-01-01'), replace(SPEC,exchanges=('BSE',)),
                 replace(SPEC,top_n=5), replace(SPEC,universe_asof='2026-02-26')):
        with pytest.raises(ValueError, match='unapproved'):
            execute(tmp_path/'out', spec)


def test_endpoint_uses_first_silver5_not_silver30_or_last_bar(tmp_path):
    # Generated Parquet stays in pytest isolation, never touches the real Lake.
    prices, factors = tmp_path/'prices.parquet', tmp_path/'factors.parquet'
    with duckdb.connect(':memory:') as c:
        c.execute('''CREATE TABLE s(ts_code VARCHAR,trade_time TIMESTAMP,trade_date DATE,open DOUBLE,freq INTEGER)''')
        c.execute("""INSERT INTO s VALUES
            ('a','2026-02-26 13:05:00','2026-02-26',10,5),
            ('a','2026-02-26 13:30:00','2026-02-26',20,5),
            ('a','2026-02-26 13:30:00','2026-02-26',30,30),
            ('a','2026-02-26 09:35:00','2026-02-26',40,5)""")
        c.execute('COPY s TO ? (FORMAT PARQUET)', [str(prices)])
        c.execute("COPY (SELECT 'a' AS ts_code, DATE '2026-02-26' AS trade_date, 2 AS adj_factor) TO ? (FORMAT PARQUET)", [str(factors)])
        c.execute(endpoint_source_sql(), [[str(prices)],[str(factors)]])
        rows = c.execute('SELECT CAST(trade_time AS VARCHAR),adjusted,multiplicity FROM endpoint_source').fetchall()
    assert rows == [('2026-02-26 13:30:00',20,1)]


def test_reader_allowlist_set_before_access_disabled_and_locked(tmp_path):
    allowed = tmp_path/'allowed.csv'
    blocked = tmp_path/'blocked.csv'
    allowed.write_text('value\n1\n')
    blocked.write_text('value\n2\n')
    with connection([allowed]) as con:
        assert con.execute('SELECT value FROM read_csv_auto(?)', [str(allowed)]).fetchone() == (1,)
        with pytest.raises(duckdb.Error):
            con.execute('SELECT value FROM read_csv_auto(?)', [str(blocked)])
        with pytest.raises(duckdb.Error):
            con.execute('SET enable_external_access=true')
