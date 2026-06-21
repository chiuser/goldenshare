from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import dagster as dg
import duckdb
from dagster._core.storage.asset_check_execution_record import (
    AssetCheckExecutionRecordStatus,
)

from orchestrator.defs.bootstrap.stk_mins_name_timeline_check_events import (
    TARGET_TS_CODE,
    build_silver_name_timeline_correction_candidates,
    correction_event_metadata,
    dry_run_silver_name_timeline_check_event_correction,
)
from orchestrator.defs.checks.stk_mins_checks import (
    SILVER_STK_MINS_NAME_TIMELINE_COVERED_CHECK,
)
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.paths import (
    silver_stk_mins_path,
    silver_stock_lifecycle_path,
    silver_trade_calendar_path,
)


class _FakeEventLogStorage:
    def __init__(self, records_by_check_key):
        self.records_by_check_key = records_by_check_key
        self.calls = []

    def get_asset_check_execution_history(
        self,
        check_key,
        *,
        limit,
        cursor=None,
        status=None,
        partition_filter=None,
    ):
        if partition_filter is not None:
            raise AssertionError("P8A dry-run must not use per-partition history reads")
        self.calls.append((check_key, limit, cursor, status))
        records = sorted(
            self.records_by_check_key.get(check_key, ()),
            key=lambda record: record.id,
            reverse=True,
        )
        if status:
            records = [record for record in records if record.status in status]
        if cursor is not None:
            records = [record for record in records if record.id < cursor]
        return records[:limit]


class _FakeInstance:
    def __init__(self, *, materialized_by_asset, records_by_check_key):
        self.materialized_by_asset = materialized_by_asset
        self.event_log_storage = _FakeEventLogStorage(records_by_check_key)

    def get_materialized_partitions(self, asset_key):
        return set(self.materialized_by_asset.get(asset_key, ()))

    def report_runless_asset_event(self, _event):
        raise AssertionError("P8A dry-run must not write runless events")


class StkMinsNameTimelineCheckEventDryRunTests(unittest.TestCase):
    def test_candidates_use_silver_stock_lifecycle(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            with duckdb.connect(database=":memory:") as connection:
                _write_calendar(connection, lake_root, ["2026-04-10"])
                _write_stock_lifecycle(
                    connection,
                    lake_root,
                    list_date="2014-01-02",
                    delist_date="2026-06-03",
                )
                _write_silver_file(connection, lake_root, "2026-04-10", freq=1)

                candidates = build_silver_name_timeline_correction_candidates(
                    connection,
                    lake_root=lake_root,
                    end_date="2026-04-13",
                )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].freq, 1)
        self.assertEqual(candidates[0].partition_key, "2026-04-10")
        self.assertEqual(candidates[0].asset_key, "silver_stk_mins_1m")
        self.assertEqual(candidates[0].target_row_count, 1)

    def test_candidates_fail_closed_when_target_lifecycle_is_not_covered(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            with duckdb.connect(database=":memory:") as connection:
                _write_calendar(connection, lake_root, ["2026-04-10"])
                _write_stock_lifecycle(
                    connection,
                    lake_root,
                    list_date="2014-01-02",
                    delist_date="2026-04-09",
                )
                _write_silver_file(connection, lake_root, "2026-04-10", freq=1)

                with self.assertRaisesRegex(ValueError, "target lifecycle check failed"):
                    build_silver_name_timeline_correction_candidates(
                        connection,
                        lake_root=lake_root,
                        end_date="2026-04-13",
                    )

    def test_dry_run_counts_failed_passed_missing_and_materialization(self) -> None:
        dates = ("2026-04-10", "2026-04-11", "2026-04-12", "2026-04-13")
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            with duckdb.connect(database=":memory:") as connection:
                _write_calendar(connection, lake_root, dates)
                _write_stock_lifecycle(
                    connection,
                    lake_root,
                    list_date="2014-01-02",
                    delist_date="2026-06-03",
                )
                for trade_date in dates:
                    _write_silver_file(connection, lake_root, trade_date, freq=1)

                asset_key = dg.AssetKey("silver_stk_mins_1m")
                check_key = dg.AssetCheckKey(
                    asset_key,
                    SILVER_STK_MINS_NAME_TIMELINE_COVERED_CHECK,
                )
                instance = _FakeInstance(
                    materialized_by_asset={
                        asset_key: {"2026-04-10", "2026-04-11", "2026-04-12"}
                    },
                    records_by_check_key={
                        check_key: (
                            _fake_check_record(
                                record_id=3,
                                partition_key="2026-04-11",
                                status=AssetCheckExecutionRecordStatus.SUCCEEDED,
                                passed=True,
                            ),
                            _fake_check_record(
                                record_id=2,
                                partition_key="2026-04-13",
                                status=AssetCheckExecutionRecordStatus.FAILED,
                                passed=False,
                            ),
                            _fake_check_record(
                                record_id=1,
                                partition_key="2026-04-10",
                                status=AssetCheckExecutionRecordStatus.FAILED,
                                passed=False,
                            ),
                        )
                    },
                )

                report = dry_run_silver_name_timeline_check_event_correction(
                    instance=instance,
                    connection=connection,
                    lake_root=lake_root,
                    end_date="2026-04-13",
                    history_page_limit=2,
                )

        self.assertEqual(report.candidate_event_count, 4)
        self.assertEqual(report.historical_failed_event_count, 2)
        self.assertEqual(report.historical_check_event_count, 3)
        self.assertEqual(report.existing_latest_passed_count, 1)
        self.assertEqual(report.latest_failed_candidate_count, 1)
        self.assertEqual(report.missing_check_event_count, 1)
        self.assertEqual(report.missing_target_materialization_count, 1)
        self.assertEqual(report.planned_new_event_count, 1)
        self.assertEqual(report.stop_reasons, ("missing_target_materialization",))
        self.assertEqual(
            report.latest_failed_samples[0].partition_key,
            "2026-04-10",
        )
        self.assertGreaterEqual(len(instance.event_log_storage.calls), 2)

    def test_scope_is_locked_to_000638(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            with duckdb.connect(database=":memory:") as connection:
                _write_calendar(connection, lake_root, ["2026-04-10"])
                _write_stock_lifecycle(connection, lake_root)

                with self.assertRaisesRegex(ValueError, "Unsupported ts_code"):
                    build_silver_name_timeline_correction_candidates(
                        connection,
                        lake_root=lake_root,
                        ts_code="000001.SZ",
                    )

    def test_correction_metadata_documents_future_green_event_contract(self) -> None:
        self.assertEqual(
            correction_event_metadata(),
            {
                "source_correction_reason": "000638_lifecycle_check_semantics_fix",
                "ts_code": TARGET_TS_CODE,
                "lifecycle_fact_source": "silver_stock_lifecycle",
                "checked_code_date_freq_count": 1,
                "failed_code_date_freq_count": 0,
            },
        )


def _write_calendar(connection, lake_root: Path, trade_dates: tuple[str, ...] | list[str]) -> None:
    path = silver_trade_calendar_path(lake_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = " UNION ALL ".join(
        f"""
        SELECT
          'SSE'::VARCHAR AS exchange,
          CAST({duckdb_string(trade_date)} AS DATE) AS trade_date,
          true AS is_open,
          NULL::DATE AS pretrade_date
        """
        for trade_date in trade_dates
    )
    connection.execute(f"COPY ({rows}) TO {duckdb_string(path)} (FORMAT PARQUET)")


def _write_stock_lifecycle(
    connection,
    lake_root: Path,
    *,
    ts_code: str = TARGET_TS_CODE,
    list_date: str = "2014-01-02",
    delist_date: str = "2026-06-03",
) -> None:
    path = silver_stock_lifecycle_path(lake_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection.execute(
        f"""
        COPY (
          SELECT
            {duckdb_string(ts_code)} AS ts_code,
            '000638'::VARCHAR AS symbol,
            'sample'::VARCHAR AS name,
            'SZSE'::VARCHAR AS exchange,
            '主板'::VARCHAR AS market,
            'CNY'::VARCHAR AS curr_type,
            true AS is_cny_stock,
            'D'::VARCHAR AS list_status,
            DATE {duckdb_string(list_date)} AS list_date,
            DATE {duckdb_string(delist_date)} AS delist_date
        ) TO {duckdb_string(path)} (FORMAT PARQUET)
        """
    )


def _write_silver_file(
    connection,
    lake_root: Path,
    trade_date: str,
    *,
    freq: int,
    ts_code: str = TARGET_TS_CODE,
) -> None:
    path = silver_stk_mins_path(lake_root, freq, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection.execute(
        f"""
        COPY (
          SELECT
            {duckdb_string(ts_code)} AS ts_code,
            {freq}::INTEGER AS freq,
            CAST({duckdb_string(trade_date)} AS DATE) AS trade_date,
            CAST({duckdb_string(trade_date + " 09:31:00")} AS TIMESTAMP) AS trade_time,
            10.0::DOUBLE AS open,
            10.5::DOUBLE AS high,
            9.8::DOUBLE AS low,
            10.2::DOUBLE AS close,
            100.0::DOUBLE AS vol,
            1000.0::DOUBLE AS amount,
            'SZSE'::VARCHAR AS exchange
        ) TO {duckdb_string(path)} (FORMAT PARQUET)
        """
    )


def _fake_check_record(
    *,
    record_id: int,
    partition_key: str,
    status,
    passed: bool,
):
    evaluation = SimpleNamespace(
        asset_key=dg.AssetKey("silver_stk_mins_1m"),
        check_name=SILVER_STK_MINS_NAME_TIMELINE_COVERED_CHECK,
        partition=partition_key,
        passed=passed,
        blocking=True,
    )
    event = SimpleNamespace(
        run_id=f"run-{record_id}",
        timestamp=float(record_id),
        dagster_event=SimpleNamespace(event_specific_data=evaluation),
    )
    return SimpleNamespace(
        id=record_id,
        partition=partition_key,
        status=status,
        event=event,
    )


if __name__ == "__main__":
    unittest.main()
