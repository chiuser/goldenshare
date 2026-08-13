from __future__ import annotations

from pathlib import Path

import dagster as dg
import pytest

from orchestrator.defs.bootstrap import cn_a_minute_gold_p9_events as events
from orchestrator.defs.bootstrap import cn_a_minute_gold_p9_events_cli as cli


def test_p9_scope_is_exactly_the_rebuilt_families() -> None:
    assert events.P9_FREQUENCIES == (5, 15, 30, 60)
    assert events.P9_CHECK_WINDOW == 20
    assert events.P9_FAMILIES == (
        "index_gold",
        "major_index_gold",
        "major_index_technical_state",
        "stock_qfq",
        "stock_indicator_state",
    )


def test_cli_requires_explicit_apply_identity(tmp_path: Path) -> None:
    parser = cli._parser()
    args = parser.parse_args(["apply", "--output", str(tmp_path / "out.json")])
    with pytest.raises(SystemExit):
        cli._validate(parser, args)


def test_cli_dry_run_rejects_event_write_confirmation(tmp_path: Path) -> None:
    parser = cli._parser()
    args = parser.parse_args(
        [
            "dry-run",
            "--confirm-event-write",
            "--output",
            str(tmp_path / "out.json"),
        ]
    )
    with pytest.raises(SystemExit):
        cli._validate(parser, args)


def test_apply_reports_materialization_before_latest_bound_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = events.P9AssetSpec(
        family="index_gold",
        asset_key="gold_index_mins_5m",
        freq=5,
        partition_set="cn_a_index_mins_trade_days",
        trade_dates=("2026-08-12",),
        check_names=("gold_index_mins_5m_core_check",),
        observed_columns=("trade_date",),
        uri_builder=lambda _date: tmp_path / "part-000.parquet",
        row_count_by_date={"2026-08-12": 1},
        source_method="test",
    )
    check = dg.AssetCheckResult(passed=True, metadata={})
    plan = events.P9Plan(
        plan_hash="plan",
        evidence_hashes={},
        assets=(spec,),
        recent_dates_by_partition_set={"cn_a_index_mins_trade_days": ("2026-08-12",)},
        missing_registered={"cn_a_index_mins_trade_days": ()},
        active_run_count=0,
        check_audits={"gold_index_mins_5m|2026-08-12": (check,)},
        elapsed_ms=0.0,
    )
    calls: list[str] = []
    monkeypatch.setattr(
        events,
        "_report_materialization",
        lambda *_args, **_kwargs: calls.append("materialization"),
    )
    monkeypatch.setattr(
        events,
        "_latest_materialization_for_p9",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        events,
        "_report_checks",
        lambda *_args, **_kwargs: (calls.append("check") or 1, 0),
    )

    report = events.apply_p9_family(
        instance=object(),
        plan=plan,
        family="index_gold",
        checkpoint_path=tmp_path / "checkpoint.json",
        expected_plan_hash="plan",
    )

    assert calls == ["materialization", "check"]
    assert report.reported_materializations == 1
    assert report.reported_checks == 1


def test_runless_check_revision_keeps_event_log_and_rebinds_latest_materialization(
    tmp_path: Path,
) -> None:
    from dagster._core.storage.event_log.schema import (
        AssetCheckExecutionsTable,
        SqlEventLogStorageTable,
    )

    instance = dg.DagsterInstance.ephemeral(tempdir=str(tmp_path))
    spec = events.P9AssetSpec(
        family="index_gold",
        asset_key="gold_index_mins_5m",
        freq=5,
        partition_set="cn_a_index_mins_trade_days",
        trade_dates=("2026-08-12",),
        check_names=("gold_index_mins_5m_core_check",),
        observed_columns=("trade_date",),
        uri_builder=lambda _date: tmp_path / "part-000.parquet",
        row_count_by_date={"2026-08-12": 1},
        source_method="test",
    )
    check = dg.AssetCheckResult(passed=True, metadata={})

    def plan(plan_hash: str) -> events.P9Plan:
        return events.P9Plan(
            plan_hash=plan_hash,
            evidence_hashes={},
            assets=(spec,),
            recent_dates_by_partition_set={
                "cn_a_index_mins_trade_days": ("2026-08-12",)
            },
            missing_registered={"cn_a_index_mins_trade_days": ()},
            active_run_count=0,
            check_audits={"gold_index_mins_5m|2026-08-12": (check,)},
            elapsed_ms=0.0,
        )

    old_plan = plan("old-plan")
    events._report_materialization(
        instance, plan=old_plan, spec=spec, date="2026-08-12"
    )
    assert events._report_checks(
        instance, plan=old_plan, spec=spec, date="2026-08-12"
    ) == (1, 0)

    current_plan = plan("current-plan")
    events._report_materialization(
        instance, plan=current_plan, spec=spec, date="2026-08-12"
    )
    latest = events._latest_materialization(instance, spec.asset_key, "2026-08-12")
    assert events._report_checks(
        instance, plan=current_plan, spec=spec, date="2026-08-12"
    ) == (1, 1)

    with instance.event_log_storage.index_connection() as connection:
        check_rows = connection.execute(AssetCheckExecutionsTable.select()).fetchall()
        event_rows = connection.execute(
            SqlEventLogStorageTable.select().where(
                SqlEventLogStorageTable.c.dagster_event_type == "ASSET_CHECK_EVALUATION"
            )
        ).fetchall()
    assert len(check_rows) == 1
    assert check_rows[0].materialization_event_storage_id == latest.storage_id
    assert len(event_rows) == 2

    assert events._report_checks(
        instance, plan=current_plan, spec=spec, date="2026-08-12"
    ) == (0, 0)


def test_apply_rejects_failed_recent_check(tmp_path: Path) -> None:
    spec = events.P9AssetSpec(
        family="index_gold",
        asset_key="gold_index_mins_5m",
        freq=5,
        partition_set="cn_a_index_mins_trade_days",
        trade_dates=("2026-08-12",),
        check_names=("gold_index_mins_5m_core_check",),
        observed_columns=("trade_date",),
        uri_builder=lambda _date: tmp_path / "part-000.parquet",
        row_count_by_date={"2026-08-12": 1},
        source_method="test",
    )
    plan = events.P9Plan(
        plan_hash="plan",
        evidence_hashes={},
        assets=(spec,),
        recent_dates_by_partition_set={"cn_a_index_mins_trade_days": ("2026-08-12",)},
        missing_registered={"cn_a_index_mins_trade_days": ()},
        active_run_count=0,
        check_audits={
            "gold_index_mins_5m|2026-08-12": (dg.AssetCheckResult(passed=False),)
        },
        elapsed_ms=0.0,
    )

    with pytest.raises(events.MinuteGoldP9EventError, match="preflight"):
        events.apply_p9_family(
            instance=object(),
            plan=plan,
            family="index_gold",
            checkpoint_path=tmp_path / "checkpoint.json",
            expected_plan_hash="plan",
        )


def test_checkpoint_plan_hash_is_immutable(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.json"
    events._atomic_json(
        checkpoint,
        {"plan_hash": "other", "completed_items": []},
    )
    with pytest.raises(events.MinuteGoldP9EventError, match="another plan"):
        events._checkpoint(checkpoint, plan_hash="plan")
