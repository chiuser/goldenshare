"""Literal bad-data cases exercise the shared production predicates."""

import duckdb
import pytest

from orchestrator.defs.stock_factor_price_checks import (
    audit_adj_factor_candidate_rules,
    daily_qfq_contract_rule_counts,
    minute_qfq_counts_sql,
)


@pytest.mark.parametrize("sql,expected",[
    ("SELECT '688689.SH'::VARCHAR ts_code,DATE '2026-06-29' trade_date",{"partition_date_mismatch_count":0,"null_key_count":0,"duplicate_key_count":0}),
    ("SELECT NULL::VARCHAR ts_code,DATE '2026-06-28' trade_date",{"partition_date_mismatch_count":1,"null_key_count":1,"duplicate_key_count":0}),
    ("SELECT '688689.SH'::VARCHAR ts_code,DATE '2026-06-29' trade_date FROM range(2)",{"partition_date_mismatch_count":0,"null_key_count":0,"duplicate_key_count":1}),
])
def test_daily_literals(tmp_path,sql,expected):
    with duckdb.connect() as c:
        path=tmp_path/"daily.parquet";c.execute("COPY ("+sql+") TO ? (FORMAT PARQUET)",[str(path)])
        assert daily_qfq_contract_rule_counts(c,path,"2026-06-29")==expected


def test_factor_current_listing_and_source_precision(tmp_path):
    with duckdb.connect() as c:
        factor=tmp_path/"factor.parquet";life=tmp_path/"life.parquet"
        c.execute("COPY (SELECT '688689.SH'::VARCHAR ts_code,DATE '2026-06-29' trade_date,1.0597::DOUBLE adj_factor) TO ? (FORMAT PARQUET)",[str(factor)])
        c.execute("COPY (SELECT '688689.SH'::VARCHAR ts_code,DATE '2021-01-27' list_date,NULL::DATE delist_date,true is_cny_stock,'D'::VARCHAR list_status) TO ? (FORMAT PARQUET)",[str(life)])
        counts=audit_adj_factor_candidate_rules(c,factor,"2026-06-29",raw=False,lifecycle_path=life)
        assert counts=={"rows":1,"partition_mismatch":0,"nonpositive_factor":0,"duplicate_keys":0,"lifecycle_invalid":1,"coverage_missing":0,"coverage_unexpected":1}


def test_minute_batch_rules_equal_scalar_and_detect_bad_path_time():
    with duckdb.connect() as c:
        c.execute("CREATE TABLE bars AS SELECT '688689.SH'::VARCHAR ts_code,1::INTEGER freq,DATE '2026-06-29' trade_date,TIMESTAMP '2026-06-29 09:30:00' trade_time,10.0::DOUBLE open,11.0::DOUBLE high,9.0::DOUBLE low,10.0::DOUBLE AS close,100.0::DOUBLE vol,1000.0::DOUBLE amount,'SSE'::VARCHAR exchange,'/gold/ts_code=688689.SH/year=2026/part-000.parquet'::VARCHAR filename")
        args={"gold_source": "bars","freq": 1}
        assert c.execute(minute_qfq_counts_sql(**args,partition_key="2026-06-29")).fetchone()==(1,0,0,0)
        assert c.execute(minute_qfq_counts_sql(**args,partition_key=["2026-06-29","2026-06-30"])).fetchone()==(1,0,0,0)
        c.execute("UPDATE bars SET trade_time=TIMESTAMP '2026-06-30 09:30:00',high=8")
        assert c.execute(minute_qfq_counts_sql(**args,partition_key=["2026-06-29"])).fetchone()==(1,1,0,1)


@pytest.mark.parametrize("keys,today,expected",[
    ({"2026-06-29"},"2026-10-14",True),
    (set(),"2026-10-14",False),
    ({"2026-06-29"},"2026-06-28",False),
])
def test_frozen_partition_evidence_uses_formal_rule(keys,today,expected):
    from orchestrator.defs.stock_factor_price_checks import (
        adj_factor_partition_allowed_status,
    )
    assert adj_factor_partition_allowed_status(partition_key="2026-06-29",registered_keys=keys,today=today)["passed"] is expected


def test_minute_basic_counts_do_not_replace_identity_coverage():
    from orchestrator.defs.stock_factor_price_checks import (
        minute_qfq_identity_coverage_counts_sql,
    )
    source="(SELECT '688689.SH'::VARCHAR ts_code,1::INTEGER freq,DATE '2026-06-29' trade_date,TIMESTAMP '2026-06-29 09:30:00' trade_time,10.0::DOUBLE open,11.0::DOUBLE high,9.0::DOUBLE low,10.0::DOUBLE AS close,1.0::DOUBLE vol,1.0::DOUBLE amount,'WRONG'::VARCHAR exchange,'/gold/ts_code=688689.SH/year=2026/part.parquet'::VARCHAR filename)"
    expected="SELECT '688689.SH'::VARCHAR ts_code,TIMESTAMP '2026-06-29 09:30:00' trade_time,'SSE'::VARCHAR exchange"
    with duckdb.connect() as c:
        assert c.execute(minute_qfq_counts_sql(gold_source=source,partition_key='2026-06-29',freq=1)).fetchone()==(1,0,0,0)
        assert c.execute(minute_qfq_identity_coverage_counts_sql(gold_source=source,partition_key=['2026-06-29'],expected_identity_sql=expected)).fetchone()==(0,0,1)
        assert c.execute(minute_qfq_identity_coverage_counts_sql(gold_source=source,partition_key='2026-06-29',expected_identity_sql=expected)).fetchone()==(0,0,1)
