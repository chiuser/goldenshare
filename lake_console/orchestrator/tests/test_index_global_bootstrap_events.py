from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import dagster as dg
import duckdb
import pytest

from orchestrator.defs.bootstrap import index_global_bootstrap_events as events
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
        return {
            trade_date
            for (asset_name, trade_date) in self.materializations
            if asset_name == asset_key.to_user_string()
        }

    def fetch_materializations(self, record_filter, limit: int = 1):
        asset_name = record_filter.asset_key.to_user_string()
        wanted = set(record_filter.asset_partitions or ())
        records = [
            value
            for (candidate_asset, trade_date), value in self.materializations.items()
            if candidate_asset == asset_name and (not wanted or trade_date in wanted)
        ]
        return SimpleNamespace(records=records[:limit])

    def report_runless_asset_event(self, event: object) -> None:
        self.events.append(event)
        if isinstance(event, dg.AssetMaterialization):
            self.materializations[(event.asset_key.to_user_string(), event.partition)] = SimpleNamespace(
                storage_id=len(self.materializations) + 1,
                run_id="runless",
                timestamp=float(len(self.materializations) + 1),
            )


def _write_report(path: Path, dates: tuple[str, ...]) -> None:
    path.write_text(
        __import__("json").dumps(
            {
                "should_stop": False,
                "date_plan": {
                    "start_date": dates[0],
                    "end_date": dates[-1],
                    "expected_natural_dates": list(dates),
                    "fingerprint": events._date_plan_fingerprint(dates),
                },
                "raw_audit": {
                    "expected_file_count": len(dates),
                    "missing_count": 0,
                    "invalid_existing_count": 0,
                    "valid_existing_count": len(dates),
                },
                "silver_audit": {
                    "expected_file_count": len(dates),
                    "missing_count": 0,
                    "invalid_existing_count": 0,
                    "valid_existing_count": len(dates),
                },
            }
        ),
        encoding="utf-8",
    )


def _write_target(path: Path, *, raw: bool, trade_date: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = (
        "ts_code VARCHAR, trade_date VARCHAR, open DOUBLE, close DOUBLE, high DOUBLE, "
        "low DOUBLE, pre_close DOUBLE, change DOUBLE, pct_chg DOUBLE, swing DOUBLE, "
        "vol DOUBLE, amount DOUBLE"
        if raw
        else "ts_code VARCHAR, trade_date DATE, open DOUBLE, high DOUBLE, low DOUBLE, "
        "close DOUBLE, pre_close DOUBLE, change_amount DOUBLE, pct_chg DOUBLE, swing DOUBLE, "
        "vol DOUBLE, amount DOUBLE"
    )
    with duckdb.connect(":memory:") as connection:
        connection.execute(f"CREATE TABLE source ({fields})")
        connection.execute(
            "INSERT INTO source VALUES (" + ("'XIN9', ?, '1', '1', '1', '1', '1', '0', '0', '0', '0', '0'" if raw else "'XIN9', CAST(? AS DATE), 1, 1, 1, 1, 1, 0, 0, 0, 0, 0") + ")",
            [trade_date.replace("-", "") if raw else trade_date],
        )
        connection.execute("COPY source TO ? (FORMAT PARQUET)", [str(path)])


def test_partition_registration_is_explicit_and_idempotent(monkeypatch, tmp_path: Path) -> None:
    dates = ("2022-01-01", "2022-01-02")
    report_path = tmp_path / "report.json"
    _write_report(report_path, dates)
    for date in dates:
        _write_target(tmp_path / "raw" / f"trade_date={date}" / "part-000.parquet", raw=True, trade_date=date)
        _write_target(tmp_path / "silver" / f"trade_date={date}" / "part-000.parquet", raw=False, trade_date=date)
    instance = _Instance(())
    monkeypatch.setattr(events, "INDEX_GLOBAL_EXPECTED_PARTITION_COUNT", 2)
    monkeypatch.setattr(events, "INDEX_GLOBAL_DATE_PLAN_FINGERPRINT", events._date_plan_fingerprint(dates))
    monkeypatch.setattr(events, "raw_index_global_path", lambda root, date: root / "raw" / f"trade_date={date}" / "part-000.parquet")
    monkeypatch.setattr(events, "silver_index_global_path", lambda root, date: root / "silver" / f"trade_date={date}" / "part-000.parquet")
    monkeypatch.setattr(events, "asset_readiness_status", lambda *_args, **_kwargs: SimpleNamespace(ready=False))
    result = events.register_index_global_partitions(
        instance=instance,
        lake_root=tmp_path,
        reconciliation_report_path=report_path,
        duckdb_resource=_MemoryDuckDB(),
        confirm_partition_write=True,
    )
    assert result.registered_partition_count == 2
    assert set(instance.get_dynamic_partitions(events.INDEX_GLOBAL_PARTITION_SET)) == set(dates)


def test_event_plan_is_read_only_and_recent_checks_are_bounded(monkeypatch, tmp_path: Path) -> None:
    dates = tuple(f"2022-01-{index:02d}" for index in range(1, 23))
    report_path = tmp_path / "report.json"
    _write_report(report_path, dates)
    for date in dates:
        _write_target(tmp_path / "raw" / f"trade_date={date}" / "part-000.parquet", raw=True, trade_date=date)
        _write_target(tmp_path / "silver" / f"trade_date={date}" / "part-000.parquet", raw=False, trade_date=date)
    monkeypatch.setattr(events, "INDEX_GLOBAL_EXPECTED_PARTITION_COUNT", len(dates))
    monkeypatch.setattr(events, "INDEX_GLOBAL_DATE_PLAN_FINGERPRINT", events._date_plan_fingerprint(dates))
    monkeypatch.setattr(events, "raw_index_global_path", lambda root, date: root / "raw" / f"trade_date={date}" / "part-000.parquet")
    monkeypatch.setattr(events, "silver_index_global_path", lambda root, date: root / "silver" / f"trade_date={date}" / "part-000.parquet")
    monkeypatch.setattr(events, "asset_readiness_status", lambda *_args, **_kwargs: SimpleNamespace(ready=False))
    instance = _Instance(dates)
    plan = events.plan_index_global_bootstrap_events(
        instance=instance,
        lake_root=tmp_path,
        reconciliation_report_path=report_path,
        duckdb_resource=_MemoryDuckDB(),
    )
    assert plan.should_stop is False
    assert plan.planned_raw_materialization_count == len(dates)
    assert plan.planned_silver_materialization_count == len(dates)
    assert plan.planned_raw_check_count == 20
    assert plan.planned_silver_check_count == 20
    assert instance.events == []


def test_apply_requires_explicit_confirmation() -> None:
    with pytest.raises(ValueError, match="confirm-event-write"):
        events.report_index_global_events(
            instance=object(),
            lake_root=Path("/tmp/no-lake"),
            reconciliation_report_path=Path("/tmp/no-report"),
            duckdb_resource=_MemoryDuckDB(),
            dry_run=False,
            confirm_event_write=False,
        )
