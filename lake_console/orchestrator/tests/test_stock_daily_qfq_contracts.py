import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import dagster as dg
import duckdb

from orchestrator.defs.checks.stock_daily_qfq_checks import (
    gold_stock_daily_qfq_contract_check,
)
from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.assets.stock_daily_qfq import gold_stock_daily_qfq
from orchestrator.defs.catalog import (
    ComputeEngine,
    EventPolicy,
    IngestionSource,
    PartitionModel,
    PartitionPhysicalLayout,
    WritePolicy,
    get_lake_asset_catalog_entry,
    get_partition_model_definition,
)
from orchestrator.defs.jobs.stock_daily_qfq_update import (
    gold_stock_daily_qfq_check_refresh_job,
    gold_stock_daily_qfq_update_job,
)
from orchestrator.defs.partitions import cn_a_stock_trade_days
from orchestrator.defs.paths import (
    gold_stock_daily_qfq_path,
    silver_adj_factor_path,
    silver_stock_daily_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STOCK_DAILY_QFQ_SCHEMA,
    SILVER_ADJ_FACTOR_SCHEMA,
    SILVER_STOCK_DAILY_SCHEMA,
    SILVER_TRADE_CALENDAR_SCHEMA,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.stock_daily_qfq import (
    GOLD_STOCK_DAILY_QFQ_COLUMNS,
    build_stock_daily_qfq_select_sql,
    load_stock_daily_qfq_previous_lookup_trade_dates,
    write_gold_stock_daily_qfq_partition,
)
from orchestrator.defs.run_contracts.metadata import (
    DAGSTER_COLUMN_SCHEMA_METADATA_KEY,
    DATASET_ID_METADATA_KEY,
)
from orchestrator.defs.sensors.readiness import (
    GOLD_STOCK_DAILY_QFQ_CHECKS,
    GOLD_STOCK_DAILY_QFQ_READINESS_SPECS,
    partition_dataset_readiness_status_from_latest_checks,
)


TRADE_DATE = "2026-06-18"
PREVIOUS_DATE = "2026-06-17"
EARLIER_DATE = "2026-06-16"


def _column_types(schema) -> dict[str, str]:
    return {column.name: column.type for column in schema}


def _write_rows(
    path: Path,
    *,
    column_types: dict[str, str],
    rows: list[dict[str, object]],
    order_by: str = "1",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = tuple(column_types)
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


def _ensure_test_lake_root_ready(root: Path) -> None:
    for part in ("raw", "silver", "gold", "_tmp"):
        (root / part).mkdir(parents=True, exist_ok=True)


def _stock_daily_row(
    ts_code: str,
    trade_date: str,
    *,
    close: float,
    open_: float | None = None,
) -> dict[str, object]:
    open_value = close - 0.5 if open_ is None else open_
    return {
        "ts_code": ts_code,
        "trade_date": trade_date,
        "open": open_value,
        "high": open_value + 1.0,
        "low": open_value - 1.0,
        "close": close,
        "pre_close": close - 1.0,
        "change_amount": 1.0,
        "pct_chg": 10.0,
        "vol": 100.0,
        "amount": 1000.0,
    }


def _adj_factor_row(ts_code: str, trade_date: str, adj_factor: float) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "trade_date": trade_date,
        "adj_factor": adj_factor,
    }


def _write_stock_daily(root: Path, trade_date: str, rows: list[dict[str, object]]) -> None:
    _write_rows(
        silver_stock_daily_path(root, trade_date),
        column_types=_column_types(SILVER_STOCK_DAILY_SCHEMA),
        rows=rows,
        order_by="ts_code, trade_date",
    )


def _write_adj_factor(root: Path, trade_date: str, rows: list[dict[str, object]]) -> None:
    _write_rows(
        silver_adj_factor_path(root, trade_date),
        column_types=_column_types(SILVER_ADJ_FACTOR_SCHEMA),
        rows=rows,
        order_by="ts_code, trade_date",
    )


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
            {
                "exchange": "SZSE",
                "trade_date": "2026-06-15",
                "is_open": True,
                "pretrade_date": "2026-06-12",
            },
        ],
        order_by="exchange, trade_date",
    )


def _fetch_output_rows(path: Path) -> list[dict[str, object]]:
    with duckdb.connect(database=":memory:") as connection:
        rows = connection.execute(
            f"""
            SELECT *
            FROM read_parquet('{path}', hive_partitioning=false)
            ORDER BY ts_code
            """
        ).fetchall()
    return [dict(zip(GOLD_STOCK_DAILY_QFQ_COLUMNS, row, strict=True)) for row in rows]


class StockDailyQfqContractTests(unittest.TestCase):
    def test_asset_definition_registers_partition_and_column_schema(self) -> None:
        self.assertEqual(gold_stock_daily_qfq.key.to_user_string(), "gold_stock_daily_qfq")
        self.assertEqual(gold_stock_daily_qfq.partitions_def, cn_a_stock_trade_days)
        spec = gold_stock_daily_qfq.get_asset_spec(gold_stock_daily_qfq.key)
        self.assertEqual(spec.metadata[DATASET_ID_METADATA_KEY], "stock_daily_qfq")
        self.assertIn(DAGSTER_COLUMN_SCHEMA_METADATA_KEY, spec.metadata)

    def test_catalog_entry_registers_trade_date_gold_qfq_contract(self) -> None:
        entry = get_lake_asset_catalog_entry("gold_stock_daily_qfq")
        partition_model = get_partition_model_definition(entry.partition_model)

        self.assertEqual(entry.dataset_id, "stock_daily_qfq")
        self.assertEqual(entry.column_schema, GOLD_STOCK_DAILY_QFQ_SCHEMA)
        self.assertEqual(
            entry.partition_model,
            PartitionModel.TRADE_DATE_PARTITION_GOLD_STOCK_DAILY_QFQ,
        )
        self.assertEqual(partition_model.asset_family, "stock_daily_qfq")
        self.assertEqual(partition_model.physical_layout, PartitionPhysicalLayout.PARTITION_FILE)
        self.assertEqual(entry.write_policy, WritePolicy.PARTITION_FILE_ATOMIC_REPLACE)
        self.assertEqual(entry.event_policy, EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL)
        self.assertEqual(entry.bootstrap_sources, (IngestionSource.DERIVED_FROM_ASSETS,))
        self.assertEqual(entry.performance_contract.compute_engine, ComputeEngine.DUCKDB_SQL)

    def test_readiness_uses_only_retained_contract_check(self) -> None:
        self.assertEqual(
            GOLD_STOCK_DAILY_QFQ_CHECKS,
            ("gold_stock_daily_qfq_contract_check",),
        )
        self.assertEqual(len(GOLD_STOCK_DAILY_QFQ_READINESS_SPECS), 1)
        spec = GOLD_STOCK_DAILY_QFQ_READINESS_SPECS[0]

        self.assertEqual(spec.asset_key.to_user_string(), "gold_stock_daily_qfq")
        self.assertEqual(spec.blocking_check_names, GOLD_STOCK_DAILY_QFQ_CHECKS)
        self.assertNotIn(
            "gold_stock_daily_qfq_factor_repair_plan_evaluated",
            spec.blocking_check_names,
        )

    def test_ordinary_checks_are_partitioned(self) -> None:
        self.assertEqual(
            gold_stock_daily_qfq_contract_check.partitions_def,
            cn_a_stock_trade_days,
        )

    def test_check_refresh_job_selects_checks_only(self) -> None:
        selected_assets = gold_stock_daily_qfq_check_refresh_job.selection.resolve(
            [gold_stock_daily_qfq]
        )

        self.assertEqual(
            gold_stock_daily_qfq_check_refresh_job.name,
            "gold_stock_daily_qfq_check_refresh_job",
        )
        self.assertEqual(
            gold_stock_daily_qfq_check_refresh_job.partitions_def,
            cn_a_stock_trade_days,
        )
        self.assertEqual(selected_assets, set())
        self.assertIn(
            "AssetChecksForAssetKeysSelection",
            repr(gold_stock_daily_qfq_check_refresh_job.selection),
        )
        self.assertNotIn(
            "KeysAssetSelection",
            repr(gold_stock_daily_qfq_check_refresh_job.selection),
        )

    def test_update_job_still_selects_asset_and_checks(self) -> None:
        selected_assets = gold_stock_daily_qfq_update_job.selection.resolve(
            [gold_stock_daily_qfq]
        )

        self.assertEqual(selected_assets, {gold_stock_daily_qfq.key})
        self.assertIn(
            "AssetChecksForAssetKeysSelection",
            repr(gold_stock_daily_qfq_update_job.selection),
        )
        self.assertIn(
            "KeysAssetSelection",
            repr(gold_stock_daily_qfq_update_job.selection),
        )

    def test_update_job_records_partitioned_checks_readable_by_readiness(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _ensure_test_lake_root_ready(root)
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

            instance = dg.DagsterInstance.ephemeral()
            instance.add_dynamic_partitions(cn_a_stock_trade_days.name, [TRADE_DATE])
            definitions = dg.Definitions(
                assets=[gold_stock_daily_qfq],
                asset_checks=[gold_stock_daily_qfq_contract_check],
                jobs=[gold_stock_daily_qfq_update_job],
                resources={
                    "lake_root": LakeRootResource(root_path=str(root)),
                    "duckdb": DuckDBResource(),
                },
            )

            result = definitions.resolve_job_def(
                "gold_stock_daily_qfq_update_job"
            ).execute_in_process(
                instance=instance,
                partition_key=TRADE_DATE,
                raise_on_error=True,
            )

            readiness = partition_dataset_readiness_status_from_latest_checks(
                instance,
                GOLD_STOCK_DAILY_QFQ_READINESS_SPECS,
                partition_key=TRADE_DATE,
            )

        self.assertTrue(result.success)
        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.statuses[0].missing_check_names, ())
        self.assertEqual(readiness.statuses[0].failed_check_names, ())

    def test_select_sql_describes_gold_stock_daily_qfq_schema(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
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

            sql = build_stock_daily_qfq_select_sql(
                stock_daily_path=silver_stock_daily_path(root, TRADE_DATE),
                trade_adj_factor_path=silver_adj_factor_path(root, TRADE_DATE),
                previous_stock_daily_paths=(),
                previous_adj_factor_paths=(),
                as_of_adj_factor_path=silver_adj_factor_path(root, TRADE_DATE),
                trade_date=TRADE_DATE,
                as_of_trade_date=TRADE_DATE,
            )
            with duckdb.connect(database=":memory:") as connection:
                described = connection.execute(f"DESCRIBE ({sql})").fetchall()

        self.assertEqual(
            [(column[0], column[1]) for column in described],
            [(column.name, column.type) for column in GOLD_STOCK_DAILY_QFQ_SCHEMA],
        )

    def test_writer_uses_qfq_formula_and_recomputes_previous_fields(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
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
                result = write_gold_stock_daily_qfq_partition(
                    connection=connection,
                    lake_root=root,
                    trade_date=TRADE_DATE,
                    previous_lookup_trade_dates=(PREVIOUS_DATE,),
                )

            rows = _fetch_output_rows(result.path)

        by_code = {row["ts_code"]: row for row in rows}
        self.assertEqual(result.output_row_count, 2)
        self.assertEqual(result.observed_columns, GOLD_STOCK_DAILY_QFQ_COLUMNS)
        self.assertAlmostEqual(by_code["000001.SZ"]["open"], 10.0)
        self.assertAlmostEqual(by_code["000001.SZ"]["close"], 10.5)
        self.assertAlmostEqual(by_code["000001.SZ"]["pre_close"], 4.5)
        self.assertAlmostEqual(by_code["000001.SZ"]["change_amount"], 6.0)
        self.assertAlmostEqual(
            by_code["000001.SZ"]["pct_chg"],
            (10.5 - 4.5) / 4.5 * 100,
        )
        self.assertAlmostEqual(by_code["600000.SH"]["pre_close"], 36.0)
        self.assertAlmostEqual(by_code["600000.SH"]["change_amount"], -15.5)

    def test_writer_sets_previous_fields_to_zero_for_first_available_row(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_stock_daily(
                root,
                TRADE_DATE,
                [_stock_daily_row("000001.SZ", TRADE_DATE, close=10.5, open_=10.0)],
            )
            _write_adj_factor(
                root,
                TRADE_DATE,
                [_adj_factor_row("000001.SZ", TRADE_DATE, 4.0)],
            )

            with duckdb.connect(database=":memory:") as connection:
                result = write_gold_stock_daily_qfq_partition(
                    connection=connection,
                    lake_root=root,
                    trade_date=TRADE_DATE,
                    previous_lookup_trade_dates=(),
                )

            rows = _fetch_output_rows(result.path)

        self.assertEqual(rows[0]["pre_close"], 0)
        self.assertEqual(rows[0]["change_amount"], 0)
        self.assertEqual(rows[0]["pct_chg"], 0)
        self.assertEqual(result.missing_previous_row_count, 1)

    def test_writer_fails_when_previous_row_exists_without_previous_factor(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
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

            with duckdb.connect(database=":memory:") as connection:
                with self.assertRaisesRegex(
                    ValueError,
                    "previous adj factor rows are missing",
                ):
                    write_gold_stock_daily_qfq_partition(
                        connection=connection,
                        lake_root=root,
                        trade_date=TRADE_DATE,
                        previous_lookup_trade_dates=(PREVIOUS_DATE,),
                    )

        self.assertFalse(gold_stock_daily_qfq_path(root, TRADE_DATE).exists())

    def test_previous_lookup_uses_sse_expected_calendar(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_calendar(root)

            with duckdb.connect(database=":memory:") as connection:
                trade_dates = load_stock_daily_qfq_previous_lookup_trade_dates(
                    connection=connection,
                    lake_root=root,
                    trade_date=TRADE_DATE,
                    limit=2,
                )

        self.assertEqual(trade_dates, (EARLIER_DATE, PREVIOUS_DATE))


if __name__ == "__main__":
    unittest.main()
