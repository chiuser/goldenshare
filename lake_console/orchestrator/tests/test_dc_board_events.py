import json
from pathlib import Path
from types import SimpleNamespace

import dagster as dg
import duckdb
import pytest

from orchestrator.defs.bootstrap.dc_board_events import (
    plan_dc_board_events,
    report_dc_board_events,
)
from orchestrator.defs.paths import (
    raw_dc_daily_path,
    raw_dc_index_path,
    raw_dc_member_path,
    silver_dc_daily_path,
    silver_dc_index_path,
    silver_dc_member_path,
)
from orchestrator.defs.resources import DuckDBResource


DATES = ("2026-07-13", "2026-07-14")
FINGERPRINTS = {
    "dc_index": "index-fingerprint",
    "dc_member": "member-fingerprint",
    "dc_daily": "daily-fingerprint",
}


class FakeEventInstance:
    def __init__(self) -> None:
        self.events: list[object] = []
        self._records: dict[tuple[str, str], SimpleNamespace] = {}

    def get_dynamic_partitions(self, name: str) -> list[str]:
        assert name == "cn_a_index_trade_days"
        return list(DATES)

    def get_materialized_partitions(self, asset_key: dg.AssetKey) -> set[str]:
        label = asset_key.to_user_string()
        return {
            partition
            for (asset_label, partition) in self._records
            if asset_label == label
        }

    def fetch_materializations(self, record_filter, limit: int = 1):
        asset_label = record_filter.asset_key.to_user_string()
        partitions = set(record_filter.asset_partitions or ())
        records = [
            record
            for (record_asset, partition), record in self._records.items()
            if record_asset == asset_label and (not partitions or partition in partitions)
        ]
        records.sort(key=lambda record: record.timestamp, reverse=True)
        return SimpleNamespace(records=records[:limit])

    def report_runless_asset_event(self, event) -> None:
        self.events.append(event)
        if isinstance(event, dg.AssetMaterialization):
            key = (event.asset_key.to_user_string(), event.partition)
            self._records[key] = SimpleNamespace(
                storage_id=1000 + len(self._records),
                run_id="runless",
                timestamp=float(len(self._records) + 1),
            )


def _write_fixture_lake(root: Path) -> None:
    for trade_date in DATES:
        paths = {
            "raw_index": raw_dc_index_path(root, trade_date),
            "raw_member": raw_dc_member_path(root, trade_date),
            "raw_daily": raw_dc_daily_path(root, trade_date),
            "silver_index": silver_dc_index_path(root, trade_date),
            "silver_member": silver_dc_member_path(root, trade_date),
            "silver_daily": silver_dc_daily_path(root, trade_date),
        }
        for path in paths.values():
            path.parent.mkdir(parents=True, exist_ok=True)
        date_literal = f"DATE '{trade_date}'"
        raw_date_literal = f"'{trade_date.replace('-', '')}'"
        with duckdb.connect(database=":memory:") as connection:
            connection.execute(
                f"""
                COPY (
                    SELECT 'BK0001.DC'::VARCHAR AS ts_code,
                           {raw_date_literal}::VARCHAR AS trade_date,
                           '行业板块'::VARCHAR AS name,
                           NULL::VARCHAR AS leading,
                           '000001.SZ'::VARCHAR AS leading_code,
                           1.0::DOUBLE AS pct_change,
                           1.0::DOUBLE AS leading_pct,
                           100.0::DOUBLE AS total_mv,
                           1.0::DOUBLE AS turnover_rate,
                           1::INTEGER AS up_num,
                           1::INTEGER AS down_num,
                           '行业板块'::VARCHAR AS idx_type,
                           NULL::VARCHAR AS level
                ) TO '{paths['raw_index']}' (FORMAT PARQUET)
                """
            )
            connection.execute(
                f"""
                COPY (
                    SELECT {raw_date_literal}::VARCHAR AS trade_date,
                           'BK0001.DC'::VARCHAR AS ts_code,
                           '000001.SZ'::VARCHAR AS con_code,
                           '示例股票'::VARCHAR AS name
                ) TO '{paths['raw_member']}' (FORMAT PARQUET)
                """
            )
            connection.execute(
                f"""
                COPY (
                    SELECT 'BK0001.DC'::VARCHAR AS ts_code,
                           {raw_date_literal}::VARCHAR AS trade_date,
                           10.0::DOUBLE AS close,
                           9.0::DOUBLE AS open,
                           10.0::DOUBLE AS high,
                           9.0::DOUBLE AS low,
                           1.0::DOUBLE AS change,
                           1.0::DOUBLE AS pct_change,
                           100.0::DOUBLE AS vol,
                           1000.0::DOUBLE AS amount,
                           1.0::DOUBLE AS swing,
                           1.0::DOUBLE AS turnover_rate,
                           '行业板块'::VARCHAR AS category
                ) TO '{paths['raw_daily']}' (FORMAT PARQUET)
                """
            )
            connection.execute(
                f"""
                COPY (
                    SELECT 'BK0001.DC'::VARCHAR AS ts_code,
                           {date_literal} AS trade_date,
                           '行业板块'::VARCHAR AS name,
                           NULL::VARCHAR AS leading,
                           '000001.SZ'::VARCHAR AS leading_code,
                           1.0::DOUBLE AS pct_change,
                           1.0::DOUBLE AS leading_pct,
                           100.0::DOUBLE AS total_mv,
                           1.0::DOUBLE AS turnover_rate,
                           1::INTEGER AS up_num,
                           1::INTEGER AS down_num,
                           '行业板块'::VARCHAR AS idx_type,
                           NULL::VARCHAR AS level
                ) TO '{paths['silver_index']}' (FORMAT PARQUET)
                """
            )
            connection.execute(
                f"""
                COPY (
                    SELECT {date_literal} AS trade_date,
                           'BK0001.DC'::VARCHAR AS ts_code,
                           '000001.SZ'::VARCHAR AS con_code,
                           '示例股票'::VARCHAR AS name
                ) TO '{paths['silver_member']}' (FORMAT PARQUET)
                """
            )
            connection.execute(
                f"""
                COPY (
                    SELECT 'BK0001.DC'::VARCHAR AS ts_code,
                           {date_literal} AS trade_date,
                           10.0::DOUBLE AS close,
                           9.0::DOUBLE AS open,
                           10.0::DOUBLE AS high,
                           9.0::DOUBLE AS low,
                           1.0::DOUBLE AS change,
                           1.0::DOUBLE AS pct_change,
                           100.0::DOUBLE AS vol,
                           1000.0::DOUBLE AS amount,
                           1.0::DOUBLE AS swing,
                           1.0::DOUBLE AS turnover_rate,
                           '行业板块'::VARCHAR AS category
                ) TO '{paths['silver_daily']}' (FORMAT PARQUET)
                """
            )


def _write_reports(root: Path) -> tuple[Path, Path, Path, Path]:
    baseline = root / "baseline.json"
    raw_audit = root / "raw.json"
    silver_audit = root / "silver.json"
    final = root / "final.json"
    date_plans = [
        {
            "dataset": dataset,
            "expected_trade_dates": list(DATES),
            "fingerprint": fingerprint,
        }
        for dataset, fingerprint in FINGERPRINTS.items()
    ]
    baseline.write_text(json.dumps({"should_stop": False, "date_plans": date_plans}))
    for path in (raw_audit, silver_audit):
        path.write_text(
            json.dumps({"should_stop": False, "date_plan_fingerprints": FINGERPRINTS})
        )
    final.write_text(
        json.dumps(
            {
                "should_stop": False,
                "raw": {"date_plan_fingerprints": FINGERPRINTS},
                "silver": {"date_plan_fingerprints": FINGERPRINTS},
            }
        )
    )
    return baseline, raw_audit, silver_audit, final


def test_m8_dry_run_plans_full_materialization_and_recent_checks(tmp_path: Path) -> None:
    _write_fixture_lake(tmp_path)
    reports = _write_reports(tmp_path)
    instance = FakeEventInstance()

    report = report_dc_board_events(
        instance=instance,
        lake_root=tmp_path,
        duckdb_resource=DuckDBResource(),
        baseline_report_path=reports[0],
        raw_audit_report_path=reports[1],
        silver_audit_report_path=reports[2],
        final_reconciliation_report_path=reports[3],
        dry_run=True,
    )

    assert report.plan.should_stop is False
    assert report.plan.planned_materialization_count == 12
    assert report.plan.planned_check_count == 12
    assert report.plan.planned_event_count == 24
    assert instance.events == []


def test_m8_apply_requires_confirmation_and_reports_partitioned_events(tmp_path: Path) -> None:
    _write_fixture_lake(tmp_path)
    reports = _write_reports(tmp_path)
    instance = FakeEventInstance()

    with pytest.raises(ValueError, match="confirm-event-write"):
        report_dc_board_events(
            instance=instance,
            lake_root=tmp_path,
            duckdb_resource=DuckDBResource(),
            baseline_report_path=reports[0],
            raw_audit_report_path=reports[1],
            silver_audit_report_path=reports[2],
            final_reconciliation_report_path=reports[3],
            dry_run=False,
        )

    report = report_dc_board_events(
        instance=instance,
        lake_root=tmp_path,
        duckdb_resource=DuckDBResource(),
        baseline_report_path=reports[0],
        raw_audit_report_path=reports[1],
        silver_audit_report_path=reports[2],
        final_reconciliation_report_path=reports[3],
        dry_run=False,
        confirm_event_write=True,
    )

    assert report.reported_materialization_count == 12
    assert report.reported_check_count == 12
    assert report.reported_event_count == 24
    materializations = [
        event for event in instance.events if isinstance(event, dg.AssetMaterialization)
    ]
    checks = [
        event for event in instance.events if isinstance(event, dg.AssetCheckEvaluation)
    ]
    assert len(materializations) == 12
    assert len(checks) == 12
    assert all(event.partition in DATES for event in materializations)
    assert all(event.partition in DATES for event in checks)
    assert all(event.target_materialization_data is not None for event in checks)
    assert all(event.blocking is True and event.passed is True for event in checks)


def test_m8_stops_when_audit_is_not_green(tmp_path: Path) -> None:
    _write_fixture_lake(tmp_path)
    reports = list(_write_reports(tmp_path))
    reports[2].write_text(json.dumps({"should_stop": True}))
    instance = FakeEventInstance()

    with pytest.raises(ValueError, match="not green"):
        plan_dc_board_events(
            instance=instance,
            lake_root=tmp_path,
            duckdb_resource=DuckDBResource(),
            baseline_report_path=reports[0],
            raw_audit_report_path=reports[1],
            silver_audit_report_path=reports[2],
            final_reconciliation_report_path=reports[3],
        )
    assert instance.events == []
