import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import dagster as dg
import duckdb

from orchestrator.defs.checks import stk_mins_checks
from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.paths import (
    gold_stk_mins_qfq_path,
    silver_adj_factor_path,
    silver_stk_mins_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STK_MINS_QFQ_SCHEMA,
    SILVER_ADJ_FACTOR_SCHEMA,
    SILVER_STK_MINS_SCHEMA,
)
from orchestrator.defs.sensors import readiness


TRADE_DATE = "2014-06-03"
LATEST_DATE = "2014-06-04"
ASSET_KEY = dg.AssetKey("gold_stk_mins_qfq_5m")


class _LakeRoot:
    def __init__(self, root: Path) -> None:
        self._root = root

    def root(self) -> Path:
        return self._root


class _CheckContext:
    partition_key = TRADE_DATE


def _column_types(schema) -> dict[str, str]:
    return {column.name: column.type for column in schema}


def _write_rows(
    path: Path,
    *,
    schema,
    rows: list[dict[str, object]],
    order_by: str = "1",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = tuple(column.name for column in schema)
    column_types = _column_types(schema)
    with duckdb.connect(database=":memory:") as connection:
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


def _silver_row(
    ts_code: str = "600000.SH",
    *,
    trade_time: str = f"{TRADE_DATE} 09:35:00",
    open_: float = 10.0,
) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "freq": 5,
        "trade_date": TRADE_DATE,
        "trade_time": trade_time,
        "open": open_,
        "high": open_ + 1.0,
        "low": open_ - 1.0,
        "close": open_ + 0.5,
        "vol": 100.0,
        "amount": 1000.0,
        "exchange": "SSE" if ts_code.endswith(".SH") else "SZSE",
    }


def _adj_row(ts_code: str, trade_date: str, adj_factor: float) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "trade_date": trade_date,
        "adj_factor": adj_factor,
    }


def _gold_row(
    ts_code: str = "600000.SH",
    *,
    trade_time: str = f"{TRADE_DATE} 09:35:00",
    open_: float = 5.0,
    freq: int = 5,
) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "freq": freq,
        "trade_date": TRADE_DATE,
        "trade_time": trade_time,
        "open": open_,
        "high": open_ + 0.5,
        "low": open_ - 0.5,
        "close": open_ + 0.25,
        "vol": 100.0,
        "amount": 1000.0,
        "exchange": "SSE" if ts_code.endswith(".SH") else "SZSE",
    }


def _write_silver(lake_root: Path, rows: list[dict[str, object]]) -> None:
    _write_rows(
        silver_stk_mins_path(lake_root, 5, TRADE_DATE),
        schema=SILVER_STK_MINS_SCHEMA,
        rows=rows,
        order_by="ts_code, trade_time",
    )


def _write_adj_factor(
    lake_root: Path,
    *,
    trade_rows: list[dict[str, object]] | None = None,
    latest_rows: list[dict[str, object]] | None = None,
) -> None:
    _write_rows(
        silver_adj_factor_path(lake_root, TRADE_DATE),
        schema=SILVER_ADJ_FACTOR_SCHEMA,
        rows=trade_rows
        if trade_rows is not None
        else [
            _adj_row("600000.SH", TRADE_DATE, 2.0),
            _adj_row("000001.SZ", TRADE_DATE, 3.0),
        ],
        order_by="ts_code",
    )
    _write_rows(
        silver_adj_factor_path(lake_root, LATEST_DATE),
        schema=SILVER_ADJ_FACTOR_SCHEMA,
        rows=latest_rows
        if latest_rows is not None
        else [
            _adj_row("600000.SH", LATEST_DATE, 4.0),
            _adj_row("000001.SZ", LATEST_DATE, 6.0),
        ],
        order_by="ts_code",
    )


def _write_gold(lake_root: Path, rows: list[dict[str, object]]) -> None:
    for row in rows:
        path = gold_stk_mins_qfq_path(
            lake_root,
            row["freq"],
            str(row["ts_code"]),
            TRADE_DATE[:4],
        )
        existing_rows = []
        if path.exists():
            with duckdb.connect(database=":memory:") as connection:
                existing_rows = [
                    dict(zip([column.name for column in GOLD_STK_MINS_QFQ_SCHEMA], item, strict=True))
                    for item in connection.execute(
                        f"SELECT * FROM read_parquet('{path.as_posix()}', hive_partitioning=false)"
                    ).fetchall()
                ]
        _write_rows(
            path,
            schema=GOLD_STK_MINS_QFQ_SCHEMA,
            rows=[*existing_rows, row],
            order_by="trade_date, trade_time",
        )


def _check_results(lake_root: Path) -> dict[str, dg.AssetCheckResult]:
    results = stk_mins_checks._gold_stk_mins_qfq_check_results(
        context=_CheckContext(),
        lake_root=_LakeRoot(lake_root),
        duckdb=DuckDBResource(),
        freq=5,
        asset_key=ASSET_KEY,
    )
    return {result.check_name: result for result in results}


class StkMinsQfqM8BCheckTests(unittest.TestCase):
    def test_gold_qfq_checks_pass_for_valid_partition(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir) / "lake"
            _write_silver(
                lake_root,
                [
                    _silver_row("600000.SH", open_=10.0),
                    _silver_row("000001.SZ", open_=30.0),
                ],
            )
            _write_adj_factor(lake_root)
            _write_gold(
                lake_root,
                [
                    _gold_row("600000.SH", open_=5.0),
                    _gold_row("000001.SZ", open_=15.0),
                ],
            )

            results = _check_results(lake_root)

            self.assertEqual(len(results), len(stk_mins_checks.GOLD_STK_MINS_QFQ_CHECK_NAMES))
            self.assertTrue(all(result.passed for result in results.values()))
            self.assertEqual(
                results[
                    stk_mins_checks.GOLD_STK_MINS_QFQ_FORMULA_MATCHES_SILVER_ADJ_FACTOR_CHECK
                ].asset_key,
                ASSET_KEY,
            )

    def test_missing_gold_file_fails_file_row_count_and_formula_checks(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir) / "lake"
            _write_silver(lake_root, [_silver_row("600000.SH", open_=10.0)])
            _write_adj_factor(lake_root)

            results = _check_results(lake_root)

            self.assertFalse(
                results[
                    stk_mins_checks.GOLD_STK_MINS_QFQ_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK
                ].passed
            )
            self.assertFalse(
                results[
                    stk_mins_checks.GOLD_STK_MINS_QFQ_FORMULA_MATCHES_SILVER_ADJ_FACTOR_CHECK
                ].passed
            )

    def test_schema_mismatch_fails_schema_check(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir) / "lake"
            _write_silver(lake_root, [_silver_row("600000.SH", open_=10.0)])
            _write_adj_factor(lake_root)
            bad_schema = tuple(
                column
                for column in GOLD_STK_MINS_QFQ_SCHEMA
                if column.name != "exchange"
            )
            _write_rows(
                gold_stk_mins_qfq_path(lake_root, 5, "600000.SH", 2014),
                schema=bad_schema,
                rows=[
                    {
                        key: value
                        for key, value in _gold_row("600000.SH", open_=5.0).items()
                        if key != "exchange"
                    }
                ],
                order_by="trade_date, trade_time",
            )

            results = _check_results(lake_root)

            self.assertFalse(
                results[
                    stk_mins_checks.GOLD_STK_MINS_QFQ_SCHEMA_MATCHES_CONTRACT_CHECK
                ].passed
            )

    def test_freq_date_path_mismatch_fails_alignment_check(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir) / "lake"
            _write_silver(lake_root, [_silver_row("600000.SH", open_=10.0)])
            _write_adj_factor(lake_root)
            _write_rows(
                gold_stk_mins_qfq_path(lake_root, 5, "600000.SH", 2014),
                schema=GOLD_STK_MINS_QFQ_SCHEMA,
                rows=[_gold_row("600000.SH", open_=5.0, freq=15)],
                order_by="trade_date, trade_time",
            )

            results = _check_results(lake_root)

            self.assertFalse(
                results[
                    stk_mins_checks.GOLD_STK_MINS_QFQ_FREQ_DATE_PATH_MATCH_CHECK
                ].passed
            )

    def test_duplicate_keys_fail_unique_check(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir) / "lake"
            _write_silver(lake_root, [_silver_row("600000.SH", open_=10.0)])
            _write_adj_factor(lake_root)
            _write_rows(
                gold_stk_mins_qfq_path(lake_root, 5, "600000.SH", 2014),
                schema=GOLD_STK_MINS_QFQ_SCHEMA,
                rows=[
                    _gold_row("600000.SH", open_=5.0),
                    _gold_row("600000.SH", open_=5.0),
                ],
                order_by="trade_date, trade_time",
            )

            results = _check_results(lake_root)

            self.assertFalse(
                results[
                    stk_mins_checks.GOLD_STK_MINS_QFQ_UNIQUE_TS_CODE_TRADE_TIME_CHECK
                ].passed
            )

    def test_bad_prices_fail_price_sanity_check(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir) / "lake"
            _write_silver(lake_root, [_silver_row("600000.SH", open_=10.0)])
            _write_adj_factor(lake_root)
            bad_row = _gold_row("600000.SH", open_=5.0)
            bad_row["low"] = 6.0
            _write_gold(lake_root, [bad_row])

            results = _check_results(lake_root)

            self.assertFalse(
                results[stk_mins_checks.GOLD_STK_MINS_QFQ_PRICE_SANITY_CHECK].passed
            )

    def test_row_count_mismatch_fails_reconciliation_check(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir) / "lake"
            _write_silver(
                lake_root,
                [
                    _silver_row("600000.SH", trade_time=f"{TRADE_DATE} 09:35:00", open_=10.0),
                    _silver_row("600000.SH", trade_time=f"{TRADE_DATE} 09:40:00", open_=12.0),
                ],
            )
            _write_adj_factor(lake_root)
            _write_gold(lake_root, [_gold_row("600000.SH", open_=5.0)])

            results = _check_results(lake_root)

            self.assertFalse(
                results[
                    stk_mins_checks.GOLD_STK_MINS_QFQ_ROW_COUNT_MATCHES_SILVER_CHECK
                ].passed
            )

    def test_missing_factor_fails_factor_coverage_check(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir) / "lake"
            _write_silver(
                lake_root,
                [
                    _silver_row("600000.SH", open_=10.0),
                    _silver_row("000001.SZ", open_=30.0),
                ],
            )
            _write_adj_factor(
                lake_root,
                trade_rows=[_adj_row("600000.SH", TRADE_DATE, 2.0)],
                latest_rows=[_adj_row("600000.SH", LATEST_DATE, 4.0)],
            )
            _write_gold(lake_root, [_gold_row("600000.SH", open_=5.0)])

            results = _check_results(lake_root)

            self.assertFalse(
                results[
                    stk_mins_checks.GOLD_STK_MINS_QFQ_FACTOR_COVERAGE_COMPLETE_CHECK
                ].passed
            )

    def test_formula_mismatch_fails_formula_check(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir) / "lake"
            _write_silver(lake_root, [_silver_row("600000.SH", open_=10.0)])
            _write_adj_factor(lake_root)
            _write_gold(lake_root, [_gold_row("600000.SH", open_=6.0)])

            results = _check_results(lake_root)

            self.assertFalse(
                results[
                    stk_mins_checks.GOLD_STK_MINS_QFQ_FORMULA_MATCHES_SILVER_ADJ_FACTOR_CHECK
                ].passed
            )

    def test_check_definitions_and_readiness_names_match(self) -> None:
        check_names = sorted(
            check_key.name
            for check_definition in stk_mins_checks.GOLD_STK_MINS_QFQ_CHECK_DEFINITIONS
            for check_key in check_definition.check_keys
        )
        expected_names = sorted(
            stk_mins_checks.GOLD_STK_MINS_QFQ_CHECK_NAMES
            * len(stk_mins_checks.GOLD_STK_MINS_QFQ_ASSETS)
        )

        self.assertEqual(check_names, expected_names)
        self.assertEqual(
            readiness.GOLD_STK_MINS_QFQ_CHECKS,
            stk_mins_checks.GOLD_STK_MINS_QFQ_CHECK_NAMES,
        )
        self.assertEqual(len(readiness.GOLD_STK_MINS_QFQ_READINESS_SPECS), 5)


if __name__ == "__main__":
    unittest.main()
