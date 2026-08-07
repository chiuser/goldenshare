from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
from types import SimpleNamespace

import dagster as dg
import pytest

from orchestrator.defs.bootstrap import major_index_mins_bootstrap_events as events


class _DuckDB:
    @contextmanager
    def connect(self):
        yield object()


class _Instance:
    def __init__(self) -> None:
        self.dynamic_partitions: list[str] = []
        self.events: list[object] = []
        self.materializations: dict[tuple[str, str], SimpleNamespace] = {}
        self.check_records: dict[tuple[str, str], list[SimpleNamespace]] = {}
        self.event_log_storage = self

    def get_runs(self, *, filters, limit: int):
        del filters, limit
        return []

    def get_dynamic_partitions(self, name: str) -> list[str]:
        assert name == events.MAJOR_INDEX_MINS_PARTITION_SET
        return list(self.dynamic_partitions)

    def add_dynamic_partitions(self, name: str, keys: list[str]) -> None:
        assert name == events.MAJOR_INDEX_MINS_PARTITION_SET
        self.dynamic_partitions.extend(
            value for value in keys if value not in self.dynamic_partitions
        )

    def get_materialized_partitions(self, asset_key: dg.AssetKey) -> set[str]:
        label = asset_key.to_user_string()
        return {
            partition
            for (asset, partition), _record in self.materializations.items()
            if asset == label
        }

    def fetch_materializations(self, record_filter, limit: int = 1):
        asset = record_filter.asset_key.to_user_string()
        partitions = set(record_filter.asset_partitions or ())
        records = [
            record
            for (candidate_asset, partition), record in self.materializations.items()
            if candidate_asset == asset and (not partitions or partition in partitions)
        ]
        records.sort(key=lambda value: value.storage_id, reverse=True)
        return SimpleNamespace(records=records[:limit])

    def get_asset_check_execution_history(self, check_key, limit: int):
        key = (check_key.asset_key.to_user_string(), check_key.name)
        return list(reversed(self.check_records.get(key, ())))[:limit]

    def report_runless_asset_event(self, event: object) -> None:
        self.events.append(event)
        if isinstance(event, dg.AssetMaterialization):
            asset = event.asset_key.to_user_string()
            storage_id = len(self.events)
            self.materializations[(asset, str(event.partition))] = SimpleNamespace(
                storage_id=storage_id,
                run_id="runless",
                timestamp=float(storage_id),
                partition_key=str(event.partition),
            )
            return
        if isinstance(event, dg.AssetCheckEvaluation):
            key = (event.asset_key.to_user_string(), event.check_name)
            self.check_records.setdefault(key, []).append(
                SimpleNamespace(
                    partition=event.partition,
                    status=SimpleNamespace(value="SUCCEEDED"),
                    event=SimpleNamespace(
                        dagster_event=SimpleNamespace(event_specific_data=event)
                    ),
                )
            )


def _fixture(
    monkeypatch,
    tmp_path: Path,
    dates: tuple[str, ...],
) -> tuple[Path, Path, Path]:
    date_plan = events.MajorIndexMinsDatePlan(
        start_date=dates[0],
        end_date=dates[-1],
        expected_trade_dates=dates,
        fingerprint="frozen-date-plan",
    )
    monkeypatch.setattr(events, "build_date_plan", lambda **_kwargs: date_plan)
    monkeypatch.setattr(
        events,
        "_parquet_row_counts",
        lambda _connection, paths: {
            str(value.resolve()): 1 for value in paths
        },
    )
    date_report = tmp_path / "date-plan.json"
    date_report.write_text(
        json.dumps(
            {
                "date_plan": {
                    "start_date": dates[0],
                    "end_date": dates[-1],
                    "expected_date_count": len(dates),
                    "fingerprint": date_plan.fingerprint,
                }
            }
        ),
        encoding="utf-8",
    )
    for spec in events._asset_specs():
        for trade_date in dates:
            path = spec.path_builder(tmp_path, spec.frequency, trade_date)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"verified-parquet-fixture")
    promote_report = tmp_path / "promote.json"
    promote_report.write_text(
        json.dumps(
            {
                "should_stop": False,
                "formal_lake_root": str(tmp_path),
                "date_plan_fingerprint": date_plan.fingerprint,
                "post_raw_valid_count": len(dates)
                * len(events.MAJOR_INDEX_MINS_SOURCE_FREQS),
                "post_silver_valid_count": len(dates)
                * len(events.MAJOR_INDEX_MINS_SILVER_FREQS),
                "post_raw_row_count": len(dates)
                * len(events.MAJOR_INDEX_MINS_SOURCE_FREQS),
                "post_silver_row_count": len(dates)
                * len(events.MAJOR_INDEX_MINS_SILVER_FREQS),
                "failure_samples": [],
                "stop_reason_codes": [],
            }
        ),
        encoding="utf-8",
    )
    fallback_report = tmp_path / "fallback.json"
    fallback_report.write_text(
        json.dumps(
            {
                "should_stop": False,
                "failure_samples": [],
                "stop_reason_codes": [],
                "results": [],
                "written_count": 0,
                "reused_count": 0,
            }
        ),
        encoding="utf-8",
    )
    return date_report, promote_report, fallback_report


def _plan(
    *,
    instance: _Instance,
    tmp_path: Path,
    date_report: Path,
    promote_report: Path,
    fallback_report: Path,
    require_registered: bool,
):
    return events.plan_major_index_mins_bootstrap_events(
        instance=instance,
        lake_root=tmp_path,
        date_plan_report_path=date_report,
        promote_report_path=promote_report,
        fallback_report_path=fallback_report,
        duckdb_resource=_DuckDB(),
        require_registered=require_registered,
    )


def test_dry_run_is_read_only_and_requires_registered_partitions(
    monkeypatch,
    tmp_path: Path,
) -> None:
    dates = ("2026-01-02", "2026-01-05", "2026-01-06")
    date_report, promote_report, fallback_report = _fixture(monkeypatch, tmp_path, dates)
    instance = _Instance()

    plan = _plan(
        instance=instance,
        tmp_path=tmp_path,
        date_report=date_report,
        promote_report=promote_report,
        fallback_report=fallback_report,
        require_registered=True,
    )

    assert plan.should_stop is True
    assert plan.missing_registered_dates == dates
    assert plan.inventory_file_count == len(dates) * 12
    assert plan.inventory_row_count == len(dates) * 12
    assert plan.planned_materialization_count == len(dates) * 12
    assert plan.planned_check_count == len(dates) * 12
    assert instance.events == []


def test_register_sample_apply_and_post_audit_are_idempotent(
    monkeypatch,
    tmp_path: Path,
) -> None:
    dates = tuple(f"2026-01-{day:02d}" for day in range(1, 22))
    date_report, promote_report, fallback_report = _fixture(monkeypatch, tmp_path, dates)
    instance = _Instance()

    register_report = events.register_major_index_mins_partitions(
        instance=instance,
        lake_root=tmp_path,
        date_plan_report_path=date_report,
        promote_report_path=promote_report,
        fallback_report_path=fallback_report,
        duckdb_resource=_DuckDB(),
        confirm_partition_write=True,
    )
    assert register_report.registered_partition_count == len(dates)
    assert register_report.plan.should_stop is False
    assert register_report.plan.missing_registered_dates == ()

    sample = events.report_major_index_mins_events(
        instance=instance,
        lake_root=tmp_path,
        date_plan_report_path=date_report,
        promote_report_path=promote_report,
        fallback_report_path=fallback_report,
        duckdb_resource=_DuckDB(),
        dry_run=False,
        confirm_event_write=True,
        sample_only=True,
    )
    assert sample.selected_partition_keys == (dates[-1],)
    assert sample.reported_materialization_count == 12
    assert sample.reported_check_count == 12

    apply_report = events.report_major_index_mins_events(
        instance=instance,
        lake_root=tmp_path,
        date_plan_report_path=date_report,
        promote_report_path=promote_report,
        fallback_report_path=fallback_report,
        duckdb_resource=_DuckDB(),
        dry_run=False,
        confirm_event_write=True,
    )
    assert apply_report.reported_materialization_count == len(dates) * 12 - 12
    assert apply_report.reported_check_count == 20 * 12 - 12

    post = _plan(
        instance=instance,
        tmp_path=tmp_path,
        date_report=date_report,
        promote_report=promote_report,
        fallback_report=fallback_report,
        require_registered=True,
    )
    assert post.should_stop is False
    assert post.planned_materialization_count == 0
    assert post.planned_check_count == 0, {
        value.spec.asset_key.to_user_string(): sorted(
            set(dates[-20:]) - set(value.existing_ready_check_dates)
        )
        for value in post.asset_plans
    }
    check_events = [
        value for value in instance.events if isinstance(value, dg.AssetCheckEvaluation)
    ]
    assert {value.partition for value in check_events} == set(dates[-20:])
    assert all(value.partition is not None for value in instance.events)


def test_report_change_gate_blocks_modified_formal_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    dates = ("2026-01-02",)
    date_report, promote_report, fallback_report = _fixture(monkeypatch, tmp_path, dates)
    spec = events._asset_specs()[0]
    changed = spec.path_builder(tmp_path, spec.frequency, dates[0])
    report_mtime = promote_report.stat().st_mtime
    os.utime(changed, (report_mtime + 10, report_mtime + 10))
    instance = _Instance()
    instance.dynamic_partitions.extend(dates)

    plan = _plan(
        instance=instance,
        tmp_path=tmp_path,
        date_report=date_report,
        promote_report=promote_report,
        fallback_report=fallback_report,
        require_registered=True,
    )

    assert plan.should_stop is True
    assert any("changed after P7E" in value for value in plan.precondition_errors)


def test_only_audited_historical_raw_empty_files_are_allowed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    dates = tuple(f"2026-01-{day:02d}" for day in range(1, 22))
    date_report, promote_report, fallback_report = _fixture(
        monkeypatch,
        tmp_path,
        dates,
    )
    raw_spec = events._asset_specs()[0]
    empty_path = raw_spec.path_builder(tmp_path, raw_spec.frequency, dates[0])
    monkeypatch.setattr(
        events,
        "_parquet_row_counts",
        lambda _connection, paths: {
            str(value.resolve()): 0 if value == empty_path else 1
            for value in paths
        },
    )
    fallback_report.write_text(
        json.dumps(
            {
                "should_stop": False,
                "failure_samples": [],
                "stop_reason_codes": [],
                "results": [
                    {
                        "trade_date": dates[0],
                        "target_freq": raw_spec.frequency,
                        "source_mode": "derived_fallback",
                        "reason_code": f"native_{raw_spec.frequency}_source_empty",
                    }
                ],
                "written_count": 1,
                "reused_count": 0,
            }
        ),
        encoding="utf-8",
    )
    promote = json.loads(promote_report.read_text(encoding="utf-8"))
    promote["post_raw_row_count"] -= 1
    promote_report.write_text(json.dumps(promote), encoding="utf-8")
    instance = _Instance()
    instance.dynamic_partitions.extend(dates)

    plan = _plan(
        instance=instance,
        tmp_path=tmp_path,
        date_report=date_report,
        promote_report=promote_report,
        fallback_report=fallback_report,
        require_registered=True,
    )

    assert plan.should_stop is False
    assert plan.source_empty_raw_keys == (f"{dates[0]}:{raw_spec.frequency}",)
    assert plan.inventory_row_count == len(dates) * 12 - 1


def test_writes_require_explicit_confirmation(monkeypatch, tmp_path: Path) -> None:
    dates = ("2026-01-02",)
    date_report, promote_report, fallback_report = _fixture(monkeypatch, tmp_path, dates)
    instance = _Instance()

    with pytest.raises(ValueError, match="confirm-partition-write"):
        events.register_major_index_mins_partitions(
            instance=instance,
            lake_root=tmp_path,
            date_plan_report_path=date_report,
            promote_report_path=promote_report,
            fallback_report_path=fallback_report,
            duckdb_resource=_DuckDB(),
            confirm_partition_write=False,
        )
    with pytest.raises(ValueError, match="confirm-event-write"):
        events.report_major_index_mins_events(
            instance=instance,
            lake_root=tmp_path,
            date_plan_report_path=date_report,
            promote_report_path=promote_report,
            fallback_report_path=fallback_report,
            duckdb_resource=_DuckDB(),
            dry_run=False,
            confirm_event_write=False,
        )
