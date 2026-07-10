import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import dagster as dg

from orchestrator.defs.assets.stk_nineturn import silver_stock_nineturn_daily
from orchestrator.defs.checks.stk_nineturn_checks import (
    silver_stock_nineturn_daily_canonical_integrity_check,
    silver_stock_nineturn_daily_contract_check,
)
from orchestrator.defs.jobs.stk_nineturn_update import (
    silver_stock_nineturn_daily_update_job,
)
from orchestrator.defs.partitions import cn_a_stock_trade_days
from orchestrator.defs.paths import (
    raw_stk_nineturn_path,
    silver_stock_identity_map_path,
    silver_stock_nineturn_daily_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.stk_nineturn_contract import (
    RAW_STK_NINETURN_COLUMNS,
    RAW_STK_NINETURN_COLUMN_TYPES,
    SILVER_STOCK_NINETURN_DAILY_COLUMNS,
    write_silver_stock_nineturn_daily_partition,
)


PARTITION_KEY = "2026-07-09"
CANONICAL_CODE = "920001.BJ"
OLD_CODE = "830001.BJ"
SECOND_OLD_CODE = "831001.BJ"


class _CheckContext:
    def __init__(self, instance: dg.DagsterInstance) -> None:
        self.partition_key = PARTITION_KEY
        self.instance = instance


def _check_function(check_definition):
    return check_definition.node_def.compute_fn.decorated_fn


def _prepare_lake_root(root: Path) -> None:
    for layer in ("raw", "silver", "gold"):
        (root / layer).mkdir(parents=True, exist_ok=True)


def _raw_row(ts_code: str, **overrides) -> dict[str, object]:
    row: dict[str, object] = {
        "ts_code": ts_code,
        "trade_date": PARTITION_KEY,
        "freq": "daily",
        "open": 10.0,
        "high": 11.0,
        "low": 9.0,
        "close": 10.5,
        "vol": 100.0,
        "amount": 1000.0,
        "up_count": 0.0,
        "down_count": 3.0,
        "nine_up_turn": None,
        "nine_down_turn": None,
    }
    row.update(overrides)
    return row


def _write_raw_rows(root: Path, rows: list[dict[str, object]]) -> None:
    path = raw_stk_nineturn_path(root, PARTITION_KEY)
    path.parent.mkdir(parents=True, exist_ok=True)
    with DuckDBResource().connect() as connection:
        column_defs = ", ".join(
            f'"{column}" {RAW_STK_NINETURN_COLUMN_TYPES[column]}'
            for column in RAW_STK_NINETURN_COLUMNS
        )
        connection.execute(f"CREATE TEMP TABLE rows_to_write ({column_defs})")
        placeholders = ", ".join("?" for _column in RAW_STK_NINETURN_COLUMNS)
        connection.executemany(
            f"INSERT INTO rows_to_write VALUES ({placeholders})",
            [
                [row.get(column) for column in RAW_STK_NINETURN_COLUMNS]
                for row in rows
            ],
        )
        connection.execute(
            f"""
            COPY (
              SELECT {', '.join(f'"{column}"' for column in RAW_STK_NINETURN_COLUMNS)}
              FROM rows_to_write
              ORDER BY ts_code
            ) TO '{path.as_posix()}' (FORMAT PARQUET)
            """
        )


def _write_identity_rows(
    root: Path,
    rows: list[tuple[str, str, str, str | None]],
) -> None:
    path = silver_stock_identity_map_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with DuckDBResource().connect() as connection:
        connection.execute(
            """
            CREATE TEMP TABLE identity_rows (
              latest_ts_code VARCHAR,
              source_ts_code VARCHAR,
              valid_from DATE,
              valid_to DATE
            )
            """
        )
        connection.executemany(
            "INSERT INTO identity_rows VALUES (?, ?, ?, ?)",
            rows,
        )
        connection.execute(
            f"""
            COPY (
              SELECT * FROM identity_rows ORDER BY source_ts_code
            ) TO '{path.as_posix()}' (FORMAT PARQUET)
            """
        )


def _read_silver_rows(root: Path) -> list[tuple[object, ...]]:
    path = silver_stock_nineturn_daily_path(root, PARTITION_KEY)
    with DuckDBResource().connect() as connection:
        return connection.execute(
            f"""
            SELECT {', '.join(SILVER_STOCK_NINETURN_DAILY_COLUMNS)}
            FROM read_parquet('{path.as_posix()}', hive_partitioning=false)
            ORDER BY ts_code
            """
        ).fetchall()


class StkNineturnSilverTests(unittest.TestCase):
    def test_writer_prefers_canonical_row_for_resolvable_signal_conflict(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _prepare_lake_root(root)
            _write_raw_rows(
                root,
                [
                    _raw_row(OLD_CODE, down_count=3.0),
                    _raw_row(
                        CANONICAL_CODE,
                        up_count=9.0,
                        down_count=0.0,
                        nine_up_turn="+9",
                    ),
                ],
            )
            _write_identity_rows(
                root,
                [
                    (CANONICAL_CODE, OLD_CODE, "2021-11-15", None),
                    (CANONICAL_CODE, CANONICAL_CODE, "2021-11-15", None),
                ],
            )

            result = write_silver_stock_nineturn_daily_partition(
                lake_root=root,
                duckdb=DuckDBResource(),
                partition_key=PARTITION_KEY,
            )
            rows = _read_silver_rows(root)

            self.assertEqual(result.source_row_count, 2)
            self.assertEqual(result.row_count, 1)
            self.assertEqual(result.alias_duplicate_key_count, 1)
            self.assertEqual(result.count_signal_conflict_key_count, 1)
            self.assertEqual(result.market_value_conflict_key_count, 0)
            self.assertEqual(result.unmapped_source_code_count, 0)
            self.assertEqual(rows[0][0], CANONICAL_CODE)
            self.assertEqual(rows[0][9:13], (9, 0, "+9", None))

    def test_writer_maps_old_only_row_without_changing_business_values(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _prepare_lake_root(root)
            _write_raw_rows(root, [_raw_row(OLD_CODE, down_count=8.0)])
            _write_identity_rows(
                root,
                [(CANONICAL_CODE, OLD_CODE, "2021-11-15", None)],
            )

            result = write_silver_stock_nineturn_daily_partition(
                lake_root=root,
                duckdb=DuckDBResource(),
                partition_key=PARTITION_KEY,
            )
            row = _read_silver_rows(root)[0]

            self.assertEqual(result.row_count, 1)
            self.assertEqual(row[0], CANONICAL_CODE)
            self.assertEqual(row[9:13], (0, 8, None, None))

    def test_writer_deduplicates_equal_alias_rows_deterministically(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _prepare_lake_root(root)
            _write_raw_rows(
                root,
                [_raw_row(OLD_CODE), _raw_row(SECOND_OLD_CODE)],
            )
            _write_identity_rows(
                root,
                [
                    (CANONICAL_CODE, OLD_CODE, "2021-11-15", None),
                    (CANONICAL_CODE, SECOND_OLD_CODE, "2021-11-15", None),
                ],
            )

            result = write_silver_stock_nineturn_daily_partition(
                lake_root=root,
                duckdb=DuckDBResource(),
                partition_key=PARTITION_KEY,
            )

            self.assertEqual(result.alias_duplicate_key_count, 1)
            self.assertEqual(result.count_signal_conflict_key_count, 0)
            self.assertEqual(len(_read_silver_rows(root)), 1)

    def test_writer_fails_closed_when_source_code_is_unmapped(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _prepare_lake_root(root)
            _write_raw_rows(root, [_raw_row(OLD_CODE)])
            _write_identity_rows(
                root,
                [(CANONICAL_CODE, CANONICAL_CODE, "2021-11-15", None)],
            )

            with self.assertRaisesRegex(RuntimeError, "unmapped source codes"):
                write_silver_stock_nineturn_daily_partition(
                    lake_root=root,
                    duckdb=DuckDBResource(),
                    partition_key=PARTITION_KEY,
                )

            self.assertFalse(
                silver_stock_nineturn_daily_path(root, PARTITION_KEY).exists()
            )

    def test_writer_treats_expired_identity_interval_as_unmapped(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _prepare_lake_root(root)
            _write_raw_rows(root, [_raw_row(OLD_CODE)])
            _write_identity_rows(
                root,
                [(CANONICAL_CODE, OLD_CODE, "2021-11-15", PARTITION_KEY)],
            )

            with self.assertRaisesRegex(RuntimeError, "unmapped source codes"):
                write_silver_stock_nineturn_daily_partition(
                    lake_root=root,
                    duckdb=DuckDBResource(),
                    partition_key=PARTITION_KEY,
                )

    def test_writer_fails_closed_on_overlapping_identity_rows(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _prepare_lake_root(root)
            _write_raw_rows(root, [_raw_row(OLD_CODE)])
            _write_identity_rows(
                root,
                [
                    (CANONICAL_CODE, OLD_CODE, "2021-11-15", None),
                    ("920002.BJ", OLD_CODE, "2021-11-15", None),
                ],
            )

            with self.assertRaisesRegex(RuntimeError, "ambiguous identity mappings"):
                write_silver_stock_nineturn_daily_partition(
                    lake_root=root,
                    duckdb=DuckDBResource(),
                    partition_key=PARTITION_KEY,
                )

    def test_writer_fails_closed_on_market_value_conflict(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _prepare_lake_root(root)
            _write_raw_rows(
                root,
                [_raw_row(OLD_CODE), _raw_row(CANONICAL_CODE, close=10.6)],
            )
            _write_identity_rows(
                root,
                [
                    (CANONICAL_CODE, OLD_CODE, "2021-11-15", None),
                    (CANONICAL_CODE, CANONICAL_CODE, "2021-11-15", None),
                ],
            )

            with self.assertRaisesRegex(RuntimeError, "market value conflicts"):
                write_silver_stock_nineturn_daily_partition(
                    lake_root=root,
                    duckdb=DuckDBResource(),
                    partition_key=PARTITION_KEY,
                )

            self.assertFalse(
                silver_stock_nineturn_daily_path(root, PARTITION_KEY).exists()
            )

    def test_writer_fails_on_signal_conflict_without_canonical_source(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _prepare_lake_root(root)
            _write_raw_rows(
                root,
                [
                    _raw_row(OLD_CODE, down_count=2.0),
                    _raw_row(SECOND_OLD_CODE, down_count=3.0),
                ],
            )
            _write_identity_rows(
                root,
                [
                    (CANONICAL_CODE, OLD_CODE, "2021-11-15", None),
                    (CANONICAL_CODE, SECOND_OLD_CODE, "2021-11-15", None),
                ],
            )

            with self.assertRaisesRegex(
                RuntimeError,
                "without canonical source rows",
            ):
                write_silver_stock_nineturn_daily_partition(
                    lake_root=root,
                    duckdb=DuckDBResource(),
                    partition_key=PARTITION_KEY,
                )

            self.assertFalse(
                silver_stock_nineturn_daily_path(root, PARTITION_KEY).exists()
            )

    def test_writer_does_not_overwrite_existing_partition_by_default(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _prepare_lake_root(root)
            _write_raw_rows(root, [_raw_row(CANONICAL_CODE)])
            _write_identity_rows(
                root,
                [(CANONICAL_CODE, CANONICAL_CODE, "2021-11-15", None)],
            )
            write_silver_stock_nineturn_daily_partition(
                lake_root=root,
                duckdb=DuckDBResource(),
                partition_key=PARTITION_KEY,
            )

            with self.assertRaises(FileExistsError):
                write_silver_stock_nineturn_daily_partition(
                    lake_root=root,
                    duckdb=DuckDBResource(),
                    partition_key=PARTITION_KEY,
                )

    def test_canonical_check_detects_tampered_silver_values(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _prepare_lake_root(root)
            _write_raw_rows(root, [_raw_row(CANONICAL_CODE)])
            _write_identity_rows(
                root,
                [(CANONICAL_CODE, CANONICAL_CODE, "2021-11-15", None)],
            )
            write_silver_stock_nineturn_daily_partition(
                lake_root=root,
                duckdb=DuckDBResource(),
                partition_key=PARTITION_KEY,
            )
            target_path = silver_stock_nineturn_daily_path(root, PARTITION_KEY)
            temporary_path = target_path.with_name("tampered.parquet")
            with DuckDBResource().connect() as connection:
                connection.execute(
                    f"""
                    COPY (
                      SELECT
                        ts_code, trade_date, freq, open, high, low, close,
                        vol, amount, up_count, down_count + 1 AS down_count,
                        nine_up_turn, nine_down_turn
                      FROM read_parquet(
                        '{target_path.as_posix()}',
                        hive_partitioning=false
                      )
                    ) TO '{temporary_path.as_posix()}' (FORMAT PARQUET)
                    """
                )
            temporary_path.replace(target_path)
            instance = dg.DagsterInstance.ephemeral()
            instance.add_dynamic_partitions(
                cn_a_stock_trade_days.name,
                [PARTITION_KEY],
            )

            result = _check_function(
                silver_stock_nineturn_daily_canonical_integrity_check
            )(
                _CheckContext(instance),
                LakeRootResource(root_path=str(root)),
                DuckDBResource(),
            )

            self.assertFalse(result.passed)

    def test_silver_job_writes_partitioned_checks(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _prepare_lake_root(root)
            _write_raw_rows(root, [_raw_row(CANONICAL_CODE)])
            _write_identity_rows(
                root,
                [(CANONICAL_CODE, CANONICAL_CODE, "2021-11-15", None)],
            )
            instance = dg.DagsterInstance.ephemeral()
            instance.add_dynamic_partitions(
                cn_a_stock_trade_days.name,
                [PARTITION_KEY],
            )
            definitions = dg.Definitions(
                assets=[
                    dg.AssetSpec(
                        key="raw_tushare_stk_nineturn",
                        partitions_def=cn_a_stock_trade_days,
                    ),
                    dg.AssetSpec(key="silver_stock_identity_map"),
                    silver_stock_nineturn_daily,
                ],
                asset_checks=[
                    silver_stock_nineturn_daily_contract_check,
                    silver_stock_nineturn_daily_canonical_integrity_check,
                ],
                jobs=[silver_stock_nineturn_daily_update_job],
                resources={
                    "lake_root": LakeRootResource(root_path=str(root)),
                    "duckdb": DuckDBResource(),
                },
            )

            result = definitions.resolve_job_def(
                "silver_stock_nineturn_daily_update_job"
            ).execute_in_process(
                instance=instance,
                partition_key=PARTITION_KEY,
                raise_on_error=True,
            )
            check_events = [
                event.event_specific_data
                for event in result.all_events
                if event.event_type == dg.DagsterEventType.ASSET_CHECK_EVALUATION
            ]

            self.assertTrue(result.success)
            self.assertEqual(len(check_events), 2)
            self.assertEqual(
                {evaluation.partition for evaluation in check_events},
                {PARTITION_KEY},
            )


if __name__ == "__main__":
    unittest.main()
