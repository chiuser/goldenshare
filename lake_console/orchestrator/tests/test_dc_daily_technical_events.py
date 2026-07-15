from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import dagster as dg

from orchestrator.defs.asset_guards.dc_daily_technical_quality import (
    GOLD_DC_DAILY_TECHNICAL_CHECK_NAME,
    GoldDcDailyTechnicalAudit,
)
from orchestrator.defs.bootstrap import dc_daily_technical_events as events


DATES = tuple(f"trade-{index:03d}" for index in range(611))


class _DuckDBResource:
    @contextmanager
    def connect(self):
        yield object()


class _Instance:
    def __init__(self) -> None:
        self.events: list[object] = []
        self.materializations: dict[str, SimpleNamespace] = {}
        self.event_log_storage = SimpleNamespace()

    def get_dynamic_partitions(self, _name: str) -> list[str]:
        return list(DATES)

    def get_materialized_partitions(self, _asset_key: dg.AssetKey) -> set[str]:
        return set(self.materializations)

    def fetch_materializations(self, record_filter, limit: int = 1):
        partitions = set(record_filter.asset_partitions or ())
        records = [
            record
            for partition, record in self.materializations.items()
            if not partitions or partition in partitions
        ]
        return SimpleNamespace(records=records[:limit])

    def report_runless_asset_event(self, event: object) -> None:
        self.events.append(event)
        if isinstance(event, dg.AssetMaterialization):
            self.materializations[event.partition] = SimpleNamespace(
                storage_id=len(self.materializations) + 1,
                run_id="",
                timestamp=float(len(self.materializations) + 1),
            )


def _audits() -> dict[str, GoldDcDailyTechnicalAudit]:
    return {
        trade_date: GoldDcDailyTechnicalAudit(
            trade_date=trade_date,
            passed=True,
            materialized=True,
            checked_row_count=10,
            failed_row_count=0,
        )
        for trade_date in DATES
    }


def _create_gold_targets(tmp_path: Path) -> None:
    for trade_date in DATES:
        target = tmp_path / "gold" / trade_date / "part-000.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()


def _patch_common_fixtures(monkeypatch, tmp_path: Path) -> None:
    _create_gold_targets(tmp_path)
    monkeypatch.setattr(
        events,
        "gold_dc_daily_technical_path",
        lambda root, trade_date: root / "gold" / trade_date / "part-000.parquet",
    )
    monkeypatch.setattr(events, "_load_audit_report", lambda _path: {
        "expected_start_date": DATES[0],
        "expected_end_date": DATES[-1],
        "expected_date_count": 611,
        "target_file_count": 611,
    })
    monkeypatch.setattr(events, "_expected_dates_from_calendar", lambda *_args, **_kwargs: DATES)
    monkeypatch.setattr(events, "batch_gold_dc_daily_technical_audit", lambda **_kwargs: _audits())
    monkeypatch.setattr(
        events,
        "asset_readiness_status",
        lambda *_args, **_kwargs: SimpleNamespace(ready=False),
    )


def test_full_event_plan_is_bounded_and_read_only(monkeypatch, tmp_path: Path) -> None:
    instance = _Instance()
    _patch_common_fixtures(monkeypatch, tmp_path)

    plan = events.plan_gold_dc_daily_technical_events(
        instance=instance,
        lake_root=tmp_path,
        audit_report_path=tmp_path / "audit.json",
        duckdb_resource=_DuckDBResource(),
    )

    assert plan.should_stop is False
    assert plan.planned_materialization_count == 611
    assert plan.planned_check_count == 20
    assert plan.planned_event_count == 631
    assert instance.events == []


def test_sample_reports_three_materializations_and_latest_check(monkeypatch, tmp_path: Path) -> None:
    instance = _Instance()
    _patch_common_fixtures(monkeypatch, tmp_path)
    report = events.report_gold_dc_daily_technical_events(
        instance=instance,
        lake_root=tmp_path,
        audit_report_path=tmp_path / "audit.json",
        duckdb_resource=_DuckDBResource(),
        mode="sample",
        dry_run=False,
        confirm_event_write=True,
    )

    assert report.reported_materialization_count == 3
    assert report.reported_check_count == 1
    assert report.reported_event_count == 4
    materializations = [
        event for event in instance.events if isinstance(event, dg.AssetMaterialization)
    ]
    checks = [
        event for event in instance.events if isinstance(event, dg.AssetCheckEvaluation)
    ]
    assert {event.partition for event in materializations} == {DATES[0], DATES[305], DATES[-1]}
    assert len(checks) == 1
    assert checks[0].partition == DATES[-1]
    assert checks[0].check_name == GOLD_DC_DAILY_TECHNICAL_CHECK_NAME
    assert checks[0].target_materialization_data is not None
