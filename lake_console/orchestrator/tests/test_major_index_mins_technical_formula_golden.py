from pathlib import Path

import duckdb
import pytest

from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.io.major_index_mins_technical_writer import (
    write_major_index_mins_technical_partition,
)
from orchestrator.defs.paths import gold_major_index_mins_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.cn_a_derived_minute_bars import (
    expected_gold_minute_times,
)
from orchestrator.defs.run_contracts.major_index_mins_technical import (
    expected_major_index_mins_technical_codes,
)

TRADE_DATE = "2009-01-05"
FREQ = 5


def _write_golden_bar_partition(root: Path) -> None:
    path = gold_major_index_mins_path(root, FREQ, TRADE_DATE)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[object, ...]] = []
    trade_times = expected_gold_minute_times("SSE", FREQ)
    for code_offset, code in enumerate(
        expected_major_index_mins_technical_codes(TRADE_DATE)
    ):
        for bar_index, trade_time in enumerate(trade_times):
            close = float(bar_index + 1 + code_offset)
            rows.append(
                (
                    code,
                    FREQ,
                    TRADE_DATE,
                    f"{TRADE_DATE} {trade_time}",
                    close,
                    close + 1.0,
                    close - 1.0,
                    close,
                    1.0,
                    close,
                    "SSE",
                    close,
                )
            )

    with duckdb.connect(":memory:") as connection:
        connection.execute(
            """
            CREATE TABLE gold_rows (
              ts_code VARCHAR,
              freq INTEGER,
              trade_date DATE,
              trade_time TIMESTAMP,
              open DOUBLE,
              high DOUBLE,
              low DOUBLE,
              close DOUBLE,
              vol DOUBLE,
              amount DOUBLE,
              exchange VARCHAR,
              vwap DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO gold_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        connection.execute(
            copy_query_to_parquet(
                "SELECT * FROM gold_rows ORDER BY ts_code, trade_time",
                path,
            )
        )


def test_formula_golden_fixture_locks_ma_boll_macd_and_kdj(
    tmp_path: Path,
) -> None:
    lake_root = tmp_path / "lake"
    staging_root = tmp_path / "staging"
    _write_golden_bar_partition(lake_root)

    result = write_major_index_mins_technical_partition(
        source_lake_root_path=lake_root,
        target_lake_root_path=lake_root,
        staging_root_path=staging_root,
        duckdb_resource=DuckDBResource(),
        freq=FREQ,
        partition_key=TRADE_DATE,
        run_id="formula-golden",
        expected_trade_dates=(TRADE_DATE,),
    )

    with duckdb.connect(":memory:") as connection:
        row = connection.execute(
            f"""
            SELECT *
            FROM {read_parquet(result.technical_path, hive_partitioning=False)}
            WHERE ts_code = '000001.SH'
            ORDER BY trade_time DESC
            LIMIT 1
            """
        ).fetchone()
        columns = tuple(item[0] for item in connection.description)
        session = connection.execute(
            f"""
            SELECT
              count(*),
              min(strftime(trade_time, '%H:%M:%S')),
              max(strftime(trade_time, '%H:%M:%S')),
              count(*) FILTER (
                WHERE strftime(trade_time, '%H:%M:%S') = '09:30:00'
              )
            FROM {read_parquet(result.technical_path, hive_partitioning=False)}
            WHERE ts_code = '000001.SH'
            """
        ).fetchone()
    actual = dict(zip(columns, row, strict=True))

    assert session == (48, "09:35:00", "15:00:00", 0)
    assert actual["observation_count"] == 48
    assert actual["ma_5"] == pytest.approx(46.0)
    assert actual["ma_10"] == pytest.approx(43.5)
    assert actual["ma_20"] == pytest.approx(38.5)
    assert actual["ma_30"] == pytest.approx(33.5)
    assert actual["ma_60"] is None
    assert actual["ma_90"] is None
    assert actual["ma_250"] is None
    assert actual["boll_mid"] == pytest.approx(38.5)
    assert actual["boll_upper"] == pytest.approx(50.03256259467079)
    assert actual["boll_lower"] == pytest.approx(26.967437405329203)
    assert actual["macd_dif"] == pytest.approx(6.666407739609795)
    assert actual["macd_dea"] == pytest.approx(6.513878614542531)
    assert actual["macd"] == pytest.approx(0.3050582501345289)
    assert actual["kdj_k"] == pytest.approx(89.99999940672087)
    assert actual["kdj_d"] == pytest.approx(89.99999083995485)
    assert actual["kdj_j"] == pytest.approx(90.00001654025294)
