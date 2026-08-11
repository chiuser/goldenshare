from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.io.major_index_mins_technical_writer import (
    write_major_index_mins_technical_partition,
)
from orchestrator.defs.paths import silver_major_index_mins_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.major_index_mins_technical import (
    expected_major_index_mins_technical_codes,
)

TRADE_DATE = "2009-01-05"
FREQ = 5


def _write_golden_silver_partition(root: Path) -> None:
    path = silver_major_index_mins_path(root, f"{FREQ}min", TRADE_DATE)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[str, str, datetime, float, float, float]] = []
    start = datetime.fromisoformat(f"{TRADE_DATE} 09:30:00")
    for code_offset, code in enumerate(
        expected_major_index_mins_technical_codes(TRADE_DATE)
    ):
        for bar_index in range(49):
            close = float(bar_index + 1 + code_offset)
            rows.append(
                (
                    code,
                    f"{FREQ}min",
                    start + timedelta(minutes=FREQ * bar_index),
                    close + 1.0,
                    close - 1.0,
                    close,
                )
            )

    with duckdb.connect(":memory:") as connection:
        connection.execute(
            """
            CREATE TABLE silver_rows (
              ts_code VARCHAR,
              freq VARCHAR,
              trade_time TIMESTAMP,
              high DOUBLE,
              low DOUBLE,
              close DOUBLE
            )
            """
        )
        connection.executemany(
            "INSERT INTO silver_rows VALUES (?, ?, ?, ?, ?, ?)", rows
        )
        connection.execute(
            copy_query_to_parquet(
                "SELECT * FROM silver_rows ORDER BY ts_code, trade_time",
                path,
            )
        )


def test_formula_golden_fixture_locks_ma_boll_macd_and_kdj(
    tmp_path: Path,
) -> None:
    lake_root = tmp_path / "lake"
    staging_root = tmp_path / "staging"
    _write_golden_silver_partition(lake_root)

    result = write_major_index_mins_technical_partition(
        lake_root_path=lake_root,
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
    actual = dict(zip(columns, row, strict=True))

    assert actual["observation_count"] == 49
    assert actual["ma_5"] == pytest.approx(47.0)
    assert actual["ma_10"] == pytest.approx(44.5)
    assert actual["ma_20"] == pytest.approx(39.5)
    assert actual["ma_30"] == pytest.approx(34.5)
    assert actual["ma_60"] is None
    assert actual["ma_90"] is None
    assert actual["ma_250"] is None
    assert actual["boll_mid"] == pytest.approx(39.5)
    assert actual["boll_upper"] == pytest.approx(51.03256259467079)
    assert actual["boll_lower"] == pytest.approx(27.967437405329203)
    assert actual["macd_dif"] == pytest.approx(6.690947538607233)
    assert actual["macd_dea"] == pytest.approx(6.549292399355504)
    assert actual["macd"] == pytest.approx(0.2833102785034587)
    assert actual["kdj_k"] == pytest.approx(89.99999960448056)
    assert actual["kdj_d"] == pytest.approx(89.99999376146339)
    assert actual["kdj_j"] == pytest.approx(90.00001129051495)
