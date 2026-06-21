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
    silver_stock_lifecycle_path,
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


def _write_silver_stock_lifecycle_parquet(path: Path) -> None:
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT
                '000001.SZ' AS ts_code,
                '000001' AS symbol,
                '平安银行' AS name,
                'SZSE' AS exchange,
                '主板' AS market,
                'CNY' AS curr_type,
                true AS is_cny_stock,
                'L' AS list_status,
                DATE '2020-01-01' AS list_date,
                NULL::DATE AS delist_date
              UNION ALL
              SELECT '000002.SZ', '000002', '退市样本', 'SZSE', '主板',
                'CNY', true, 'D', DATE '2020-01-01', DATE '2026-06-30'
              UNION ALL
              SELECT '000003.SZ', '000003', '未上市样本', 'SZSE', '主板',
                'CNY', true, 'L', DATE '2026-05-29', NULL::DATE
              UNION ALL
              SELECT '000004.SZ', '000004', '早期日期样本', 'SZSE', '主板',
                'CNY', true, 'L', DATE '2021-01-01', NULL::DATE
              UNION ALL
              SELECT '200001.SZ', '200001', '外币样本', 'SZSE', 'B股',
                'HKD', false, 'L', DATE '2020-01-01', NULL::DATE
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

    def test_silver_select_keeps_lifecycle_valid_cny_rows(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            raw_path = root / "raw.parquet"
            stock_lifecycle_path = silver_stock_lifecycle_path(root)
            _write_raw_adj_factor_parquet(raw_path)
            stock_lifecycle_path.parent.mkdir(parents=True, exist_ok=True)
            _write_silver_stock_lifecycle_parquet(stock_lifecycle_path)

            with duckdb.connect(database=":memory:") as connection:
                rows = connection.execute(
                    f"""
                    SELECT ts_code, strftime(trade_date, '%Y-%m-%d'), adj_factor
                    FROM ({silver_adj_factor_select(raw_path, stock_lifecycle_path)})
                    ORDER BY ts_code
                    """
                ).fetchall()

        self.assertEqual(
            rows,
            [
                ("000001.SZ", "2026-05-28", 1.1),
                ("000002.SZ", "2026-05-28", 2.2),
            ],
        )

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
