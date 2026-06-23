import json
import tempfile
import unittest
from pathlib import Path

import dagster as dg
import duckdb

from orchestrator.defs.bootstrap.index_daily_raw_by_date_runless_events import (
    RAW_INDEX_DAILY_ASSET_KEY,
    RAW_INDEX_DAILY_CHECKS,
    audit_raw_index_daily_runless_partition,
    plan_raw_index_daily_recent_window_events,
    raw_index_daily_by_code_source_glob,
    report_raw_index_daily_recent_window_events,
)
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.partitions import cn_a_index_trade_days, cn_a_index_ts_codes
from orchestrator.defs.paths import raw_index_daily_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.sensors.readiness import AssetReadinessSpec, asset_readiness_status


INDEX_DAILY_COLUMNS = (
    "ts_code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "change",
    "pct_chg",
    "vol",
    "amount",
)


def _raw_trade_date(partition_key: str) -> str:
    return partition_key.replace("-", "")


def _index_daily_row(ts_code: str, partition_key: str) -> tuple[object, ...]:
    return (
        ts_code,
        _raw_trade_date(partition_key),
        1.0,
        2.0,
        0.5,
        1.5,
        1.4,
        0.1,
        7.1429,
        1000.0,
        2000.0,
    )


def _sql_literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, str):
        return f"{duckdb_string(value)}::VARCHAR"
    return f"{value}::DOUBLE"


def _write_index_daily_file(path: Path, rows: tuple[tuple[object, ...], ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    values_sql = ", ".join(
        "(" + ", ".join(_sql_literal(value) for value in row) + ")"
        for row in rows
    )
    column_sql = ", ".join(INDEX_DAILY_COLUMNS)
    with duckdb.connect(database=":memory:") as connection:
        connection.execute(
            f"""
            COPY (
              SELECT *
              FROM (VALUES {values_sql}) rows({column_sql})
            ) TO {duckdb_string(path)} (FORMAT PARQUET)
            """
        )


def _write_source_by_code_files(
    root: Path,
    partitions: tuple[str, ...],
    codes: tuple[str, ...],
) -> None:
    for code in codes:
        path = (
            root
            / "raw"
            / "tushare"
            / "index_daily_by_code"
            / f"ts_code={code}"
            / "part-000.parquet"
        )
        rows = tuple(_index_daily_row(code, partition_key) for partition_key in partitions)
        _write_index_daily_file(path, rows)


def _write_target_by_date_files(
    root: Path,
    partitions: tuple[str, ...],
    codes: tuple[str, ...],
) -> None:
    for partition_key in partitions:
        rows = tuple(_index_daily_row(code, partition_key) for code in codes)
        _write_index_daily_file(raw_index_daily_path(root, partition_key), rows)


def _write_p3_report(root: Path, path: Path, partitions: tuple[str, ...], rows: int) -> None:
    payload = {
        "failures": {},
        "forbidden_partition_exists": False,
        "target_file_count": len(partitions),
        "target_partition_dir_count": len(partitions),
        "target_min_trade_date": _raw_trade_date(min(partitions)),
        "target_max_trade_date": _raw_trade_date(max(partitions)),
        "target_root": str(root / "raw" / "index_daily"),
        "target_rows": rows,
        "target_distinct_pairs": rows,
        "source_minus_target_pairs": 0,
        "source_minus_target_rows": 0,
        "target_minus_source_pairs": 0,
        "target_minus_source_rows": 0,
        "target_duplicate_pairs": 0,
        "target_excluded_rows": 0,
        "target_null_key_rows": 0,
    }
    path.write_text(json.dumps(payload))


def _instance_with_partitions(
    partition_keys: tuple[str, ...],
    index_codes: tuple[str, ...],
) -> dg.DagsterInstance:
    instance = dg.DagsterInstance.ephemeral()
    instance.add_dynamic_partitions(cn_a_index_trade_days.name, list(partition_keys))
    instance.add_dynamic_partitions(cn_a_index_ts_codes.name, list(index_codes))
    return instance


class IndexDailyRawByDateRunlessEventTests(unittest.TestCase):
    def test_dry_run_counts_recent_window_and_does_not_write_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            partitions = ("2026-06-01", "2026-06-02", "2026-06-03")
            codes = ("000001.SH", "000002.SH")
            _write_source_by_code_files(root, partitions, codes)
            _write_target_by_date_files(root, partitions, codes)
            p3_report = root / "p3_report.json"
            _write_p3_report(root, p3_report, partitions, rows=len(partitions) * len(codes))
            instance = _instance_with_partitions(partitions, codes)

            report = report_raw_index_daily_recent_window_events(
                instance=instance,
                lake_root=root,
                duckdb=DuckDBResource(),
                p3_final_audit_report_path=p3_report,
                window_limit=3,
                dry_run=True,
            )
            materializations = instance.fetch_materializations(
                dg.AssetRecordsFilter(
                    asset_key=RAW_INDEX_DAILY_ASSET_KEY,
                    asset_partitions=[partitions[-1]],
                ),
                limit=1,
            ).records

        json.dumps(report.to_payload())
        self.assertFalse(report.should_stop)
        self.assertEqual(report.plan.selected_partition_keys, partitions)
        self.assertEqual(report.planned_new_event_count, 9)
        self.assertEqual(report.reported_event_count, 0)
        self.assertEqual(materializations, [])

    def test_reports_runless_materialization_and_two_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            partitions = ("2026-06-03",)
            codes = ("000001.SH", "000002.SH")
            _write_source_by_code_files(root, partitions, codes)
            _write_target_by_date_files(root, partitions, codes)
            p3_report = root / "p3_report.json"
            _write_p3_report(root, p3_report, partitions, rows=2)
            instance = _instance_with_partitions(partitions, codes)

            report = report_raw_index_daily_recent_window_events(
                instance=instance,
                lake_root=root,
                duckdb=DuckDBResource(),
                p3_final_audit_report_path=p3_report,
                partition_keys=partitions,
                dry_run=False,
            )
            readiness = asset_readiness_status(
                instance,
                AssetReadinessSpec(RAW_INDEX_DAILY_ASSET_KEY, RAW_INDEX_DAILY_CHECKS),
                partition_key=partitions[0],
            )
            materialization = instance.fetch_materializations(
                dg.AssetRecordsFilter(
                    asset_key=RAW_INDEX_DAILY_ASSET_KEY,
                    asset_partitions=[partitions[0]],
                ),
                limit=1,
            ).records[0]
            target_storage_ids = []
            for check_name in RAW_INDEX_DAILY_CHECKS:
                history = instance.event_log_storage.get_asset_check_execution_history(
                    dg.AssetCheckKey(RAW_INDEX_DAILY_ASSET_KEY, check_name),
                    limit=1,
                )
                evaluation = history[0].event.dagster_event.event_specific_data
                target_storage_ids.append(
                    evaluation.target_materialization_data.storage_id
                )

        self.assertEqual(report.reported_partition_keys, partitions)
        self.assertEqual(report.reported_event_count, 3)
        self.assertTrue(readiness.ready)
        self.assertEqual(target_storage_ids, [materialization.storage_id] * 2)

    def test_source_target_pair_diff_blocks_green_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            partition_key = "2026-06-03"
            source_codes = ("000001.SH", "000002.SH")
            target_codes = ("000001.SH",)
            _write_source_by_code_files(root, (partition_key,), source_codes)
            _write_target_by_date_files(root, (partition_key,), target_codes)
            p3_report = root / "p3_report.json"
            _write_p3_report(root, p3_report, (partition_key,), rows=1)
            instance = _instance_with_partitions((partition_key,), source_codes)

            report = report_raw_index_daily_recent_window_events(
                instance=instance,
                lake_root=root,
                duckdb=DuckDBResource(),
                p3_final_audit_report_path=p3_report,
                partition_keys=(partition_key,),
                dry_run=True,
            )
            with self.assertRaisesRegex(ValueError, "runless audit failed"):
                report_raw_index_daily_recent_window_events(
                    instance=instance,
                    lake_root=root,
                    duckdb=DuckDBResource(),
                    p3_final_audit_report_path=p3_report,
                    partition_keys=(partition_key,),
                    dry_run=False,
                )

        self.assertTrue(report.should_stop)
        self.assertEqual(report.plan.failed_partition_count, 1)
        self.assertIn(
            "raw_index_daily_code_coverage_check",
            report.plan.partition_audits[0].failed_check_names,
        )

    def test_duplicate_key_blocks_file_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            partition_key = "2026-06-03"
            codes = ("000001.SH",)
            _write_source_by_code_files(root, (partition_key,), codes)
            _write_index_daily_file(
                raw_index_daily_path(root, partition_key),
                (
                    _index_daily_row("000001.SH", partition_key),
                    _index_daily_row("000001.SH", partition_key),
                ),
            )
            p3_report = root / "p3_report.json"
            _write_p3_report(root, p3_report, (partition_key,), rows=2)
            instance = _instance_with_partitions((partition_key,), codes)

            audit = audit_raw_index_daily_runless_partition(
                lake_root=root,
                duckdb=DuckDBResource(),
                partition_key=partition_key,
                source_glob=raw_index_daily_by_code_source_glob(root),
                registered_index_codes=codes,
                p3_final_audit_report_path=p3_report,
            )

        self.assertFalse(audit.passed)
        self.assertIn("raw_index_daily_file_contract_check", audit.failed_check_names)

    def test_window_limit_over_recent_limit_fails(self) -> None:
        instance = _instance_with_partitions((), ("000001.SH",))
        with self.assertRaisesRegex(ValueError, "must not exceed"):
            plan_raw_index_daily_recent_window_events(
                instance=instance,
                lake_root=Path("/tmp/unused"),
                duckdb=DuckDBResource(),
                p3_final_audit_report_path=Path("/tmp/missing.json"),
                window_limit=21,
            )

    def test_existing_non_ready_materialization_blocks_apply(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            partition_key = "2026-06-03"
            codes = ("000001.SH",)
            _write_source_by_code_files(root, (partition_key,), codes)
            _write_target_by_date_files(root, (partition_key,), codes)
            p3_report = root / "p3_report.json"
            _write_p3_report(root, p3_report, (partition_key,), rows=1)
            instance = _instance_with_partitions((partition_key,), codes)
            instance.report_runless_asset_event(
                dg.AssetMaterialization(
                    asset_key=RAW_INDEX_DAILY_ASSET_KEY,
                    partition=partition_key,
                )
            )

            dry_run = report_raw_index_daily_recent_window_events(
                instance=instance,
                lake_root=root,
                duckdb=DuckDBResource(),
                p3_final_audit_report_path=p3_report,
                partition_keys=(partition_key,),
                dry_run=True,
            )
            with self.assertRaisesRegex(ValueError, "non-ready"):
                report_raw_index_daily_recent_window_events(
                    instance=instance,
                    lake_root=root,
                    duckdb=DuckDBResource(),
                    p3_final_audit_report_path=p3_report,
                    partition_keys=(partition_key,),
                    dry_run=False,
                )

        self.assertTrue(dry_run.should_stop)
        self.assertEqual(dry_run.blocked_existing_partition_keys, (partition_key,))


if __name__ == "__main__":
    unittest.main()
