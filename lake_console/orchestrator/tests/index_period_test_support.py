"""指数周期测试的真实生产者schema与独立字面行情样本。"""

from datetime import date

import duckdb

from orchestrator.defs.io import index_period_writer as writer
from orchestrator.defs.paths import (
    silver_index_basic_path,
    silver_index_daily_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    SILVER_INDEX_BASIC_SCHEMA,
    SILVER_INDEX_DAILY_SCHEMA,
    SILVER_INDEX_WEEKLY_SCHEMA,
)
from orchestrator.defs.run_contracts.index_period import IndexPeriodSilverConfig
from tests.test_index_period_contracts import EXPECTED_CODES


def silver_inputs(root):
    # 字段依据calendar.py、index_basic.py、index_daily.py；日期和行情是人工边界样本。
    with duckdb.connect() as connection:
        path = silver_trade_calendar_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        connection.execute(f"""COPY (SELECT 'SSE'::VARCHAR exchange,day::DATE trade_date,
            (isodow(day)<6)::BOOLEAN is_open,NULL::DATE pretrade_date
            FROM generate_series(DATE '2024-01-01',DATE '2027-12-31',INTERVAL 1 DAY)t(day)) TO '{path}' (FORMAT PARQUET)""")
        basic = silver_index_basic_path(root)
        basic.parent.mkdir(parents=True, exist_ok=True)
        select = ",".join(
            "code::VARCHAR ts_code"
            if c.name == "ts_code"
            else "CASE WHEN code='000680.SH' THEN DATE '2025-01-20' ELSE DATE '2000-01-01' END list_date"
            if c.name == "list_date"
            else f'CAST(NULL AS {c.type}) AS "{c.name}"'
            for c in SILVER_INDEX_BASIC_SCHEMA
        )
        connection.execute(
            f"COPY (SELECT {select} FROM unnest(?::VARCHAR[])t(code)) TO '{basic}' (FORMAT PARQUET)",
            [EXPECTED_CODES],
        )
    values = {
        "2026-06-29": (100, 100, 100, 100, 100, 0, 0),
        "2026-06-30": (100, 100, 100, 100, 100, 0, 0),
        "2026-07-01": (100, 104, 98, 102, 100, 100.1256, 200.5678),
        "2026-07-02": (103, 108, 101, 106, 102, 200.2345, 300.6789),
        "2026-07-03": (105, 109, 102, 104, 106, 300.3456, 400.7890),
    }
    for day, values_for_day in values.items():
        daily_input(root, day, values_for_day)


def daily_input(root, day, values, *, codes=EXPECTED_CODES):
    path = silver_index_daily_path(root, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as connection:
        connection.execute(
            """CREATE TABLE daily AS SELECT code::VARCHAR ts_code,?::DATE trade_date,
            ?::DOUBLE open,?::DOUBLE high,?::DOUBLE low,?::DOUBLE AS "close",?::DOUBLE pre_close,
            999::DOUBLE change_amount,999::DOUBLE pct_chg,?::DOUBLE vol,?::DOUBLE amount
            FROM unnest(?::VARCHAR[])t(code)""",
            [date.fromisoformat(day), *values, codes],
        )
        assert tuple(
            (r[0], r[1]) for r in connection.execute("DESCRIBE daily").fetchall()
        ) == tuple((c.name, c.type) for c in SILVER_INDEX_DAILY_SCHEMA)
        connection.execute(f"COPY daily TO '{path}' (FORMAT PARQUET)")


def seed_silver(root, period, *, start="2026-06-29", day="2026-06-30"):
    path = writer.index_period_path(root, period, "silver")
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as connection:
        projection = ",".join(
            f'CAST("{c.name}" AS {c.type}) AS "{c.name}"'
            for c in SILVER_INDEX_WEEKLY_SCHEMA
        )
        connection.execute(
            f"""COPY (SELECT {projection} FROM (
            SELECT code ts_code,?::DATE period_start_date,?::DATE trade_date,
                100 open,100 high,100 low,100 AS "close",100 pre_close,0 change_amount,0 pct_chg,0 vol,0 amount
            FROM unnest(?::VARCHAR[])t(code))) TO '{path}' (FORMAT PARQUET)""",
            [date.fromisoformat(start), date.fromisoformat(day), EXPECTED_CODES],
        )
    return path


def silver_update(root, period, key, config, run_id="silver-test"):
    with duckdb.connect() as connection:
        return writer.write_index_period_silver(
            connection,
            lake_root=root,
            period=period,
            partition_key=key,
            run_id=run_id,
            staging_root=root.parent / "staging",
            config=IndexPeriodSilverConfig(**config),
        )
