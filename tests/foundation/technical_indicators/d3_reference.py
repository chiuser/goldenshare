"""Independent D3 fixture and reference SQL, never production SQL templates.

The input cents expression is the reproducible rising/falling literal from LLD
21.4. Recursive HUGEINT reference uses original prices and rational EMA/K/D,
not the product's offset, powers, segment coefficients or shared helpers.
Every operation is called and charged by the finite D3 session fixture.
"""

from datetime import date
import json
from zoneinfo import ZoneInfo


MA_PERIODS = (5, 10, 20, 30, 60, 90, 250)
DAILY_DATES = (
    "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09",
    "2026-01-12", "2026-01-13", "2026-01-14", "2026-01-15", "2026-01-16",
    "2026-01-19", "2026-01-20", "2026-01-21", "2026-01-22", "2026-01-23",
    "2026-01-26", "2026-01-27", "2026-01-28", "2026-01-29", "2026-01-30", "2026-02-02",
)


MACD_REFERENCE = """WITH RECURSIVE p AS (SELECT CAST(? AS BIGINT) AS fast, CAST(? AS BIGINT) AS slow,
                           CAST(? AS BIGINT) AS signal),
b AS MATERIALIZED (SELECT seq,cents::HUGEINT*10000000000000000::HUGEINT AS x
                   FROM d3_bars WHERE seq<=?),
r(seq,ef,es,dif,dea) AS (
 SELECT seq,x,x,0::HUGEINT,0::HUGEINT FROM b WHERE seq=1
 UNION ALL
 SELECT b.seq,e.ef,e.es,e.ef-e.es,
        ((p.signal-1)::HUGEINT*r.dea+2::HUGEINT*(e.ef-e.es))//(p.signal+1)
 FROM r JOIN b ON b.seq=r.seq+1 CROSS JOIN p
 CROSS JOIN LATERAL (
   SELECT ((p.fast-1)::HUGEINT*r.ef+2::HUGEINT*b.x)//(p.fast+1) AS ef,
          ((p.slow-1)::HUGEINT*r.es+2::HUGEINT*b.x)//(p.slow+1) AS es
 ) e
)
SELECT seq,dif::DOUBLE/1e18 AS dif,dea::DOUBLE/1e18 AS dea,
       (2::HUGEINT*(dif-dea))::DOUBLE/1e18 AS hist FROM r ORDER BY seq
"""


KDJ_REFERENCE = """WITH RECURSIVE windows AS MATERIALIZED (
 SELECT seq,cents,
        max(cents+100) OVER (ORDER BY seq ROWS BETWEEN 8 PRECEDING AND CURRENT ROW) AS hi,
        min(cents-100) OVER (ORDER BY seq ROWS BETWEEN 8 PRECEDING AND CURRENT ROW) AS lo
 FROM d3_bars
), b AS MATERIALIZED (
 SELECT seq,CASE WHEN hi=lo THEN 50000000000000000000::HUGEINT
                ELSE ((cents-lo)::HUGEINT*100::HUGEINT*1000000000000000000::HUGEINT)//(hi-lo)
           END AS rsv FROM windows
), r(seq,k,d) AS (
 SELECT seq,first_k,(100000000000000000000::HUGEINT+first_k)//3
 FROM b CROSS JOIN LATERAL (
   SELECT (100000000000000000000::HUGEINT+b.rsv)//3 AS first_k
 ) first_values WHERE seq=1
 UNION ALL
 SELECT b.seq,next_values.k,(2::HUGEINT*r.d+next_values.k)//3
 FROM r JOIN b ON b.seq=r.seq+1
 CROSS JOIN LATERAL (SELECT (2::HUGEINT*r.k+b.rsv)//3 AS k) next_values
)
SELECT seq,k::DOUBLE/1e18 AS k,d::DOUBLE/1e18 AS d,
       (3::HUGEINT*k-2::HUGEINT*d)::DOUBLE/1e18 AS j FROM r ORDER BY seq
"""


def _write_daily(state, con):
    for index, text in enumerate(DAILY_DATES):
        day = date.fromisoformat(text)
        path = state.root / f"silver/quote/stock_daily/trade_date={text}/part-000.parquet"
        path.parent.mkdir(parents=True)
        state.query(con, "fixture_daily", """COPY (SELECT '600000.SH'::VARCHAR AS ts_code,
            $day::DATE AS trade_date,10.0::DOUBLE AS open,11.0::DOUBLE AS high,
            9.0::DOUBLE AS low,10.0::DOUBLE AS close,10.0::DOUBLE AS pre_close,
            0.0::DOUBLE AS change_amount,0.0::DOUBLE AS pct_chg,
            100.0::DOUBLE AS vol,1000.0::DOUBLE AS amount)
            TO $target (FORMAT PARQUET)""", rows=1,
            bindings={"day": day, "target": str(path)})
        factor = state.root / f"silver/quote/adj_factor/trade_date={text}/part-000.parquet"
        factor.parent.mkdir(parents=True)
        state.query(con, "fixture_factor", """COPY (SELECT '600000.SH'::VARCHAR AS ts_code,
            $day::DATE AS trade_date,$factor::DOUBLE AS adj_factor)
            TO $target (FORMAT PARQUET)""", rows=1,
            bindings={"day": day, "factor": 1.0 if index<10 else 2.0, "target": str(factor)})
    state.fixture_rows += 42


def _write_literals(state, con):
    state.literal_root = state.root / "literal"
    for text, price in (("2026-01-05", 10.0), ("2026-01-06", 12.0), ("2026-01-07", 11.0)):
        path = state.literal_root / f"silver/quote/stock_daily/trade_date={text}/part-000.parquet"
        path.parent.mkdir(parents=True)
        state.query(con, "fixture_literal", """COPY (SELECT '600000.SH'::VARCHAR AS ts_code,
            $day::DATE AS trade_date,$price::DOUBLE AS open,$price::DOUBLE AS high,
            $price::DOUBLE AS low,$price::DOUBLE AS close,100.0::DOUBLE AS vol,
            1000.0::DOUBLE AS amount,$price::DOUBLE AS pre_close,
            0.0::DOUBLE AS change_amount,0.0::DOUBLE AS pct_chg)
            TO $target (FORMAT PARQUET)""", rows=1,
            bindings={"day": date.fromisoformat(text), "price": price, "target": str(path)})
    state.fixture_rows += 3


def build_fixture_and_reference(state):
    import duckdb

    con = duckdb.connect(":memory:", config={"threads": 1, "memory_limit": "128MiB",
                                            "max_temp_directory_size": "0B"})
    try:
        state.query(con, "fixture_numbered_prices", """CREATE TEMP TABLE d3_bars AS
          WITH numbered AS (
            SELECT i::BIGINT AS seq,10000+3*(i%11)-5*(i%7) AS cents,
                   DATE '2024-01-02'+CAST(floor((i-1)/240) AS INTEGER) AS day,
                   (i-1)%240 AS minute_index FROM range(1,10002) t(i)
          ) SELECT *,CAST(day AS TIMESTAMP)+CASE WHEN minute_index<120
            THEN INTERVAL 9 HOUR+INTERVAL 31 MINUTE+minute_index*INTERVAL 1 MINUTE
            ELSE INTERVAL 13 HOUR+INTERVAL 1 MINUTE+(minute_index-120)*INTERVAL 1 MINUTE
            END AS bar_time FROM numbered ORDER BY seq""", rows=10001)
        path = state.root / "gold/quote/stk_mins_qfq/freq=1/ts_code=600000.SH/year=2024/part-000.parquet"
        path.parent.mkdir(parents=True)
        state.query(con, "fixture_minute_parquet", """COPY (SELECT '600000.SH'::VARCHAR AS ts_code,
            1::INTEGER AS freq,day::DATE AS trade_date,bar_time::TIMESTAMP AS trade_time,
            cents/100.0 AS open,(cents+100)/100.0 AS high,(cents-100)/100.0 AS low,
            cents/100.0 AS close,100.0::DOUBLE AS vol,1000.0::DOUBLE AS amount,
            'SSE'::VARCHAR AS exchange FROM d3_bars ORDER BY seq)
            TO $target (FORMAT PARQUET,ROW_GROUP_SIZE 8192)""", rows=10001,
            bindings={"target": str(path)})
        state.fixture_rows += 10001
        times = state.query(con, "fixture_times", "SELECT bar_time FROM d3_bars ORDER BY seq", rows=10001)
        state.times = tuple(row[0].replace(tzinfo=ZoneInfo("Asia/Shanghai")) for row in times)
        default = state.query(con, "reference_macd_default", MACD_REFERENCE, rows=20002,
                              bindings=(12,26,9,10001))
        state.references["macd"] = tuple(default)
        state.references["kdj"] = tuple(state.query(con, "reference_kdj_default", KDJ_REFERENCE, rows=20002))
        projections = ["seq", "cents/100.0 AS close", "(cents+100)/100.0 AS high", "(cents-100)/100.0 AS low"]
        for period in MA_PERIODS:
            projections.append(f"CASE WHEN count(*) OVER w{period}={period} THEN "
                               f"(sum(cents) OVER w{period})::DOUBLE/(100.0*{period}) END AS ma{period}")
        projections.extend([
            "CASE WHEN count(*) OVER w20=20 THEN (sum(cents) OVER w20)::DOUBLE/2000.0 END AS middle",
            "CASE WHEN count(*) OVER w20=20 THEN sqrt(((sum(cents*cents) OVER w20)::HUGEINT*20-"
            "(sum(cents) OVER w20)::HUGEINT*(sum(cents) OVER w20)::HUGEINT)::DOUBLE/4000000.0) END AS deviation",
        ])
        windows = ",".join(f"w{n} AS (ORDER BY seq ROWS BETWEEN {n-1} PRECEDING AND CURRENT ROW)" for n in MA_PERIODS)
        reference_sql = "WITH independently_windowed AS (SELECT "+",".join(projections)+" FROM d3_bars WINDOW "+windows+") "
        reference_sql += "SELECT *,middle+2*deviation AS upper,middle-2*deviation AS lower FROM independently_windowed ORDER BY seq"
        state.references["windows"] = tuple(state.query(con, "reference_windows", reference_sql, rows=10001))
        for label, fast, slow, signal in (("macd9",9,65,9),("macd10",10,69,10)):
            state.references[label] = tuple(state.query(con, "reference_"+label, MACD_REFERENCE,
                                                        rows=4102, bindings=(fast,slow,signal,2051)))
        _write_daily(state, con)
        _write_literals(state, con)
        from d3_support import REPORT
        (REPORT / "independent_reference.json").write_text(json.dumps(state.references, separators=(",", ":"))+"\n")
    finally:
        con.close()
