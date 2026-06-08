from datetime import date
from pathlib import Path
import tempfile
import unittest

from orchestrator.defs.checks import stock_basic_checks as checks
from orchestrator.defs.catalog.lake_assets import LAKE_ASSET_CATALOG
from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    silver_stock_basic_select,
)
from orchestrator.defs.paths import silver_stock_basic_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_STOCK_BASIC_SCHEMA,
    SILVER_STOCK_BASIC_SCHEMA,
)
from orchestrator.defs.sensors import readiness


FULL_SILVER_STOCK_BASIC_COLUMNS = (
    "ts_code",
    "symbol",
    "name",
    "area",
    "industry",
    "fullname",
    "enname",
    "cnspell",
    "market",
    "exchange",
    "curr_type",
    "list_status",
    "list_date",
    "delist_date",
    "is_hs",
    "act_name",
    "act_ent_type",
)


def _column_types(schema) -> dict[str, str]:
    return {column.name: column.type for column in schema}


def _write_rows(
    path: Path,
    *,
    column_types: dict[str, str],
    rows: list[dict[str, object]],
    order_by: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = tuple(column_types)
    with DuckDBResource().connect() as connection:
        column_defs = ", ".join(
            f'"{column}" {column_types[column]}' for column in columns
        )
        connection.execute(f"CREATE TEMP TABLE rows_to_write ({column_defs})")
        if rows:
            placeholders = ", ".join("?" for _column in columns)
            values = [[row.get(column) for column in columns] for row in rows]
            connection.executemany(
                f"INSERT INTO rows_to_write VALUES ({placeholders})",
                values,
            )
        select_columns = ", ".join(
            f'CAST("{column}" AS {column_types[column]}) AS "{column}"'
            for column in columns
        )
        connection.execute(
            copy_query_to_parquet(
                f"""
                SELECT {select_columns}
                FROM rows_to_write
                ORDER BY {order_by}
                """,
                path,
            )
        )


def _check_function(check_definition):
    return check_definition.node_def.compute_fn.decorated_fn


def _metadata_value(metadata: dict[str, object], key: str) -> object:
    value = metadata[key]
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "data"):
        return value.data
    return value


class StockBasicSchemaContractTests(unittest.TestCase):
    def test_silver_schema_preserves_raw_business_fields_and_standardizes_dates(
        self,
    ) -> None:
        raw_types = _column_types(RAW_TUSHARE_STOCK_BASIC_SCHEMA)
        silver_types = _column_types(SILVER_STOCK_BASIC_SCHEMA)

        self.assertEqual(
            tuple(column.name for column in SILVER_STOCK_BASIC_SCHEMA),
            FULL_SILVER_STOCK_BASIC_COLUMNS,
        )
        self.assertEqual(set(silver_types), set(raw_types))
        for column_name in FULL_SILVER_STOCK_BASIC_COLUMNS:
            expected_type = (
                "DATE"
                if column_name in {"list_date", "delist_date"}
                else raw_types[column_name]
            )
            self.assertEqual(silver_types[column_name], expected_type)

    def test_silver_select_keeps_current_listed_rows_and_full_business_fields(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_path = Path(temp_dir) / "raw_stock_basic.parquet"
            _write_rows(
                raw_path,
                column_types=_column_types(RAW_TUSHARE_STOCK_BASIC_SCHEMA),
                rows=[
                    {
                        "ts_code": "000001.SZ",
                        "symbol": "000001",
                        "name": "平安银行",
                        "area": "深圳",
                        "industry": "银行",
                        "fullname": "平安银行股份有限公司",
                        "enname": "Ping An Bank Co., Ltd.",
                        "cnspell": "PAYH",
                        "market": "主板",
                        "exchange": "SZSE",
                        "curr_type": "CNY",
                        "list_status": "L",
                        "list_date": "19910403",
                        "delist_date": None,
                        "is_hs": "S",
                        "act_name": "无",
                        "act_ent_type": "无",
                    },
                    {
                        "ts_code": "200001.SZ",
                        "symbol": "200001",
                        "name": "B股样本",
                        "area": "深圳",
                        "industry": "地产",
                        "fullname": "B股样本股份有限公司",
                        "enname": "B Share Sample Co., Ltd.",
                        "cnspell": "BGYB",
                        "market": "主板",
                        "exchange": "SZSE",
                        "curr_type": "HKD",
                        "list_status": "L",
                        "list_date": "19920101",
                        "delist_date": None,
                        "is_hs": "",
                        "act_name": "样本",
                        "act_ent_type": "样本",
                    },
                    {
                        "ts_code": "900001.SH",
                        "symbol": "900001",
                        "name": "美元B股样本",
                        "area": "上海",
                        "industry": "制造",
                        "fullname": "美元B股样本股份有限公司",
                        "enname": "USD B Share Sample Co., Ltd.",
                        "cnspell": "MYBGYB",
                        "market": "主板",
                        "exchange": "SSE",
                        "curr_type": "USD",
                        "list_status": "L",
                        "list_date": "19920101",
                        "delist_date": None,
                        "is_hs": "",
                        "act_name": "样本",
                        "act_ent_type": "样本",
                    },
                    {
                        "ts_code": "000002.SZ",
                        "symbol": "000002",
                        "name": "退市样本",
                        "area": "深圳",
                        "industry": "地产",
                        "fullname": "退市样本股份有限公司",
                        "enname": "Delisted Sample Co., Ltd.",
                        "cnspell": "TSSB",
                        "market": "主板",
                        "exchange": "SZSE",
                        "curr_type": "CNY",
                        "list_status": "D",
                        "list_date": "19910129",
                        "delist_date": "20200101",
                        "is_hs": "",
                        "act_name": "样本",
                        "act_ent_type": "样本",
                    },
                ],
                order_by="ts_code",
            )

            with DuckDBResource().connect() as connection:
                cursor = connection.execute(
                    f"SELECT * FROM ({silver_stock_basic_select(raw_path)})"
                )
                columns = tuple(description[0] for description in cursor.description)
                rows = cursor.fetchall()

        self.assertEqual(columns, FULL_SILVER_STOCK_BASIC_COLUMNS)
        self.assertEqual(len(rows), 1)
        row = dict(zip(columns, rows[0], strict=True))
        self.assertEqual(row["ts_code"], "000001.SZ")
        self.assertEqual(row["fullname"], "平安银行股份有限公司")
        self.assertEqual(row["enname"], "Ping An Bank Co., Ltd.")
        self.assertEqual(row["cnspell"], "PAYH")
        self.assertEqual(row["curr_type"], "CNY")
        self.assertEqual(row["act_name"], "无")
        self.assertEqual(row["act_ent_type"], "无")
        self.assertEqual(row["list_date"], date(1991, 4, 3))
        self.assertIsNone(row["delist_date"])

    def test_silver_cny_stock_universe_check_fails_for_b_share_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_rows(
                silver_stock_basic_path(root),
                column_types=_column_types(SILVER_STOCK_BASIC_SCHEMA),
                rows=[
                    {
                        "ts_code": "000001.SZ",
                        "symbol": "000001",
                        "name": "平安银行",
                        "area": "深圳",
                        "industry": "银行",
                        "fullname": "平安银行股份有限公司",
                        "enname": "Ping An Bank Co., Ltd.",
                        "cnspell": "PAYH",
                        "market": "主板",
                        "exchange": "SZSE",
                        "curr_type": "CNY",
                        "list_status": "L",
                        "list_date": date(1991, 4, 3),
                        "delist_date": None,
                        "is_hs": "S",
                        "act_name": "无",
                        "act_ent_type": "无",
                    },
                    {
                        "ts_code": "200001.SZ",
                        "symbol": "200001",
                        "name": "B股样本",
                        "area": "深圳",
                        "industry": "地产",
                        "fullname": "B股样本股份有限公司",
                        "enname": "B Share Sample Co., Ltd.",
                        "cnspell": "BGYB",
                        "market": "主板",
                        "exchange": "SZSE",
                        "curr_type": "HKD",
                        "list_status": "L",
                        "list_date": date(1992, 1, 1),
                        "delist_date": None,
                        "is_hs": "",
                        "act_name": "样本",
                        "act_ent_type": "样本",
                    },
                ],
                order_by="ts_code",
            )
            check_fn = _check_function(
                checks.silver_stock_basic_cny_stock_universe_check
            )

            result = check_fn(
                LakeRootResource(root_path=str(root)),
                DuckDBResource(),
            )

        self.assertFalse(result.passed)
        self.assertEqual(
            _metadata_value(result.metadata, "goldenshare/non_cny_row_count"),
            1,
        )
        sample_rows = _metadata_value(
            result.metadata,
            "goldenshare/non_cny_sample_rows",
        )
        self.assertEqual(sample_rows[0]["ts_code"], "200001.SZ")
        self.assertEqual(sample_rows[0]["curr_type"], "HKD")

    def test_existing_required_columns_check_fails_when_curr_type_is_missing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_rows(
                silver_stock_basic_path(root),
                column_types={
                    "ts_code": "VARCHAR",
                    "symbol": "VARCHAR",
                    "name": "VARCHAR",
                    "area": "VARCHAR",
                    "industry": "VARCHAR",
                    "market": "VARCHAR",
                    "exchange": "VARCHAR",
                    "list_status": "VARCHAR",
                    "list_date": "DATE",
                    "delist_date": "DATE",
                    "is_hs": "VARCHAR",
                },
                rows=[
                    {
                        "ts_code": "000001.SZ",
                        "symbol": "000001",
                        "name": "平安银行",
                        "area": "深圳",
                        "industry": "银行",
                        "market": "主板",
                        "exchange": "SZSE",
                        "list_status": "L",
                        "list_date": date(1991, 4, 3),
                        "delist_date": None,
                        "is_hs": "S",
                    }
                ],
                order_by="ts_code",
            )
            check_fn = _check_function(
                checks.silver_stock_basic_required_columns_non_null
            )

            result = check_fn(
                LakeRootResource(root_path=str(root)),
                DuckDBResource(),
            )

        self.assertFalse(result.passed)
        missing_columns = _metadata_value(
            result.metadata,
            "goldenshare/missing_columns",
        )
        self.assertIn("curr_type", missing_columns)
        self.assertIn("fullname", missing_columns)

    def test_existing_silver_stock_basic_check_names_are_unchanged(self) -> None:
        self.assertEqual(
            readiness.SILVER_STOCK_BASIC_CHECKS,
            (
                "silver_stock_basic_cny_stock_universe_check",
                "silver_stock_basic_current_listed_only",
                "silver_stock_basic_has_listed_records",
                "silver_stock_basic_lifecycle_dates_valid",
                "silver_stock_basic_required_columns_non_null",
                "silver_stock_basic_unique_ts_code",
            ),
        )
        catalog_entry = next(
            entry
            for entry in LAKE_ASSET_CATALOG
            if entry.asset_key == "silver_stock_basic"
        )
        self.assertIn(
            "silver_stock_basic_cny_stock_universe_check",
            catalog_entry.blocking_check_names,
        )


if __name__ == "__main__":
    unittest.main()
