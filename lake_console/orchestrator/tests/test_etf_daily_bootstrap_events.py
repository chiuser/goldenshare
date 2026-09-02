from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import dagster as dg
import pytest

from orchestrator.defs.bootstrap.etf_daily_bootstrap_events import (
    EtfDailyBootstrapEventsError,
    apply_events,
    build_event_plan,
    load_event_plan,
    post_audit_events,
    write_event_plan,
)
from orchestrator.defs.bootstrap.etf_daily_bootstrap_plan import (
    EtfDailyRawManifestEntry,
    EtfDailySilverBootstrapPlan,
    hash_payload,
)
from orchestrator.defs.run_contracts.etf_basic import (
    build_etf_basic_silver_snapshot_reference,
)
from orchestrator.defs.run_contracts.etf_daily import (
    ETF_DAILY_BOOTSTRAP_CONTRACT_REVISION,
    ETF_DAILY_COVERAGE_POLICY_REVISION,
    FUND_ADJ_SOURCE_COLUMNS,
    FUND_DAILY_SOURCE_COLUMNS,
)


def _dates(count: int) -> tuple[str, ...]:
    start = date(2025, 1, 2)
    return tuple((start + timedelta(days=index)).isoformat() for index in range(count))


def _basic_reference():  # type: ignore[no-untyped-def]
    return build_etf_basic_silver_snapshot_reference(
        raw_snapshot_hash="1" * 64,
        silver_content_hash="2" * 64,
        raw_uri="/tmp/raw-basic.parquet",
        silver_uri="/tmp/silver-basic.parquet",
        raw_observed_at="2026-09-03T20:55:00+08:00",
        silver_observed_at="2026-09-03T20:55:00+08:00",
        eligibility_as_of="2026-09-03",
        requestable_code_count=1,
        requestable_code_hash="3" * 64,
    )


def _silver_plan(dates: tuple[str, ...]) -> EtfDailySilverBootstrapPlan:
    manifest = tuple(
        EtfDailyRawManifestEntry(
            asset_key=asset_key,  # type: ignore[arg-type]
            trade_date=trade_date,
            target_path=f"/tmp/{asset_key}/{trade_date}.parquet",
            row_count=1,
            content_hash=("a" if asset_key.endswith("daily") else "b") * 64,
            size_bytes=100,
        )
        for trade_date in dates
        for asset_key in ("raw_tushare_fund_daily", "raw_tushare_fund_adj")
    )
    return EtfDailySilverBootstrapPlan(
        schema_version="etf_daily_bootstrap_v1",
        operation_id="event-test",
        created_at=datetime(2026, 9, 3, tzinfo=UTC).isoformat(),
        code_revision="revision",
        contract_revision=ETF_DAILY_BOOTSTRAP_CONTRACT_REVISION,
        parent_raw_plan_hash="4" * 64,
        raw_manifest=manifest,
        raw_manifest_hash=hash_payload([item.to_dict() for item in manifest]),
        coverage_policy_revision=ETF_DAILY_COVERAGE_POLICY_REVISION,
        basic_reference=_basic_reference(),
        silver_targets=(),
        estimated_new_bytes=0,
        required_free_bytes=0,
        observed_free_bytes=1,
        silver_plan_hash="5" * 64,
    )


def _physical_report(path: Path, plan: EtfDailySilverBootstrapPlan) -> None:
    evidence: list[dict[str, object]] = []
    for trade_date in plan.trade_dates:
        for asset_key, columns, content_hash in (
            ("raw_tushare_fund_daily", FUND_DAILY_SOURCE_COLUMNS, "a" * 64),
            ("raw_tushare_fund_adj", FUND_ADJ_SOURCE_COLUMNS, "b" * 64),
            ("silver_etf_daily", FUND_DAILY_SOURCE_COLUMNS, "c" * 64),
            ("silver_etf_adj_factor", FUND_ADJ_SOURCE_COLUMNS, "d" * 64),
        ):
            item: dict[str, object] = {
                "asset_key": asset_key,
                "trade_date": trade_date,
                "target_path": f"/tmp/{asset_key}/{trade_date}.parquet",
                "row_count": 1,
                "content_hash": content_hash,
                "source_fields": list(columns),
                "written_row_count": 1,
                "passed": True,
            }
            if asset_key.startswith("raw_"):
                item.update({"source_row_count": 1, "normalized_row_count": 1})
            else:
                item.update(
                    {
                        "raw_row_count": 1,
                        "selected_row_count": 1,
                        "rejected_row_count": 0,
                        "reject_reason_counts": {},
                        "basic_reference": plan.basic_reference.model_dump(mode="json"),
                        "basic_reference_fingerprint": (
                            plan.basic_reference.reference_fingerprint
                        ),
                        "basic_raw_snapshot_hash": plan.basic_reference.raw_snapshot_hash,
                        "basic_silver_content_hash": (
                            plan.basic_reference.silver_content_hash
                        ),
                        "basic_raw_uri": plan.basic_reference.raw_uri,
                        "basic_silver_uri": plan.basic_reference.silver_uri,
                    }
                )
            evidence.append(item)
    report: dict[str, object] = {
        "schema_version": "etf_daily_physical_post_audit_v1",
        "silver_plan_hash": plan.silver_plan_hash,
        "file_evidence": evidence,
        "passed": True,
        "dagster_events_written": 0,
    }
    report["report_hash"] = hash_payload(report)
    path.write_text(
        __import__("json").dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_event_plan_materializes_all_dates_but_checks_only_recent_twenty(
    tmp_path: Path,
) -> None:
    plan = _silver_plan(_dates(21))
    physical = tmp_path / "physical.json"
    _physical_report(physical, plan)
    with dg.DagsterInstance.ephemeral(tempdir=tmp_path / "instance") as instance:
        event_plan = build_event_plan(
            instance=instance,
            silver_plan=plan,
            physical_report_path=physical,
        )
    assert len(event_plan.materializations) == 84
    assert len(event_plan.checks) == 20 * (3 + 3 + 5 + 5)
    assert {item.trade_date for item in event_plan.checks} == set(plan.trade_dates[-20:])
    assert len(event_plan.pending_materializations) == 84
    assert event_plan.active_run_count == 0
    assert event_plan.should_stop is False


def test_event_plan_round_trip_apply_replay_and_post_audit(tmp_path: Path) -> None:
    plan = _silver_plan(_dates(2))
    physical = tmp_path / "physical.json"
    _physical_report(physical, plan)
    checkpoint = tmp_path / "checkpoint.json"
    with dg.DagsterInstance.ephemeral(tempdir=tmp_path / "instance") as instance:
        event_plan = build_event_plan(
            instance=instance,
            silver_plan=plan,
            physical_report_path=physical,
        )
        event_plan_path = tmp_path / "events-plan.json"
        write_event_plan(event_plan, event_plan_path)
        loaded = load_event_plan(
            event_plan_path,
            expected_plan_hash=event_plan.event_plan_hash,
        )
        assert loaded == event_plan

        first = apply_events(
            instance=instance,
            plan=loaded,
            checkpoint_path=checkpoint,
            output_path=tmp_path / "events-apply.json",
            confirm_events_apply=True,
        )
        assert first["reported_materialization_count"] == 8
        assert first["reported_check_count"] == 32

        second = apply_events(
            instance=instance,
            plan=loaded,
            checkpoint_path=checkpoint,
            output_path=tmp_path / "events-apply.json",
            confirm_events_apply=True,
        )
        assert second["reported_materialization_count"] == 0
        assert second["reported_check_count"] == 0
        audited = post_audit_events(
            instance=instance,
            plan=loaded,
            output_path=tmp_path / "events-post-audit.json",
        )
        assert audited["passed"] is True


def test_existing_non_equivalent_materialization_is_a_hard_conflict(
    tmp_path: Path,
) -> None:
    plan = _silver_plan(_dates(1))
    physical = tmp_path / "physical.json"
    _physical_report(physical, plan)
    with dg.DagsterInstance.ephemeral(tempdir=tmp_path / "instance") as instance:
        instance.report_runless_asset_event(
            dg.AssetMaterialization(
                asset_key=dg.AssetKey("raw_tushare_fund_daily"),
                partition=plan.trade_dates[0],
                metadata={"dagster/row_count": 999},
            )
        )
        event_plan = build_event_plan(
            instance=instance,
            silver_plan=plan,
            physical_report_path=physical,
        )
        assert event_plan.should_stop is True
        assert event_plan.conflicting_materializations == (
            f"raw_tushare_fund_daily|{plan.trade_dates[0]}",
        )
        with pytest.raises(EtfDailyBootstrapEventsError, match="conflict"):
            apply_events(
                instance=instance,
                plan=event_plan,
                checkpoint_path=tmp_path / "checkpoint.json",
                output_path=tmp_path / "events-apply.json",
                confirm_events_apply=True,
            )


def test_events_apply_requires_explicit_confirmation(tmp_path: Path) -> None:
    plan = _silver_plan(_dates(1))
    physical = tmp_path / "physical.json"
    _physical_report(physical, plan)
    with dg.DagsterInstance.ephemeral(tempdir=tmp_path / "instance") as instance:
        event_plan = build_event_plan(
            instance=instance,
            silver_plan=plan,
            physical_report_path=physical,
        )
        with pytest.raises(EtfDailyBootstrapEventsError, match="confirmation"):
            apply_events(
                instance=instance,
                plan=event_plan,
                checkpoint_path=tmp_path / "checkpoint.json",
                output_path=tmp_path / "events-apply.json",
                confirm_events_apply=False,
            )


def test_active_dagster_run_stops_event_plan_and_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _silver_plan(_dates(1))
    physical = tmp_path / "physical.json"
    _physical_report(physical, plan)
    monkeypatch.setattr(
        "orchestrator.defs.bootstrap.etf_daily_bootstrap_events._active_run_count",
        lambda _instance: 1,
    )
    with dg.DagsterInstance.ephemeral(tempdir=tmp_path / "instance") as instance:
        event_plan = build_event_plan(
            instance=instance,
            silver_plan=plan,
            physical_report_path=physical,
        )
        assert event_plan.active_run_count == 1
        assert event_plan.should_stop is True
        with pytest.raises(EtfDailyBootstrapEventsError, match="active run"):
            apply_events(
                instance=instance,
                plan=event_plan,
                checkpoint_path=tmp_path / "checkpoint.json",
                output_path=tmp_path / "events-apply.json",
                confirm_events_apply=True,
            )
