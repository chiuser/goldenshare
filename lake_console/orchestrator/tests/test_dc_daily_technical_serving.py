from contextlib import contextmanager
from datetime import date
from pathlib import Path
import tempfile
import unittest

import duckdb

from orchestrator.defs.assets.dc_daily_technical_serving import (
    _read_gold_rows,
    replace_dc_daily_technical_partition,
)
from orchestrator.defs.run_contracts.dc_daily_technical_serving import (
    DC_DAILY_TECHNICAL_SERVING_COLUMNS,
    DC_DAILY_TECHNICAL_SERVING_TABLE,
)


DATE = "2026-07-14"


class _FakeClickHouseClient:
    def __init__(self, rows: list[tuple]) -> None:
        self.rows = list(rows)
        self.operations: list[str] = []

    def execute(self, query: str, params=None, data=None):
        normalized = " ".join(query.split()).upper()
        if normalized.startswith("SET "):
            self.operations.append("set")
            return []
        if normalized.startswith("DELETE FROM"):
            self.operations.append("delete")
            self.rows = []
            return []
        if normalized.startswith("SELECT COUNT()"):
            self.operations.append("count")
            return [(len(self.rows),)]
        if normalized.startswith("INSERT INTO"):
            self.operations.append("insert")
            self.rows.extend(list(data if data is not None else params))
            return []
        raise AssertionError(f"unexpected ClickHouse query: {query}")


class _FakeClickHouseResource:
    def __init__(self, client: _FakeClickHouseClient) -> None:
        self.client = client

    @contextmanager
    def get_connection(self):
        yield self.client


class DcDailyTechnicalServingTests(unittest.TestCase):
    def test_replace_uses_one_bounded_delete_and_one_insert_batch(self) -> None:
        row = tuple(["BK0001.DC", date.fromisoformat(DATE), "行业", 1.0] + [None] * 20)
        client = _FakeClickHouseClient([])

        replace_dc_daily_technical_partition(
            client,
            partition_key=DATE,
            rows=[row],
        )

        self.assertEqual(client.operations, ["set", "delete", "count", "insert", "count"])
        self.assertEqual(len(client.rows), 1)

    def test_replace_rejects_empty_rows_before_touching_clickhouse(self) -> None:
        client = _FakeClickHouseClient([])
        with self.assertRaisesRegex(ValueError, "empty serving partition"):
            replace_dc_daily_technical_partition(
                client,
                partition_key=DATE,
                rows=[],
            )
        self.assertEqual(client.operations, [])

    def test_gold_projection_is_contract_order_and_rejects_bad_date(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "part.parquet"
            connection = duckdb.connect()
            try:
                connection.execute(
                    """
                    CREATE TABLE source AS
                    SELECT
                      'BK0001.DC'::VARCHAR AS ts_code,
                      DATE '2026-07-14' AS trade_date,
                      '行业'::VARCHAR AS category,
                      1.0::DOUBLE AS close,
                      NULL::DOUBLE AS ma_5,
                      NULL::DOUBLE AS ma_10,
                      NULL::DOUBLE AS ma_15,
                      NULL::DOUBLE AS ma_20,
                      NULL::DOUBLE AS ma_30,
                      NULL::DOUBLE AS ma_60,
                      NULL::DOUBLE AS ma_120,
                      NULL::DOUBLE AS ma_250,
                      1.0::DOUBLE AS kdj_k,
                      1.0::DOUBLE AS kdj_d,
                      1.0::DOUBLE AS kdj_j,
                      1.0::DOUBLE AS macd_dif,
                      1.0::DOUBLE AS macd_dea,
                      1.0::DOUBLE AS macd,
                      NULL::DOUBLE AS boll_mid,
                      NULL::DOUBLE AS boll_upper,
                      NULL::DOUBLE AS boll_lower,
                      1::INTEGER AS observation_count,
                      'ma_5_10_15_20_30_60_120_250__kdj_9_3_3__macd_12_26_9__boll_20_2'::VARCHAR AS params_key,
                      'v1'::VARCHAR AS indicator_version
                    """
                )
                connection.execute(f"COPY source TO '{path}' (FORMAT PARQUET)")
                rows = _read_gold_rows(
                    connection,
                    path,
                    partition_key=DATE,
                )
                self.assertEqual(len(rows), 1)
                self.assertEqual(
                    tuple(DC_DAILY_TECHNICAL_SERVING_COLUMNS),
                    tuple(
                        str(row[0])
                        for row in connection.execute(
                            f"DESCRIBE SELECT * FROM read_parquet('{path}')"
                        ).fetchall()
                    ),
                )
            finally:
                connection.close()
