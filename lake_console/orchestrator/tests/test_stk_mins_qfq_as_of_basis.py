from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from orchestrator.defs.duckdb_sql import copy_query_to_parquet, duckdb_string
from orchestrator.defs.paths import (
    gold_stk_mins_qfq_as_of_basis_path,
    silver_adj_factor_path,
    silver_stk_mins_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STK_MINS_QFQ_SCHEMA,
    SILVER_ADJ_FACTOR_SCHEMA,
    SILVER_STK_MINS_SCHEMA,
)
from orchestrator.defs.stk_mins_qfq import build_daily_qfq_select_sql_from_as_of_basis
from orchestrator.defs.stk_mins_qfq_as_of_basis import (
    GOLD_STK_MINS_QFQ_AS_OF_BASIS_COLUMNS,
    build_qfq_as_of_basis_rows_sql,
    qfq_as_of_basis_source_trade_dates,
    qfq_as_of_basis_validation_counts,
    write_gold_stk_mins_qfq_as_of_basis,
)
from orchestrator.defs.bootstrap.stk_mins_qfq_as_of_basis import (
    apply_stk_mins_qfq_as_of_basis_bootstrap,
    audit_stk_mins_qfq_as_of_basis_bootstrap,
    plan_stk_mins_qfq_as_of_basis_bootstrap,
)


TRADE_DATE = "2026-07-09"
REPAIR_DATE = "2026-07-13"


def _write_rows(path: Path, *, schema, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = tuple(column.name for column in schema)
    column_types = {column.name: column.type for column in schema}
    order_columns = [column for column in ("ts_code", "trade_date", "trade_time") if column in columns]
    with duckdb.connect(database=":memory:") as connection:
        column_definitions = ", ".join(
            f'"{column}" {column_types[column]}' for column in columns
        )
        connection.execute(f"CREATE TABLE rows_to_write ({column_definitions})")
        connection.executemany(
            f"INSERT INTO rows_to_write VALUES ({', '.join('?' for _ in columns)})",
            [[row.get(column) for column in columns] for row in rows],
        )
        connection.execute(
            copy_query_to_parquet(
                "SELECT * FROM rows_to_write ORDER BY " + ", ".join(order_columns),
                path,
            )
        )


def _silver_row(ts_code: str, *, trade_date: str = TRADE_DATE) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "freq": 1,
        "trade_date": trade_date,
        "trade_time": f"{trade_date} 09:31:00",
        "open": 10.0,
        "high": 11.0,
        "low": 9.0,
        "close": 10.5,
        "vol": 100.0,
        "amount": 1000.0,
        "exchange": "SSE",
    }


def _factor_row(ts_code: str, *, trade_date: str, factor: float) -> dict[str, object]:
    return {"ts_code": ts_code, "trade_date": trade_date, "adj_factor": factor}


def _qfq_row(
    ts_code: str,
    *,
    trade_date: str = TRADE_DATE,
    trade_factor: float,
    as_of_factor: float,
) -> dict[str, object]:
    silver = _silver_row(ts_code, trade_date=trade_date)
    return {
        "ts_code": ts_code,
        "freq": 1,
        "trade_date": trade_date,
        "trade_time": silver["trade_time"],
        "open": float(silver["open"]) * trade_factor / as_of_factor,
        "high": float(silver["high"]) * trade_factor / as_of_factor,
        "low": float(silver["low"]) * trade_factor / as_of_factor,
        "close": float(silver["close"]) * trade_factor / as_of_factor,
        "vol": silver["vol"],
        "amount": silver["amount"],
        "exchange": silver["exchange"],
    }


class GoldStkMinsQfqAsOfBasisTests(unittest.TestCase):
    def test_history_bootstrap_is_non_active_and_requires_explicit_apply(self) -> None:
        bootstrap_source = Path(
            "src/orchestrator/defs/bootstrap/stk_mins_qfq_as_of_basis.py"
        ).read_text()
        cli_source = Path(
            "src/orchestrator/defs/bootstrap/stk_mins_qfq_as_of_basis_cli.py"
        ).read_text()

        for forbidden_fragment in (
            "import dagster",
            "@dg.asset",
            "@dg.asset_check",
            "@dg.sensor",
            "define_asset_job",
            "report_runless_asset_event",
        ):
            self.assertNotIn(forbidden_fragment, bootstrap_source)
        self.assertIn('choices=("plan", "apply")', cli_source)
        self.assertIn('if args.stage == "apply" and not args.apply:', cli_source)
        self.assertIn('apply requires explicit --apply.', cli_source)

    def test_daily_upsert_is_idempotent_and_repair_replaces_only_selected_code(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir) / "lake"
            silver_path = silver_stk_mins_path(lake_root, 1, TRADE_DATE)
            daily_factor_path = silver_adj_factor_path(lake_root, TRADE_DATE)
            repair_factor_path = silver_adj_factor_path(lake_root, REPAIR_DATE)
            _write_rows(
                silver_path,
                schema=SILVER_STK_MINS_SCHEMA,
                rows=[_silver_row("000001.SZ"), _silver_row("600000.SH")],
            )
            _write_rows(
                daily_factor_path,
                schema=SILVER_ADJ_FACTOR_SCHEMA,
                rows=[
                    _factor_row("000001.SZ", trade_date=TRADE_DATE, factor=1.0),
                    _factor_row("600000.SH", trade_date=TRADE_DATE, factor=2.0),
                ],
            )
            _write_rows(
                repair_factor_path,
                schema=SILVER_ADJ_FACTOR_SCHEMA,
                rows=[
                    _factor_row("000001.SZ", trade_date=REPAIR_DATE, factor=4.0),
                    _factor_row("600000.SH", trade_date=REPAIR_DATE, factor=8.0),
                ],
            )

            daily_sql = build_qfq_as_of_basis_rows_sql(
                silver_paths=[silver_path],
                as_of_adj_factor_path=daily_factor_path,
                as_of_trade_date=TRADE_DATE,
                basis_origin="daily_qfq",
                trade_dates=[TRADE_DATE],
            )
            first_results = write_gold_stk_mins_qfq_as_of_basis(
                lake_root=lake_root,
                replacement_rows_sql=daily_sql,
            )
            second_results = write_gold_stk_mins_qfq_as_of_basis(
                lake_root=lake_root,
                replacement_rows_sql=daily_sql,
            )
            repair_results = write_gold_stk_mins_qfq_as_of_basis(
                lake_root=lake_root,
                replacement_rows_sql=build_qfq_as_of_basis_rows_sql(
                    silver_paths=[silver_path],
                    as_of_adj_factor_path=repair_factor_path,
                    as_of_trade_date=REPAIR_DATE,
                    basis_origin="factor_repair",
                    trade_dates=[TRADE_DATE],
                    stock_codes=["000001.SZ"],
                ),
            )

            self.assertTrue(first_results[0].changed)
            self.assertFalse(second_results[0].changed)
            self.assertTrue(repair_results[0].changed)
            basis_path = gold_stk_mins_qfq_as_of_basis_path(lake_root, 2026)
            with duckdb.connect(database=":memory:") as connection:
                observed_columns = tuple(
                    row[0]
                    for row in connection.execute(
                        "DESCRIBE SELECT * FROM "
                        f"read_parquet({duckdb_string(basis_path)}, hive_partitioning=false)"
                    ).fetchall()
                )
                rows = connection.execute(
                    f"""
                    SELECT ts_code, trade_date, as_of_adj_factor, as_of_trade_date, basis_origin
                    FROM read_parquet({duckdb_string(basis_path)}, hive_partitioning=false)
                    ORDER BY ts_code
                    """
                ).fetchall()
            self.assertEqual(observed_columns, GOLD_STK_MINS_QFQ_AS_OF_BASIS_COLUMNS)
            self.assertEqual(
                rows,
                [
                    (
                        "000001.SZ",
                        date.fromisoformat(TRADE_DATE),
                        4.0,
                        date.fromisoformat(REPAIR_DATE),
                        "factor_repair",
                    ),
                    (
                        "600000.SH",
                        date.fromisoformat(TRADE_DATE),
                        2.0,
                        date.fromisoformat(TRADE_DATE),
                        "daily_qfq",
                    ),
                ],
            )

    def test_source_factor_validation_and_date_join_use_real_as_of_basis(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir) / "lake"
            silver_path = silver_stk_mins_path(lake_root, 1, TRADE_DATE)
            trade_factor_path = silver_adj_factor_path(lake_root, TRADE_DATE)
            repair_factor_path = silver_adj_factor_path(lake_root, REPAIR_DATE)
            _write_rows(
                silver_path,
                schema=SILVER_STK_MINS_SCHEMA,
                rows=[_silver_row("000001.SZ")],
            )
            _write_rows(
                trade_factor_path,
                schema=SILVER_ADJ_FACTOR_SCHEMA,
                rows=[_factor_row("000001.SZ", trade_date=TRADE_DATE, factor=2.0)],
            )
            _write_rows(
                repair_factor_path,
                schema=SILVER_ADJ_FACTOR_SCHEMA,
                rows=[_factor_row("000001.SZ", trade_date=REPAIR_DATE, factor=4.0)],
            )
            write_gold_stk_mins_qfq_as_of_basis(
                lake_root=lake_root,
                replacement_rows_sql=build_qfq_as_of_basis_rows_sql(
                    silver_paths=[silver_path],
                    as_of_adj_factor_path=repair_factor_path,
                    as_of_trade_date=REPAIR_DATE,
                    basis_origin="factor_repair",
                    trade_dates=[TRADE_DATE],
                ),
            )
            basis_path = gold_stk_mins_qfq_as_of_basis_path(lake_root, 2026)

            with duckdb.connect(database=":memory:") as connection:
                self.assertEqual(
                    qfq_as_of_basis_source_trade_dates(
                        connection,
                        basis_paths=[basis_path],
                        trade_dates=[TRADE_DATE],
                    ),
                    (REPAIR_DATE,),
                )
                valid_counts = qfq_as_of_basis_validation_counts(
                    connection,
                    basis_paths=[basis_path],
                    trade_dates=[TRADE_DATE],
                    source_factor_paths=[repair_factor_path],
                )
                expected_rows = connection.execute(
                    build_daily_qfq_select_sql_from_as_of_basis(
                        silver_paths=[silver_path],
                        trade_adj_factor_paths=[trade_factor_path],
                        as_of_basis_paths=[basis_path],
                    )
                ).fetchall()
            self.assertEqual(valid_counts.failed_row_count, 0)
            self.assertEqual(len(expected_rows), 1)
            self.assertAlmostEqual(float(expected_rows[0][4]), 5.0)

            _write_rows(
                repair_factor_path,
                schema=SILVER_ADJ_FACTOR_SCHEMA,
                rows=[_factor_row("000001.SZ", trade_date=REPAIR_DATE, factor=5.0)],
            )
            with duckdb.connect(database=":memory:") as connection:
                mismatch_counts = qfq_as_of_basis_validation_counts(
                    connection,
                    basis_paths=[basis_path],
                    trade_dates=[TRADE_DATE],
                    source_factor_paths=[repair_factor_path],
                )
            self.assertEqual(mismatch_counts.source_factor_mismatch_row_count, 1)

    def test_history_bootstrap_plans_without_writing_then_derives_auditable_basis(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir) / "lake"
            silver_path = silver_stk_mins_path(lake_root, 1, TRADE_DATE)
            factor_path = silver_adj_factor_path(lake_root, TRADE_DATE)
            qfq_path = (
                lake_root
                / "gold"
                / "quote"
                / "stk_mins_qfq"
                / "freq=1"
                / "ts_code=000001.SZ"
                / "year=2026"
                / "part-000.parquet"
            )
            _write_rows(
                silver_path,
                schema=SILVER_STK_MINS_SCHEMA,
                rows=[_silver_row("000001.SZ")],
            )
            _write_rows(
                factor_path,
                schema=SILVER_ADJ_FACTOR_SCHEMA,
                rows=[_factor_row("000001.SZ", trade_date=TRADE_DATE, factor=2.0)],
            )
            _write_rows(
                qfq_path,
                schema=GOLD_STK_MINS_QFQ_SCHEMA,
                rows=[
                    _qfq_row(
                        "000001.SZ",
                        trade_factor=2.0,
                        as_of_factor=4.0,
                    )
                ],
            )

            plan = plan_stk_mins_qfq_as_of_basis_bootstrap(
                lake_root=lake_root,
                partition_keys=[TRADE_DATE],
            )

            basis_path = gold_stk_mins_qfq_as_of_basis_path(lake_root, 2026)
            self.assertFalse(basis_path.exists())
            self.assertFalse(plan.should_stop)
            self.assertEqual(plan.planned_replacement_row_count, 1)

            apply_report = apply_stk_mins_qfq_as_of_basis_bootstrap(
                lake_root=lake_root,
                partition_keys=[TRADE_DATE],
                expected_plan_fingerprint=plan.plan_fingerprint,
            )

            self.assertTrue(basis_path.exists())
            self.assertEqual(apply_report.written_years, ("2026",))
            self.assertTrue(apply_report.audit.passed)
            audit = audit_stk_mins_qfq_as_of_basis_bootstrap(
                lake_root=lake_root,
                partition_keys=[TRADE_DATE],
            )
            self.assertTrue(audit.passed)


if __name__ == "__main__":
    unittest.main()
