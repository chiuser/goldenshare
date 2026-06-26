import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import dagster as dg
import duckdb

from orchestrator.defs.checks.stock_daily_qfq_checks import (
    GOLD_STOCK_DAILY_QFQ_CHECK_NAMES,
    gold_stock_daily_qfq_contract_check,
    gold_stock_daily_qfq_qfq_semantics_check,
)
from orchestrator.defs.paths import (
    gold_stock_daily_qfq_path,
    silver_adj_factor_path,
    silver_stock_daily_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STOCK_DAILY_QFQ_SCHEMA,
    SILVER_ADJ_FACTOR_SCHEMA,
    SILVER_STOCK_DAILY_SCHEMA,
    SILVER_TRADE_CALENDAR_SCHEMA,
)
from orchestrator.defs.stock_daily_qfq import (
    GOLD_STOCK_DAILY_QFQ_COLUMNS,
    write_gold_stock_daily_qfq_partition,
)
from tests.test_stock_daily_qfq_contracts import (
    EARLIER_DATE,
    PREVIOUS_DATE,
    TRADE_DATE,
    _adj_factor_row,
    _column_types,
    _stock_daily_row,
    _write_adj_factor,
    _write_rows,
    _write_stock_daily,
)


def _asset_check_context(root: Path, partition_key: str):
    return dg.build_op_context(
        partition_key=partition_key,
        resources={
            "lake_root": LakeRootResource(root_path=str(root)),
            "duckdb": DuckDBResource(),
        },
    )


def _metadata_data(result, key: str):
    value = result.metadata[key]
    if hasattr(value, "data"):
        return value.data
    return getattr(value, "value", value)


def _write_calendar(root: Path) -> None:
    _write_rows(
        silver_trade_calendar_path(root),
        column_types=_column_types(SILVER_TRADE_CALENDAR_SCHEMA),
        rows=[
            {
                "exchange": "SSE",
                "trade_date": EARLIER_DATE,
                "is_open": True,
                "pretrade_date": "2026-06-15",
            },
            {
                "exchange": "SSE",
                "trade_date": PREVIOUS_DATE,
                "is_open": True,
                "pretrade_date": EARLIER_DATE,
            },
            {
                "exchange": "SSE",
                "trade_date": TRADE_DATE,
                "is_open": True,
                "pretrade_date": PREVIOUS_DATE,
            },
        ],
        order_by="exchange, trade_date",
    )


def _materialize_valid_qfq_partition(root: Path) -> None:
    _write_calendar(root)
    _write_stock_daily(
        root,
        PREVIOUS_DATE,
        [
            _stock_daily_row("000001.SZ", PREVIOUS_DATE, close=9.0),
            _stock_daily_row("600000.SH", PREVIOUS_DATE, close=18.0),
        ],
    )
    _write_stock_daily(
        root,
        TRADE_DATE,
        [
            _stock_daily_row("000001.SZ", TRADE_DATE, close=10.5, open_=10.0),
            _stock_daily_row("600000.SH", TRADE_DATE, close=20.5, open_=20.0),
        ],
    )
    _write_adj_factor(
        root,
        PREVIOUS_DATE,
        [
            _adj_factor_row("000001.SZ", PREVIOUS_DATE, 2.0),
            _adj_factor_row("600000.SH", PREVIOUS_DATE, 10.0),
        ],
    )
    _write_adj_factor(
        root,
        TRADE_DATE,
        [
            _adj_factor_row("000001.SZ", TRADE_DATE, 4.0),
            _adj_factor_row("600000.SH", TRADE_DATE, 5.0),
        ],
    )
    with duckdb.connect(database=":memory:") as connection:
        write_gold_stock_daily_qfq_partition(
            connection=connection,
            lake_root=root,
            trade_date=TRADE_DATE,
            previous_lookup_trade_dates=(PREVIOUS_DATE,),
        )


class StockDailyQfqCheckTests(unittest.TestCase):
    def test_check_name_surface_stays_compact(self) -> None:
        self.assertEqual(
            GOLD_STOCK_DAILY_QFQ_CHECK_NAMES,
            (
                "gold_stock_daily_qfq_contract_check",
                "gold_stock_daily_qfq_qfq_semantics_check",
            ),
        )

    def test_contract_check_passes_for_valid_partition(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _materialize_valid_qfq_partition(root)

            result = gold_stock_daily_qfq_contract_check(
                _asset_check_context(root, TRADE_DATE),
            )

        self.assertTrue(result.passed)
        self.assertEqual(_metadata_data(result, "goldenshare/failed_rule_names"), [])

    def test_contract_check_fails_for_duplicate_key(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            duplicate_row = {
                "ts_code": "000001.SZ",
                "trade_date": TRADE_DATE,
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.5,
                "pre_close": 9.0,
                "change_amount": 1.5,
                "pct_chg": 16.666666,
                "vol": 100.0,
                "amount": 1000.0,
            }
            _write_rows(
                gold_stock_daily_qfq_path(root, TRADE_DATE),
                column_types=_column_types(GOLD_STOCK_DAILY_QFQ_SCHEMA),
                rows=[duplicate_row, duplicate_row],
                order_by="ts_code, trade_date",
            )

            result = gold_stock_daily_qfq_contract_check(
                _asset_check_context(root, TRADE_DATE),
            )

        self.assertFalse(result.passed)
        self.assertIn(
            "unique_ts_code_trade_date",
            _metadata_data(result, "goldenshare/failed_rule_names"),
        )

    def test_qfq_semantics_check_passes_for_valid_partition(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _materialize_valid_qfq_partition(root)

            result = gold_stock_daily_qfq_qfq_semantics_check(
                _asset_check_context(root, TRADE_DATE),
            )

        self.assertTrue(result.passed)
        self.assertEqual(_metadata_data(result, "goldenshare/failed_rule_names"), [])
        self.assertEqual(
            _metadata_data(result, "goldenshare/missing_previous_factor_count"),
            0,
        )

    def test_qfq_semantics_check_fails_when_formula_does_not_match(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _materialize_valid_qfq_partition(root)

            with duckdb.connect(database=":memory:") as connection:
                rows = connection.execute(
                    f"""
                    SELECT *
                    FROM read_parquet(
                      '{gold_stock_daily_qfq_path(root, TRADE_DATE)}',
                      hive_partitioning=false
                    )
                    ORDER BY ts_code
                    """
                ).fetchall()
            corrupted_rows = [
                dict(zip(GOLD_STOCK_DAILY_QFQ_COLUMNS, row, strict=True))
                for row in rows
            ]
            corrupted_rows[0]["close"] = float(corrupted_rows[0]["close"]) + 1.0
            _write_rows(
                gold_stock_daily_qfq_path(root, TRADE_DATE),
                column_types=_column_types(GOLD_STOCK_DAILY_QFQ_SCHEMA),
                rows=corrupted_rows,
                order_by="ts_code, trade_date",
            )

            result = gold_stock_daily_qfq_qfq_semantics_check(
                _asset_check_context(root, TRADE_DATE),
            )

        self.assertFalse(result.passed)
        self.assertIn(
            "qfq_formula_matches_source_and_factor",
            _metadata_data(result, "goldenshare/failed_rule_names"),
        )

    def test_qfq_semantics_check_fails_when_previous_factor_is_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_calendar(root)
            _write_stock_daily(
                root,
                PREVIOUS_DATE,
                [_stock_daily_row("000001.SZ", PREVIOUS_DATE, close=9.0)],
            )
            _write_stock_daily(
                root,
                TRADE_DATE,
                [_stock_daily_row("000001.SZ", TRADE_DATE, close=10.5)],
            )
            _write_adj_factor(
                root,
                TRADE_DATE,
                [_adj_factor_row("000001.SZ", TRADE_DATE, 4.0)],
            )
            _write_rows(
                gold_stock_daily_qfq_path(root, TRADE_DATE),
                column_types=_column_types(GOLD_STOCK_DAILY_QFQ_SCHEMA),
                rows=[
                    {
                        "ts_code": "000001.SZ",
                        "trade_date": TRADE_DATE,
                        "open": 10.0,
                        "high": 11.0,
                        "low": 9.0,
                        "close": 10.5,
                        "pre_close": 0.0,
                        "change_amount": 0.0,
                        "pct_chg": 0.0,
                        "vol": 100.0,
                        "amount": 1000.0,
                    }
                ],
                order_by="ts_code, trade_date",
            )

            result = gold_stock_daily_qfq_qfq_semantics_check(
                _asset_check_context(root, TRADE_DATE),
            )

        self.assertFalse(result.passed)
        self.assertIn(
            "previous_adj_factor_covered",
            _metadata_data(result, "goldenshare/failed_rule_names"),
        )


if __name__ == "__main__":
    unittest.main()
