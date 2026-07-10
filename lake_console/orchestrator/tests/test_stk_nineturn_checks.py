import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import dagster as dg

from orchestrator.defs.assets.stk_nineturn import raw_tushare_stk_nineturn
from orchestrator.defs.checks.stk_nineturn_checks import (
    raw_tushare_stk_nineturn_content_integrity_check,
    raw_tushare_stk_nineturn_contract_check,
)
from orchestrator.defs.jobs.stk_nineturn_update import raw_stk_nineturn_update_job
from orchestrator.defs.partitions import cn_a_stock_trade_days
from orchestrator.defs.paths import raw_stk_nineturn_path
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    TushareResource,
    TushareResult,
)
from orchestrator.defs.stk_nineturn_contract import (
    RAW_STK_NINETURN_COLUMNS,
    RAW_STK_NINETURN_COLUMN_TYPES,
)


PARTITION_KEY = "2026-07-09"


class _CheckContext:
    def __init__(self, instance: dg.DagsterInstance) -> None:
        self.partition_key = PARTITION_KEY
        self.instance = instance


def _check_function(check_definition):
    return check_definition.node_def.compute_fn.decorated_fn


def _prepare_lake_root(root: Path) -> None:
    for layer in ("raw", "silver", "gold"):
        (root / layer).mkdir(parents=True, exist_ok=True)


def _raw_row(**overrides) -> dict[str, object]:
    row: dict[str, object] = {
        "ts_code": "600030.SH",
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


def _write_raw_rows(path: Path, rows: list[dict[str, object]]) -> None:
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


class StkNineturnCheckTests(unittest.TestCase):
    def _instance(self) -> dg.DagsterInstance:
        instance = dg.DagsterInstance.ephemeral()
        instance.add_dynamic_partitions(cn_a_stock_trade_days.name, [PARTITION_KEY])
        return instance

    def test_checks_inherit_stock_trade_day_partitions_from_asset(self) -> None:
        self.assertEqual(raw_tushare_stk_nineturn.partitions_def, cn_a_stock_trade_days)
        self.assertEqual(
            raw_tushare_stk_nineturn_contract_check.partitions_def,
            cn_a_stock_trade_days,
        )
        self.assertEqual(
            raw_tushare_stk_nineturn_content_integrity_check.partitions_def,
            cn_a_stock_trade_days,
        )

    def test_valid_partition_passes_both_checks(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _write_raw_rows(raw_stk_nineturn_path(root, PARTITION_KEY), [_raw_row()])
            context = _CheckContext(self._instance())

            contract = _check_function(raw_tushare_stk_nineturn_contract_check)(
                context,
                LakeRootResource(root_path=str(root)),
                DuckDBResource(),
            )
            content = _check_function(
                raw_tushare_stk_nineturn_content_integrity_check
            )(
                context,
                LakeRootResource(root_path=str(root)),
                DuckDBResource(),
            )

            self.assertTrue(contract.passed)
            self.assertTrue(content.passed)

    def test_duplicate_key_fails_content_integrity(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _write_raw_rows(
                raw_stk_nineturn_path(root, PARTITION_KEY),
                [_raw_row(), _raw_row()],
            )

            result = _check_function(
                raw_tushare_stk_nineturn_content_integrity_check
            )(
                _CheckContext(self._instance()),
                LakeRootResource(root_path=str(root)),
                DuckDBResource(),
            )

            self.assertFalse(result.passed)

    def test_partition_date_and_freq_fail_contract_check(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _write_raw_rows(
                raw_stk_nineturn_path(root, PARTITION_KEY),
                [_raw_row(trade_date="2026-07-08", freq="weekly")],
            )

            result = _check_function(raw_tushare_stk_nineturn_contract_check)(
                _CheckContext(self._instance()),
                LakeRootResource(root_path=str(root)),
                DuckDBResource(),
            )

            self.assertFalse(result.passed)

    def test_invalid_price_count_and_marker_fail_content_integrity(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _write_raw_rows(
                raw_stk_nineturn_path(root, PARTITION_KEY),
                [
                    _raw_row(
                        high=9.0,
                        up_count=2.5,
                        nine_up_turn="+9",
                    )
                ],
            )

            result = _check_function(
                raw_tushare_stk_nineturn_content_integrity_check
            )(
                _CheckContext(self._instance()),
                LakeRootResource(root_path=str(root)),
                DuckDBResource(),
            )

            self.assertFalse(result.passed)

    def test_raw_job_writes_partitioned_check_events(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            _prepare_lake_root(root)
            instance = self._instance()
            definitions = dg.Definitions(
                assets=[raw_tushare_stk_nineturn],
                asset_checks=[
                    raw_tushare_stk_nineturn_contract_check,
                    raw_tushare_stk_nineturn_content_integrity_check,
                ],
                jobs=[raw_stk_nineturn_update_job],
                resources={
                    "lake_root": LakeRootResource(root_path=str(root)),
                    "duckdb": DuckDBResource(),
                    "tushare": TushareResource(token="test-token"),
                },
            )
            tushare_result = TushareResult(
                rows=[
                    {
                        **_raw_row(),
                        "trade_date": "2026-07-09 00:00:00",
                    }
                ],
                columns=RAW_STK_NINETURN_COLUMNS,
                metadata={},
            )

            with patch.object(TushareResource, "call", return_value=tushare_result):
                result = definitions.resolve_job_def(
                    "raw_stk_nineturn_update_job"
                ).execute_in_process(
                    instance=instance,
                    partition_key=PARTITION_KEY,
                    raise_on_error=True,
                )

            check_events = [
                event
                for event in result.all_events
                if event.event_type == dg.DagsterEventType.ASSET_CHECK_EVALUATION
            ]

            self.assertTrue(result.success)
            self.assertEqual(len(check_events), 2)
            self.assertEqual(
                {
                    event.event_specific_data.partition
                    for event in check_events
                },
                {PARTITION_KEY},
            )
            for check_event in check_events:
                evaluation = check_event.event_specific_data
                records = instance.event_log_storage.get_asset_check_execution_history(
                    evaluation.asset_check_key,
                    limit=1,
                )
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0].partition, PARTITION_KEY)


if __name__ == "__main__":
    unittest.main()
