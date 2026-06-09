import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from orchestrator.defs.catalog.name_mapping import DATASET_CHINESE_NAMES
from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.run_contracts import asset_column_schemas
from orchestrator.defs.run_contracts.asset_column_schemas import (
    SILVER_ADJ_FACTOR_SCHEMA,
    SILVER_STOCK_BASIC_SCHEMA,
)
from orchestrator.defs.run_contracts.metadata import (
    CHECK_SCOPE_METADATA_KEY,
    CHECKED_ROW_COUNT_METADATA_KEY,
    FAILED_ROW_COUNT_METADATA_KEY,
)
from orchestrator.defs.stk_mins_qfq import (
    GOLD_STK_MINS_QFQ_FACTOR_REPAIR_PLAN_CHECK_NAME,
    QFQ_FACTOR_REPAIR_REASON_FACTOR_CHANGED,
    QFQ_FACTOR_REPAIR_REASON_MISSING_PREVIOUS_FACTOR,
    QFQ_FACTOR_REPAIR_REASON_NEW_CURRENT_CODE,
    QFQ_FACTOR_REPAIR_REASON_NO_FACTOR_CHANGED,
    build_adj_factor_changed_codes_sql,
    build_gold_stk_mins_qfq_factor_repair_check_metadata,
    build_gold_stk_mins_qfq_factor_repair_plan,
)


TRADE_DATE = "2026-05-29"
PREVIOUS_TRADE_DATE = "2026-05-28"


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


def _adj_row(ts_code: str, trade_date: str, adj_factor: float) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "trade_date": trade_date,
        "adj_factor": adj_factor,
    }


def _stock_basic_row(ts_code: str, list_date: str) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "symbol": ts_code.split(".", maxsplit=1)[0],
        "name": f"stock-{ts_code}",
        "area": "CN",
        "industry": "test",
        "market": "主板",
        "exchange": ts_code.rsplit(".", maxsplit=1)[-1],
        "list_status": "L",
        "list_date": list_date,
        "delist_date": None,
        "is_hs": "",
    }


def _fetch_dicts(sql: str) -> list[dict[str, object]]:
    with duckdb.connect(database=":memory:") as connection:
        columns = [item[0] for item in connection.execute(f"DESCRIBE ({sql})").fetchall()]
        rows = connection.execute(sql).fetchall()
    return [dict(zip(columns, row, strict=True)) for row in rows]


class StkMinsQfqM9BRepairContractTests(unittest.TestCase):
    def _write_inputs(
        self,
        root: Path,
        *,
        current_rows: list[dict[str, object]],
        previous_rows: list[dict[str, object]],
        stock_basic_rows: list[dict[str, object]],
    ) -> tuple[Path, Path, Path]:
        current_path = root / "current_adj_factor.parquet"
        previous_path = root / "previous_adj_factor.parquet"
        stock_basic_path = root / "silver_stock_basic.parquet"
        _write_rows(
            current_path,
            schema=SILVER_ADJ_FACTOR_SCHEMA,
            rows=current_rows,
            order_by="ts_code",
        )
        _write_rows(
            previous_path,
            schema=SILVER_ADJ_FACTOR_SCHEMA,
            rows=previous_rows,
            order_by="ts_code",
        )
        _write_rows(
            stock_basic_path,
            schema=SILVER_STOCK_BASIC_SCHEMA,
            rows=stock_basic_rows,
            order_by="ts_code",
        )
        return current_path, previous_path, stock_basic_path

    def test_repair_plan_is_no_change_when_factors_are_unchanged(self) -> None:
        with TemporaryDirectory() as temp_dir:
            current_path, previous_path, stock_basic_path = self._write_inputs(
                Path(temp_dir),
                current_rows=[
                    _adj_row("600000.SH", TRADE_DATE, 2.0),
                    _adj_row("000001.SZ", TRADE_DATE, 3.0),
                ],
                previous_rows=[
                    _adj_row("600000.SH", PREVIOUS_TRADE_DATE, 2.0),
                    _adj_row("000001.SZ", PREVIOUS_TRADE_DATE, 3.0),
                ],
                stock_basic_rows=[
                    _stock_basic_row("600000.SH", "1999-11-10"),
                    _stock_basic_row("000001.SZ", "1991-04-03"),
                ],
            )

            plan = build_gold_stk_mins_qfq_factor_repair_plan(
                current_adj_factor_path=current_path,
                previous_adj_factor_path=previous_path,
                silver_stock_basic_path=stock_basic_path,
                trade_date=TRADE_DATE,
                previous_trade_date=PREVIOUS_TRADE_DATE,
            )

        self.assertEqual(plan.reason, QFQ_FACTOR_REPAIR_REASON_NO_FACTOR_CHANGED)
        self.assertTrue(plan.can_execute_repair)
        self.assertFalse(plan.repair_required)
        self.assertEqual(plan.detected_change_code_count, 0)
        self.assertEqual(plan.repair_required_codes, ())

    def test_repair_plan_marks_factor_changed_codes_for_repair(self) -> None:
        with TemporaryDirectory() as temp_dir:
            current_path, previous_path, stock_basic_path = self._write_inputs(
                Path(temp_dir),
                current_rows=[
                    _adj_row("600000.SH", TRADE_DATE, 2.0),
                    _adj_row("000001.SZ", TRADE_DATE, 3.1),
                ],
                previous_rows=[
                    _adj_row("600000.SH", PREVIOUS_TRADE_DATE, 2.0),
                    _adj_row("000001.SZ", PREVIOUS_TRADE_DATE, 3.0),
                ],
                stock_basic_rows=[
                    _stock_basic_row("600000.SH", "1999-11-10"),
                    _stock_basic_row("000001.SZ", "1991-04-03"),
                ],
            )

            plan = build_gold_stk_mins_qfq_factor_repair_plan(
                current_adj_factor_path=current_path,
                previous_adj_factor_path=previous_path,
                silver_stock_basic_path=stock_basic_path,
                trade_date=TRADE_DATE,
                previous_trade_date=PREVIOUS_TRADE_DATE,
            )

        self.assertEqual(plan.reason, QFQ_FACTOR_REPAIR_REASON_FACTOR_CHANGED)
        self.assertTrue(plan.can_execute_repair)
        self.assertTrue(plan.repair_required)
        self.assertEqual(plan.repair_required_codes, ("000001.SZ",))
        self.assertEqual(plan.factor_changed_code_count, 1)
        self.assertEqual(plan.new_current_code_count, 0)
        self.assertEqual(plan.missing_previous_factor_code_count, 0)

    def test_current_only_new_listing_is_not_repair_required(self) -> None:
        with TemporaryDirectory() as temp_dir:
            current_path, previous_path, stock_basic_path = self._write_inputs(
                Path(temp_dir),
                current_rows=[
                    _adj_row("600000.SH", TRADE_DATE, 2.0),
                    _adj_row("301001.SZ", TRADE_DATE, 1.0),
                ],
                previous_rows=[_adj_row("600000.SH", PREVIOUS_TRADE_DATE, 2.0)],
                stock_basic_rows=[
                    _stock_basic_row("600000.SH", "1999-11-10"),
                    _stock_basic_row("301001.SZ", TRADE_DATE),
                ],
            )

            rows = _fetch_dicts(
                build_adj_factor_changed_codes_sql(
                    current_adj_factor_path=current_path,
                    previous_adj_factor_path=previous_path,
                    silver_stock_basic_path=stock_basic_path,
                    trade_date=TRADE_DATE,
                    previous_trade_date=PREVIOUS_TRADE_DATE,
                )
            )
            plan = build_gold_stk_mins_qfq_factor_repair_plan(
                current_adj_factor_path=current_path,
                previous_adj_factor_path=previous_path,
                silver_stock_basic_path=stock_basic_path,
                trade_date=TRADE_DATE,
                previous_trade_date=PREVIOUS_TRADE_DATE,
            )

        self.assertEqual(rows[0]["change_reason"], QFQ_FACTOR_REPAIR_REASON_NEW_CURRENT_CODE)
        self.assertEqual(plan.reason, QFQ_FACTOR_REPAIR_REASON_NEW_CURRENT_CODE)
        self.assertTrue(plan.can_execute_repair)
        self.assertFalse(plan.repair_required)
        self.assertEqual(plan.new_current_code_count, 1)
        self.assertEqual(plan.repair_required_codes, ())

    def test_current_only_previous_trade_date_listing_is_not_repair_required(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            current_path, previous_path, stock_basic_path = self._write_inputs(
                Path(temp_dir),
                current_rows=[
                    _adj_row("600000.SH", TRADE_DATE, 2.0),
                    _adj_row("920211.BJ", TRADE_DATE, 1.0),
                ],
                previous_rows=[_adj_row("600000.SH", PREVIOUS_TRADE_DATE, 2.0)],
                stock_basic_rows=[
                    _stock_basic_row("600000.SH", "1999-11-10"),
                    _stock_basic_row("920211.BJ", PREVIOUS_TRADE_DATE),
                ],
            )

            rows = _fetch_dicts(
                build_adj_factor_changed_codes_sql(
                    current_adj_factor_path=current_path,
                    previous_adj_factor_path=previous_path,
                    silver_stock_basic_path=stock_basic_path,
                    trade_date=TRADE_DATE,
                    previous_trade_date=PREVIOUS_TRADE_DATE,
                )
            )
            plan = build_gold_stk_mins_qfq_factor_repair_plan(
                current_adj_factor_path=current_path,
                previous_adj_factor_path=previous_path,
                silver_stock_basic_path=stock_basic_path,
                trade_date=TRADE_DATE,
                previous_trade_date=PREVIOUS_TRADE_DATE,
            )

        self.assertEqual(rows[0]["change_reason"], QFQ_FACTOR_REPAIR_REASON_NEW_CURRENT_CODE)
        self.assertEqual(plan.reason, QFQ_FACTOR_REPAIR_REASON_NEW_CURRENT_CODE)
        self.assertTrue(plan.can_execute_repair)
        self.assertFalse(plan.repair_required)
        self.assertEqual(plan.new_current_code_count, 1)
        self.assertEqual(plan.missing_previous_factor_code_count, 0)
        self.assertEqual(plan.repair_required_codes, ())

    def test_current_only_old_listing_blocks_repair_as_missing_previous_factor(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            current_path, previous_path, stock_basic_path = self._write_inputs(
                Path(temp_dir),
                current_rows=[
                    _adj_row("600000.SH", TRADE_DATE, 2.0),
                    _adj_row("000002.SZ", TRADE_DATE, 4.0),
                ],
                previous_rows=[_adj_row("600000.SH", PREVIOUS_TRADE_DATE, 2.0)],
                stock_basic_rows=[
                    _stock_basic_row("600000.SH", "1999-11-10"),
                    _stock_basic_row("000002.SZ", "1991-01-29"),
                ],
            )

            plan = build_gold_stk_mins_qfq_factor_repair_plan(
                current_adj_factor_path=current_path,
                previous_adj_factor_path=previous_path,
                silver_stock_basic_path=stock_basic_path,
                trade_date=TRADE_DATE,
                previous_trade_date=PREVIOUS_TRADE_DATE,
            )

        self.assertEqual(plan.reason, QFQ_FACTOR_REPAIR_REASON_MISSING_PREVIOUS_FACTOR)
        self.assertFalse(plan.can_execute_repair)
        self.assertFalse(plan.repair_required)
        self.assertEqual(plan.missing_previous_factor_code_count, 1)
        self.assertEqual(plan.repair_required_codes, ())

    def test_previous_only_code_does_not_trigger_repair(self) -> None:
        with TemporaryDirectory() as temp_dir:
            current_path, previous_path, stock_basic_path = self._write_inputs(
                Path(temp_dir),
                current_rows=[_adj_row("600000.SH", TRADE_DATE, 2.0)],
                previous_rows=[
                    _adj_row("600000.SH", PREVIOUS_TRADE_DATE, 2.0),
                    _adj_row("000003.SZ", PREVIOUS_TRADE_DATE, 5.0),
                ],
                stock_basic_rows=[
                    _stock_basic_row("600000.SH", "1999-11-10"),
                    _stock_basic_row("000003.SZ", "1991-04-03"),
                ],
            )

            plan = build_gold_stk_mins_qfq_factor_repair_plan(
                current_adj_factor_path=current_path,
                previous_adj_factor_path=previous_path,
                silver_stock_basic_path=stock_basic_path,
                trade_date=TRADE_DATE,
                previous_trade_date=PREVIOUS_TRADE_DATE,
            )

        self.assertEqual(plan.reason, QFQ_FACTOR_REPAIR_REASON_NO_FACTOR_CHANGED)
        self.assertFalse(plan.repair_required)
        self.assertEqual(plan.detected_change_code_count, 0)

    def test_repair_check_metadata_is_namespaced_and_truncated(self) -> None:
        with TemporaryDirectory() as temp_dir:
            current_path, previous_path, stock_basic_path = self._write_inputs(
                Path(temp_dir),
                current_rows=[
                    _adj_row("000001.SZ", TRADE_DATE, 1.1),
                    _adj_row("000002.SZ", TRADE_DATE, 2.1),
                    _adj_row("000003.SZ", TRADE_DATE, 3.1),
                ],
                previous_rows=[
                    _adj_row("000001.SZ", PREVIOUS_TRADE_DATE, 1.0),
                    _adj_row("000002.SZ", PREVIOUS_TRADE_DATE, 2.0),
                    _adj_row("000003.SZ", PREVIOUS_TRADE_DATE, 3.0),
                ],
                stock_basic_rows=[
                    _stock_basic_row("000001.SZ", "1991-04-03"),
                    _stock_basic_row("000002.SZ", "1991-01-29"),
                    _stock_basic_row("000003.SZ", "1991-04-03"),
                ],
            )
            plan = build_gold_stk_mins_qfq_factor_repair_plan(
                current_adj_factor_path=current_path,
                previous_adj_factor_path=previous_path,
                silver_stock_basic_path=stock_basic_path,
                trade_date=TRADE_DATE,
                previous_trade_date=PREVIOUS_TRADE_DATE,
                sample_limit=2,
            )

            metadata = build_gold_stk_mins_qfq_factor_repair_check_metadata(plan)

        self.assertEqual(metadata[CHECK_SCOPE_METADATA_KEY], "reconciliation")
        self.assertEqual(metadata[CHECKED_ROW_COUNT_METADATA_KEY], 3)
        self.assertEqual(metadata[FAILED_ROW_COUNT_METADATA_KEY], 0)
        self.assertEqual(metadata["goldenshare/reason"], "factor_changed")
        self.assertEqual(metadata["goldenshare/repair_required_code_count"], 3)
        self.assertEqual(
            metadata["goldenshare/factor_changed_code_samples"],
            ["000001.SZ", "000002.SZ"],
        )
        self.assertEqual(
            GOLD_STK_MINS_QFQ_FACTOR_REPAIR_PLAN_CHECK_NAME,
            "gold_stk_mins_qfq_factor_repair_plan_evaluated",
        )

    def test_m9b_does_not_add_factor_repair_summary_contracts(self) -> None:
        self.assertNotIn("gold_stk_mins_qfq_factor_repair_summary", DATASET_CHINESE_NAMES)
        self.assertFalse(
            hasattr(
                asset_column_schemas,
                "GOLD_STK_MINS_QFQ_FACTOR_REPAIR_SUMMARY_SCHEMA",
            )
        )


if __name__ == "__main__":
    unittest.main()
