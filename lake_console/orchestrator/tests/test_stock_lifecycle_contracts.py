from datetime import date
from pathlib import Path
import tempfile
import unittest

from orchestrator.defs.checks import stock_lifecycle_checks as checks
from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    silver_stock_lifecycle_select,
)
from orchestrator.defs.paths import silver_stock_lifecycle_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_STOCK_BASIC_SCHEMA,
    SILVER_STOCK_LIFECYCLE_SCHEMA,
)


FULL_SILVER_STOCK_LIFECYCLE_COLUMNS = (
    "ts_code",
    "symbol",
    "name",
    "exchange",
    "market",
    "curr_type",
    "is_cny_stock",
    "list_status",
    "list_date",
    "delist_date",
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


def _raw_stock_basic_row(
    *,
    ts_code: str,
    symbol: str,
    name: str,
    curr_type: str = "CNY",
    list_status: str = "L",
    list_date: str = "19910101",
    delist_date: str | None = None,
) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "symbol": symbol,
        "name": name,
        "area": "深圳",
        "industry": "样本",
        "fullname": f"{name}股份有限公司",
        "enname": f"{symbol} Sample Co., Ltd.",
        "cnspell": symbol,
        "market": "主板",
        "exchange": "SZSE" if ts_code.endswith(".SZ") else "SSE",
        "curr_type": curr_type,
        "list_status": list_status,
        "list_date": list_date,
        "delist_date": delist_date,
        "is_hs": "",
        "act_name": "样本",
        "act_ent_type": "样本",
    }


def _lifecycle_row(
    *,
    ts_code: str = "000001.SZ",
    symbol: str = "000001",
    name: str = "平安银行",
    curr_type: str = "CNY",
    is_cny_stock: bool = True,
    list_status: str = "L",
    list_date: date | None = date(1991, 4, 3),
    delist_date: date | None = None,
) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "symbol": symbol,
        "name": name,
        "exchange": "SZSE" if ts_code.endswith(".SZ") else "SSE",
        "market": "主板",
        "curr_type": curr_type,
        "is_cny_stock": is_cny_stock,
        "list_status": list_status,
        "list_date": list_date,
        "delist_date": delist_date,
    }


def _check_function(check_definition):
    return check_definition.node_def.compute_fn.decorated_fn


def _metadata_value(metadata: dict[str, object], key: str) -> object:
    value = metadata[key]
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "data"):
        return value.data
    return value


class StockLifecycleContractTests(unittest.TestCase):
    def test_lifecycle_schema_is_stable(self) -> None:
        raw_types = _column_types(RAW_TUSHARE_STOCK_BASIC_SCHEMA)
        lifecycle_types = _column_types(SILVER_STOCK_LIFECYCLE_SCHEMA)

        self.assertEqual(
            tuple(column.name for column in SILVER_STOCK_LIFECYCLE_SCHEMA),
            FULL_SILVER_STOCK_LIFECYCLE_COLUMNS,
        )
        for column_name in (
            "ts_code",
            "symbol",
            "name",
            "exchange",
            "market",
            "curr_type",
            "list_status",
        ):
            self.assertEqual(lifecycle_types[column_name], raw_types[column_name])
        self.assertEqual(lifecycle_types["is_cny_stock"], "BOOLEAN")
        self.assertEqual(lifecycle_types["list_date"], "DATE")
        self.assertEqual(lifecycle_types["delist_date"], "DATE")

    def test_lifecycle_select_keeps_historical_cny_stock_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_path = Path(temp_dir) / "raw_stock_basic.parquet"
            _write_rows(
                raw_path,
                column_types=_column_types(RAW_TUSHARE_STOCK_BASIC_SCHEMA),
                rows=[
                    _raw_stock_basic_row(
                        ts_code="000001.SZ",
                        symbol="000001",
                        name="当前上市样本",
                    ),
                    _raw_stock_basic_row(
                        ts_code="000638.SZ",
                        symbol="000638",
                        name="退市样本",
                        list_status="D",
                        list_date="19961126",
                        delist_date="20260413",
                    ),
                    _raw_stock_basic_row(
                        ts_code="000002.SZ",
                        symbol="000002",
                        name="暂停上市样本",
                        list_status="P",
                    ),
                    _raw_stock_basic_row(
                        ts_code="000003.SZ",
                        symbol="000003",
                        name="其他状态样本",
                        list_status="G",
                    ),
                    _raw_stock_basic_row(
                        ts_code="200001.SZ",
                        symbol="200001",
                        name="B股样本",
                        curr_type="HKD",
                    ),
                ],
                order_by="ts_code",
            )

            with DuckDBResource().connect() as connection:
                cursor = connection.execute(
                    f"""
                    SELECT *
                    FROM ({silver_stock_lifecycle_select(raw_path)})
                    ORDER BY ts_code
                    """
                )
                columns = tuple(description[0] for description in cursor.description)
                rows = cursor.fetchall()

        self.assertEqual(columns, FULL_SILVER_STOCK_LIFECYCLE_COLUMNS)
        self.assertEqual(
            [row[0] for row in rows],
            ["000001.SZ", "000002.SZ", "000003.SZ", "000638.SZ"],
        )
        delisted_row = dict(zip(columns, rows[-1], strict=True))
        self.assertEqual(delisted_row["ts_code"], "000638.SZ")
        self.assertEqual(delisted_row["list_status"], "D")
        self.assertTrue(delisted_row["is_cny_stock"])
        self.assertEqual(delisted_row["list_date"], date(1996, 11, 26))
        self.assertEqual(delisted_row["delist_date"], date(2026, 4, 13))

    def test_required_columns_check_fails_missing_column(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            column_types = _column_types(SILVER_STOCK_LIFECYCLE_SCHEMA)
            column_types.pop("list_status")
            _write_rows(
                silver_stock_lifecycle_path(root),
                column_types=column_types,
                rows=[
                    {
                        key: value
                        for key, value in _lifecycle_row().items()
                        if key in column_types
                    }
                ],
                order_by="ts_code",
            )

            check_fn = _check_function(
                checks.silver_stock_lifecycle_required_columns_and_types_check
            )
            result = check_fn(LakeRootResource(root_path=str(root)), DuckDBResource())

        self.assertFalse(result.passed)
        self.assertIn(
            "list_status",
            _metadata_value(result.metadata, "goldenshare/missing_columns"),
        )

    def test_dates_valid_check_fails_invalid_lifecycle_range(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_rows(
                silver_stock_lifecycle_path(root),
                column_types=_column_types(SILVER_STOCK_LIFECYCLE_SCHEMA),
                rows=[
                    _lifecycle_row(
                        ts_code="000638.SZ",
                        symbol="000638",
                        name="退市样本",
                        list_status="D",
                        list_date=date(2026, 4, 14),
                        delist_date=date(2026, 4, 13),
                    )
                ],
                order_by="ts_code",
            )

            check_fn = _check_function(checks.silver_stock_lifecycle_dates_valid_check)
            result = check_fn(LakeRootResource(root_path=str(root)), DuckDBResource())

        self.assertFalse(result.passed)
        self.assertEqual(
            _metadata_value(
                result.metadata,
                "goldenshare/invalid_lifecycle_date_count",
            ),
            1,
        )

    def test_cny_universe_check_fails_non_cny_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_rows(
                silver_stock_lifecycle_path(root),
                column_types=_column_types(SILVER_STOCK_LIFECYCLE_SCHEMA),
                rows=[
                    _lifecycle_row(
                        ts_code="200001.SZ",
                        symbol="200001",
                        name="B股样本",
                        curr_type="HKD",
                        is_cny_stock=False,
                    )
                ],
                order_by="ts_code",
            )

            check_fn = _check_function(
                checks.silver_stock_lifecycle_cny_stock_universe_check
            )
            result = check_fn(LakeRootResource(root_path=str(root)), DuckDBResource())

        self.assertFalse(result.passed)
        self.assertEqual(
            _metadata_value(result.metadata, "goldenshare/non_cny_row_count"),
            1,
        )

    def test_required_fields_check_fails_null_required_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_rows(
                silver_stock_lifecycle_path(root),
                column_types=_column_types(SILVER_STOCK_LIFECYCLE_SCHEMA),
                rows=[
                    _lifecycle_row(
                        ts_code="000001.SZ",
                        symbol="000001",
                        name="平安银行",
                        list_date=None,
                    )
                ],
                order_by="ts_code",
            )

            check_fn = _check_function(
                checks.silver_stock_lifecycle_required_fields_non_null_check
            )
            result = check_fn(LakeRootResource(root_path=str(root)), DuckDBResource())

        self.assertFalse(result.passed)
        self.assertEqual(
            _metadata_value(result.metadata, "goldenshare/null_row_count"),
            1,
        )


if __name__ == "__main__":
    unittest.main()
