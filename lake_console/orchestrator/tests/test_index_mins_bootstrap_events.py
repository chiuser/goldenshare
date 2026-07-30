from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
from types import SimpleNamespace

import dagster as dg
import duckdb
import pytest

from orchestrator.defs.bootstrap import index_mins_bootstrap_events as events
from orchestrator.defs.resources import DuckDBResource


class _MemoryDuckDB(DuckDBResource):
    @contextmanager
    def connect(self):
        connection = duckdb.connect(":memory:")
        try:
            yield connection
        finally:
            connection.close()


class _Instance:
    def __init__(self, dates: tuple[str, ...]) -> None:
        self.dates = list(dates)
        self.events: list[object] = []
        self.materializations: dict[tuple[str, str], SimpleNamespace] = {}

    def get_dynamic_partitions(self, _name: str) -> list[str]:
        return list(self.dates)

    def add_dynamic_partitions(self, _name: str, keys: list[str]) -> None:
        self.dates.extend(key for key in keys if key not in self.dates)

    def get_materialized_partitions(self, asset_key: dg.AssetKey) -> set[str]:
        asset = asset_key.to_user_string()
        return {
            partition
            for (candidate_asset, partition) in self.materializations
            if candidate_asset == asset
        }

    def fetch_materializations(self, record_filter, limit: int = 1):
        asset = record_filter.asset_key.to_user_string()
        partitions = set(record_filter.asset_partitions or ())
        records = [
            record
            for (candidate_asset, partition), record in self.materializations.items()
            if candidate_asset == asset and (not partitions or partition in partitions)
        ]
        return SimpleNamespace(records=records[-limit:])

    def report_runless_asset_event(self, event: object) -> None:
        self.events.append(event)
        if isinstance(event, dg.AssetMaterialization):
            asset = event.asset_key.to_user_string()
            self.materializations[(asset, event.partition)] = SimpleNamespace(
                storage_id=len(self.materializations) + 1,
                run_id="runless",
                timestamp=float(len(self.materializations) + 1),
            )


def _write_file(path: Path, row_count: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        connection.execute("CREATE TABLE source (value INTEGER)")
        connection.executemany("INSERT INTO source VALUES (?)", [(index,) for index in range(row_count)])
        connection.execute("COPY source TO ? (FORMAT PARQUET)", [str(path)])


def _write_report(path: Path, dates: tuple[str, ...]) -> None:
    raw_records: list[dict[str, object]] = []
    for trade_date in dates:
        for source_freq in events.INDEX_MINS_RAW_FREQS:
            raw_records.append(
                {
                    "partition_key": trade_date,
                    "source_freq": source_freq,
                    "write_mode": "staged_atomic_replace",
                    "written_row_count": 1,
                }
            )
    raw_records[0]["write_mode"] = "source_empty_exempt"
    silver_records = [
        {
            "partition_key": trade_date,
            "silver_freq": f"{frequency}min",
            "written_row_count": 1,
        }
        for trade_date in dates
        for frequency in events.INDEX_MINS_SILVER_FREQS
    ]
    path.write_text(
        json.dumps(
            {
                "should_stop": False,
                "date_plan": {
                    "start_date": dates[0],
                    "end_date": dates[-1],
                    "expected_trade_dates": list(dates),
                    "expected_date_count": len(dates),
                    "fingerprint": "fixture-fingerprint",
                },
                "raw_records": raw_records,
                "silver_records": silver_records,
                "raw_audit": {"missing_count": 0, "invalid_existing_count": 0},
                "silver_audit": {"missing_count": 0, "invalid_existing_count": 0},
            }
        ),
        encoding="utf-8",
    )


def _patch_fixture(monkeypatch, tmp_path: Path, dates: tuple[str, ...]) -> Path:
    report_path = tmp_path / "p7.json"
    _write_report(report_path, dates)
    monkeypatch.setattr(
        events,
        "raw_index_mins_path",
        lambda root, frequency, trade_date: root / "raw" / frequency / f"trade_date={trade_date}.parquet",
    )
    monkeypatch.setattr(
        events,
        "silver_index_mins_path",
        lambda root, frequency, trade_date: root / "silver" / str(frequency) / f"trade_date={trade_date}.parquet",
    )
    for trade_date in dates:
        for source_freq in events.INDEX_MINS_RAW_FREQS:
            if (trade_date, source_freq) == (dates[0], events.INDEX_MINS_RAW_FREQS[0]):
                continue
            _write_file(events.raw_index_mins_path(tmp_path, source_freq, trade_date))
        for frequency in events.INDEX_MINS_SILVER_FREQS:
            _write_file(events.silver_index_mins_path(tmp_path, frequency, trade_date))
    monkeypatch.setattr(events, "asset_readiness_status", lambda *_args, **_kwargs: SimpleNamespace(ready=False))
    return report_path


def test_plan_is_read_only_and_excludes_source_empty_raw(monkeypatch, tmp_path: Path) -> None:
    dates = ("2025-01-02", "2025-01-03")
    report_path = _patch_fixture(monkeypatch, tmp_path, dates)
    instance = _Instance(dates)
    plan = events.plan_index_mins_bootstrap_events(
        instance=instance,
        lake_root=tmp_path,
        reconciliation_report_path=report_path,
        duckdb_resource=_MemoryDuckDB(),
        require_registered=False,
    )

    assert plan.should_stop is False
    assert plan.source_empty_raw_count == 1
    assert len(plan.files) == 9 + 14
    assert plan.planned_materialization_count == 23
    assert plan.planned_check_count == 23
    assert instance.events == []


def test_apply_requires_confirmation(monkeypatch, tmp_path: Path) -> None:
    dates = ("2025-01-02", "2025-01-03")
    report_path = _patch_fixture(monkeypatch, tmp_path, dates)
    with pytest.raises(ValueError, match="confirm-event-write"):
        events.report_index_mins_events(
            instance=_Instance(dates),
            lake_root=tmp_path,
            reconciliation_report_path=report_path,
            duckdb_resource=_MemoryDuckDB(),
            dry_run=False,
            confirm_event_write=False,
        )


def test_apply_writes_partitioned_events_for_all_verified_files(monkeypatch, tmp_path: Path) -> None:
    dates = ("2025-01-02", "2025-01-03")
    report_path = _patch_fixture(monkeypatch, tmp_path, dates)
    instance = _Instance(dates)
    report = events.report_index_mins_events(
        instance=instance,
        lake_root=tmp_path,
        reconciliation_report_path=report_path,
        duckdb_resource=_MemoryDuckDB(),
        dry_run=False,
        confirm_event_write=True,
    )

    assert report.reported_materialization_count == 23
    assert report.reported_check_count == 23
    assert report.reported_materialization_count + report.reported_check_count == 46
    materializations = [event for event in instance.events if isinstance(event, dg.AssetMaterialization)]
    checks = [event for event in instance.events if isinstance(event, dg.AssetCheckEvaluation)]
    assert all(event.partition in dates for event in materializations + checks)
    assert all(event.partition is not None for event in materializations + checks)
    assert not any(
        event.asset_key.to_user_string() == "raw_index_mins_1m"
        and event.partition == dates[0]
        for event in materializations
    )
    assert {event.check_name for event in checks} == {
        *events.RAW_INDEX_MINS_CHECK_NAMES.values(),
        *events.SILVER_INDEX_MINS_CHECK_NAMES.values(),
    }
