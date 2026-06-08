import tempfile
import unittest
from pathlib import Path

import duckdb

from orchestrator.defs.catalog import DATASET_CHINESE_NAMES
from orchestrator.defs.duckdb_sql import (
    ADJ_FACTOR_BOOTSTRAP_SELECT_TEMPLATE,
    ADJ_FACTOR_RAW_REQUIRED_COLUMNS,
    ADJ_FACTOR_SILVER_REQUIRED_COLUMNS,
    duckdb_string,
    silver_adj_factor_select,
)
from orchestrator.defs.partitions import cn_a_stock_current_trade_days
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    raw_adj_factor_path,
    silver_adj_factor_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_ADJ_FACTOR_SCHEMA,
    SILVER_ADJ_FACTOR_SCHEMA,
)


def _write_old_adj_factor_parquet(path: Path, trade_date_expression: str) -> None:
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT
                '000001.SZ'::VARCHAR AS ts_code,
                {trade_date_expression} AS trade_date,
                1.234::DOUBLE AS adj_factor
            ) TO {duckdb_string(path)} (FORMAT PARQUET)
            """
        )


def _write_raw_adj_factor_parquet(path: Path) -> None:
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT '000001.SZ' AS ts_code, '20260528' AS trade_date, 1.1 AS adj_factor
              UNION ALL
              SELECT '000002.SZ' AS ts_code, '20260528' AS trade_date, 2.2 AS adj_factor
              UNION ALL
              SELECT '000003.SZ' AS ts_code, '20260528' AS trade_date, 3.3 AS adj_factor
              UNION ALL
              SELECT '000004.SZ' AS ts_code, '20200101' AS trade_date, 4.4 AS adj_factor
              UNION ALL
              SELECT '200001.SZ' AS ts_code, '20260528' AS trade_date, 5.5 AS adj_factor
            ) TO {duckdb_string(path)} (FORMAT PARQUET)
            """
        )


def _write_silver_stock_basic_parquet(path: Path) -> None:
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT
                '000001.SZ' AS ts_code,
                'CNY' AS curr_type,
                'L' AS list_status,
                DATE '2020-01-01' AS list_date
              UNION ALL
              SELECT '000002.SZ' AS ts_code, 'CNY' AS curr_type, 'D' AS list_status, DATE '2020-01-01'
              UNION ALL
              SELECT '000003.SZ' AS ts_code, 'CNY' AS curr_type, 'L' AS list_status, DATE '2026-05-29'
              UNION ALL
              SELECT '000004.SZ' AS ts_code, 'CNY' AS curr_type, 'L' AS list_status, DATE '2021-01-01'
              UNION ALL
              SELECT '200001.SZ' AS ts_code, 'HKD' AS curr_type, 'L' AS list_status, DATE '2020-01-01'
            ) TO {duckdb_string(path)} (FORMAT PARQUET)
            """
        )


class AdjFactorContractTests(unittest.TestCase):
    def test_current_trade_day_partition_name_is_stable(self) -> None:
        self.assertEqual(
            cn_a_stock_current_trade_days.name,
            "cn_a_stock_current_trade_days",
        )

    def test_adj_factor_catalog_name_is_registered(self) -> None:
        self.assertEqual(DATASET_CHINESE_NAMES["adj_factor"], "复权因子")

    def test_adj_factor_column_schemas_are_stable(self) -> None:
        self.assertEqual(
            [(column.name, column.type) for column in RAW_TUSHARE_ADJ_FACTOR_SCHEMA],
            [
                ("ts_code", "VARCHAR"),
                ("trade_date", "VARCHAR"),
                ("adj_factor", "DOUBLE"),
            ],
        )
        self.assertEqual(
            [(column.name, column.type) for column in SILVER_ADJ_FACTOR_SCHEMA],
            [
                ("ts_code", "VARCHAR"),
                ("trade_date", "DATE"),
                ("adj_factor", "DOUBLE"),
            ],
        )
        self.assertEqual(
            ADJ_FACTOR_RAW_REQUIRED_COLUMNS,
            tuple(column.name for column in RAW_TUSHARE_ADJ_FACTOR_SCHEMA),
        )
        self.assertEqual(
            ADJ_FACTOR_SILVER_REQUIRED_COLUMNS,
            tuple(column.name for column in SILVER_ADJ_FACTOR_SCHEMA),
        )

    def test_adj_factor_paths_are_stable(self) -> None:
        self.assertEqual(
            raw_adj_factor_path(PATH_TEMPLATE_LAKE_ROOT, "2026-05-29").as_posix(),
            "data_lake/raw/tushare/adj_factor/trade_date=2026-05-29/part-000.parquet",
        )
        self.assertEqual(
            silver_adj_factor_path(PATH_TEMPLATE_LAKE_ROOT, "2026-05-29").as_posix(),
            "data_lake/silver/quote/adj_factor/trade_date=2026-05-29/part-000.parquet",
        )

    def test_bootstrap_select_normalizes_old_lake_date_trade_date(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            old_path = Path(temp_dir) / "old-date.parquet"
            _write_old_adj_factor_parquet(old_path, "DATE '2009-01-05'")

            rows = self._query_bootstrap_select(old_path)

        self.assertEqual(rows, [("000001.SZ", "20090105", 1.234)])

    def test_bootstrap_select_keeps_yyyymmdd_string_trade_date(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            old_path = Path(temp_dir) / "old-string.parquet"
            _write_old_adj_factor_parquet(old_path, "'20090105'::VARCHAR")

            rows = self._query_bootstrap_select(old_path)

        self.assertEqual(rows, [("000001.SZ", "20090105", 1.234)])

    def test_silver_select_keeps_only_current_listed_rows_after_list_date(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_path = Path(temp_dir) / "raw.parquet"
            stock_basic_path = Path(temp_dir) / "silver_stock_basic.parquet"
            _write_raw_adj_factor_parquet(raw_path)
            _write_silver_stock_basic_parquet(stock_basic_path)

            with duckdb.connect(database=":memory:") as connection:
                rows = connection.execute(
                    f"""
                    SELECT ts_code, strftime(trade_date, '%Y-%m-%d'), adj_factor
                    FROM ({silver_adj_factor_select(raw_path, stock_basic_path)})
                    ORDER BY ts_code
                    """
                ).fetchall()

        self.assertEqual(rows, [("000001.SZ", "2026-05-28", 1.1)])

    def _query_bootstrap_select(self, old_path: Path) -> list[tuple[str, str, float]]:
        select_sql = ADJ_FACTOR_BOOTSTRAP_SELECT_TEMPLATE.format(
            old_path=duckdb_string(old_path)
        )
        with duckdb.connect(database=":memory:") as connection:
            return connection.execute(
                f"""
                SELECT ts_code, trade_date, adj_factor
                FROM ({select_sql})
                ORDER BY ts_code
                """
            ).fetchall()


if __name__ == "__main__":
    unittest.main()
