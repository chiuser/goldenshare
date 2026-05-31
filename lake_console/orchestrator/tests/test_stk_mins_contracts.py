import tempfile
import unittest
from pathlib import Path

import duckdb

from orchestrator.defs.catalog import DATASET_CHINESE_NAMES
from orchestrator.defs.duckdb_sql import (
    SILVER_STOCK_IDENTITY_MAP_REQUIRED_COLUMNS,
    STK_MINS_BOOTSTRAP_SELECT_TEMPLATE,
    STK_MINS_RAW_REQUIRED_COLUMNS,
    STK_MINS_SILVER_REQUIRED_COLUMNS,
    STOCK_IDENTITY_MAP_BOOTSTRAP_SELECT_TEMPLATE,
    duckdb_string,
)
from orchestrator.defs.partitions import cn_a_stock_mins_trade_days
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    raw_stk_mins_path,
    silver_stk_mins_path,
    silver_stock_identity_map_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_STK_MINS_SCHEMA,
    SILVER_STK_MINS_SCHEMA,
    SILVER_STOCK_IDENTITY_MAP_SCHEMA,
)
from orchestrator.defs.run_contracts.stk_mins import (
    STK_MINS_FREQS,
    derive_silver_stk_mins_exchange_from_ts_code,
    normalize_stk_mins_freq,
)


def _write_backup_stk_mins_parquet(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT
                '000001.SZ'::VARCHAR AS ts_code,
                30::BIGINT AS freq,
                TIMESTAMP '2026-05-07 09:30:00' AS trade_time,
                1.0::DOUBLE AS open,
                1.1::DOUBLE AS close,
                1.2::DOUBLE AS high,
                0.9::DOUBLE AS low,
                100::BIGINT AS vol,
                1234.5::DOUBLE AS amount,
                NULL AS exchange,
                1.05::DOUBLE AS vwap
            ) TO {duckdb_string(path)} (FORMAT PARQUET)
            """
        )


def _write_stock_identity_map_parquet(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT
                '001872.SZ'::VARCHAR AS latest_ts_code,
                '000022.SZ'::VARCHAR AS source_ts_code,
                DATE '1993-04-30' AS valid_from,
                NULL::DATE AS valid_to,
                DATE '1993-04-30' AS effective_list_date,
                NULL::DATE AS effective_delist_date,
                'namechange'::VARCHAR AS identity_source,
                'inferred'::VARCHAR AS confidence,
                '代码变更映射'::VARCHAR AS reason,
                TIMESTAMPTZ '2026-05-12 10:00:00+08' AS created_at
            ) TO {duckdb_string(path)} (FORMAT PARQUET)
            """
        )


class StkMinsContractTests(unittest.TestCase):
    def test_stock_mins_partition_name_is_stable(self) -> None:
        self.assertEqual(
            cn_a_stock_mins_trade_days.name,
            "cn_a_stock_mins_trade_days",
        )

    def test_stk_mins_frequency_contract_is_stable(self) -> None:
        self.assertEqual(STK_MINS_FREQS, (1, 5, 15, 30, 60))
        self.assertEqual(normalize_stk_mins_freq(30), 30)
        self.assertEqual(normalize_stk_mins_freq("30"), 30)
        with self.assertRaisesRegex(ValueError, "Unsupported stk_mins freq"):
            normalize_stk_mins_freq(2)
        with self.assertRaisesRegex(ValueError, "Unsupported stk_mins freq"):
            normalize_stk_mins_freq("30min")

    def test_stk_mins_catalog_names_are_registered(self) -> None:
        self.assertEqual(DATASET_CHINESE_NAMES["stk_mins"], "股票分钟线")
        self.assertEqual(
            DATASET_CHINESE_NAMES["stock_identity_map"],
            "股票身份映射",
        )

    def test_stk_mins_column_schemas_are_stable(self) -> None:
        self.assertEqual(
            [(column.name, column.type) for column in RAW_STK_MINS_SCHEMA],
            [
                ("ts_code", "VARCHAR"),
                ("freq", "INTEGER"),
                ("trade_time", "TIMESTAMP"),
                ("open", "DOUBLE"),
                ("close", "DOUBLE"),
                ("high", "DOUBLE"),
                ("low", "DOUBLE"),
                ("vol", "BIGINT"),
                ("amount", "DOUBLE"),
                ("exchange", "VARCHAR"),
                ("vwap", "DOUBLE"),
            ],
        )
        self.assertEqual(
            STK_MINS_RAW_REQUIRED_COLUMNS,
            tuple(column.name for column in RAW_STK_MINS_SCHEMA),
        )

    def test_stock_identity_map_column_schema_is_stable(self) -> None:
        self.assertEqual(
            [(column.name, column.type) for column in SILVER_STOCK_IDENTITY_MAP_SCHEMA],
            [
                ("latest_ts_code", "VARCHAR"),
                ("source_ts_code", "VARCHAR"),
                ("valid_from", "DATE"),
                ("valid_to", "DATE"),
                ("effective_list_date", "DATE"),
                ("effective_delist_date", "DATE"),
                ("identity_source", "VARCHAR"),
                ("confidence", "VARCHAR"),
                ("reason", "VARCHAR"),
                ("created_at", "TIMESTAMP WITH TIME ZONE"),
            ],
        )
        self.assertEqual(
            SILVER_STOCK_IDENTITY_MAP_REQUIRED_COLUMNS,
            tuple(column.name for column in SILVER_STOCK_IDENTITY_MAP_SCHEMA),
        )

    def test_silver_stk_mins_column_schema_is_stable(self) -> None:
        self.assertEqual(
            [(column.name, column.type) for column in SILVER_STK_MINS_SCHEMA],
            [
                ("ts_code", "VARCHAR"),
                ("freq", "INTEGER"),
                ("trade_date", "DATE"),
                ("trade_time", "TIMESTAMP"),
                ("open", "DOUBLE"),
                ("high", "DOUBLE"),
                ("low", "DOUBLE"),
                ("close", "DOUBLE"),
                ("vol", "DOUBLE"),
                ("amount", "DOUBLE"),
                ("exchange", "VARCHAR"),
            ],
        )
        self.assertNotIn("source_ts_code", STK_MINS_SILVER_REQUIRED_COLUMNS)
        self.assertNotIn("vwap", STK_MINS_SILVER_REQUIRED_COLUMNS)
        self.assertEqual(
            STK_MINS_SILVER_REQUIRED_COLUMNS,
            tuple(column.name for column in SILVER_STK_MINS_SCHEMA),
        )

    def test_stk_mins_paths_are_stable(self) -> None:
        self.assertEqual(
            raw_stk_mins_path(
                PATH_TEMPLATE_LAKE_ROOT,
                30,
                "2026-05-07",
            ).as_posix(),
            "data_lake/raw/tushare/stk_mins/freq=30/trade_date=2026-05-07/part-000.parquet",
        )
        self.assertEqual(
            silver_stk_mins_path(
                PATH_TEMPLATE_LAKE_ROOT,
                30,
                "2026-05-07",
            ).as_posix(),
            "data_lake/silver/quote/stk_mins/freq=30/trade_date=2026-05-07/part-000.parquet",
        )
        self.assertEqual(
            silver_stock_identity_map_path(PATH_TEMPLATE_LAKE_ROOT).as_posix(),
            "data_lake/silver/basic/stock_identity_map/part-000.parquet",
        )
        with self.assertRaisesRegex(ValueError, "Unsupported stk_mins freq"):
            raw_stk_mins_path(PATH_TEMPLATE_LAKE_ROOT, 2, "2026-05-07")
        with self.assertRaisesRegex(ValueError, "Unsupported stk_mins freq"):
            silver_stk_mins_path(PATH_TEMPLATE_LAKE_ROOT, 2, "2026-05-07")

    def test_silver_stk_mins_exchange_derivation_is_stable(self) -> None:
        self.assertEqual(
            derive_silver_stk_mins_exchange_from_ts_code("600000.SH"),
            "SSE",
        )
        self.assertEqual(
            derive_silver_stk_mins_exchange_from_ts_code("000001.SZ"),
            "SZSE",
        )
        self.assertEqual(
            derive_silver_stk_mins_exchange_from_ts_code("430047.BJ"),
            "BSE",
        )
        with self.assertRaisesRegex(ValueError, "Unsupported silver stk_mins"):
            derive_silver_stk_mins_exchange_from_ts_code("")
        with self.assertRaisesRegex(ValueError, "Unsupported silver stk_mins"):
            derive_silver_stk_mins_exchange_from_ts_code("000001.HK")

    def test_stk_mins_bootstrap_select_normalizes_backup_schema_variant(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            old_path = Path(temp_dir) / "part-00000.parquet"
            _write_backup_stk_mins_parquet(old_path)

            select_sql = STK_MINS_BOOTSTRAP_SELECT_TEMPLATE.format(
                old_path=duckdb_string(old_path)
            )
            with duckdb.connect(database=":memory:") as connection:
                describe_rows = connection.execute(
                    f"DESCRIBE SELECT * FROM ({select_sql})"
                ).fetchall()
                rows = connection.execute(
                    f"""
                    SELECT
                      ts_code,
                      freq,
                      strftime(trade_time, '%Y-%m-%d %H:%M:%S'),
                      open,
                      close,
                      high,
                      low,
                      vol,
                      amount,
                      exchange,
                      vwap
                    FROM ({select_sql})
                    """
                ).fetchall()

        self.assertEqual(
            [(row[0], row[1]) for row in describe_rows],
            [
                ("ts_code", "VARCHAR"),
                ("freq", "INTEGER"),
                ("trade_time", "TIMESTAMP"),
                ("open", "DOUBLE"),
                ("close", "DOUBLE"),
                ("high", "DOUBLE"),
                ("low", "DOUBLE"),
                ("vol", "BIGINT"),
                ("amount", "DOUBLE"),
                ("exchange", "VARCHAR"),
                ("vwap", "DOUBLE"),
            ],
        )
        self.assertEqual(
            rows,
            [
                (
                    "000001.SZ",
                    30,
                    "2026-05-07 09:30:00",
                    1.0,
                    1.1,
                    1.2,
                    0.9,
                    100,
                    1234.5,
                    None,
                    1.05,
                )
            ],
        )

    def test_stock_identity_map_bootstrap_select_normalizes_types(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            old_path = Path(temp_dir) / "security_identity_map.parquet"
            _write_stock_identity_map_parquet(old_path)

            select_sql = STOCK_IDENTITY_MAP_BOOTSTRAP_SELECT_TEMPLATE.format(
                old_path=duckdb_string(old_path)
            )
            with duckdb.connect(database=":memory:") as connection:
                describe_rows = connection.execute(
                    f"DESCRIBE SELECT * FROM ({select_sql})"
                ).fetchall()
                rows = connection.execute(
                    f"""
                    SELECT
                      latest_ts_code,
                      source_ts_code,
                      strftime(valid_from, '%Y-%m-%d'),
                      valid_to IS NULL,
                      strftime(effective_list_date, '%Y-%m-%d'),
                      effective_delist_date IS NULL,
                      identity_source,
                      confidence,
                      reason,
                      typeof(created_at)
                    FROM ({select_sql})
                    """
                ).fetchall()

        self.assertEqual(
            [(row[0], row[1]) for row in describe_rows],
            [
                ("latest_ts_code", "VARCHAR"),
                ("source_ts_code", "VARCHAR"),
                ("valid_from", "DATE"),
                ("valid_to", "DATE"),
                ("effective_list_date", "DATE"),
                ("effective_delist_date", "DATE"),
                ("identity_source", "VARCHAR"),
                ("confidence", "VARCHAR"),
                ("reason", "VARCHAR"),
                ("created_at", "TIMESTAMP WITH TIME ZONE"),
            ],
        )
        self.assertEqual(
            rows,
            [
                (
                    "001872.SZ",
                    "000022.SZ",
                    "1993-04-30",
                    True,
                    "1993-04-30",
                    True,
                    "namechange",
                    "inferred",
                    "代码变更映射",
                    "TIMESTAMP WITH TIME ZONE",
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
