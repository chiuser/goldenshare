from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import dagster as dg
import pytest

from orchestrator.defs.bootstrap import stk_mins_bse_recursive_events as events
from orchestrator.defs.bootstrap import stk_mins_bse_recursive_events_cli as cli

DATES = tuple(f"2026-07-{day:02d}" for day in range(1, 21))


class _PlanInstance:
    def __init__(self, registered_dates: tuple[str, ...] = DATES) -> None:
        self.registered_dates = registered_dates

    def get_dynamic_partitions(self, _name: str) -> list[str]:
        return list(self.registered_dates)

    def get_runs(self, **_kwargs: object) -> list[object]:
        return []


def _write_manifest(path: Path, rows: list[dict[str, object]]) -> Path:
    frozen: dict[str, object] = {
        "schema_version": 1,
        "stage": "actual_changed_recursive_manifest",
        "plan_hash": f"source-{path.stem}",
        "changed_file_count": len(rows),
        "changed_files": rows,
    }
    payload = {
        **frozen,
        "manifest_hash": events._hash_payload(frozen),
        "generated_at": "2026-08-27T00:00:00+00:00",
        "should_stop": False,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _row(
    tmp_path: Path,
    *,
    family: str,
    freq: int,
    dates: tuple[str, ...],
) -> dict[str, object]:
    target = tmp_path / f"{family}-{freq}.parquet"
    target.write_bytes(f"{family}:{freq}".encode())
    return {
        "asset_family": family,
        "freq": freq,
        "target_path": str(target),
        "recent_changed_trade_dates": list(dates),
    }


def _stock_audits(
    _lake_root: Path,
    freq: int,
    dates: tuple[str, ...] | list[str],
) -> dict[str, tuple[dg.AssetCheckResult, ...]]:
    results: dict[str, tuple[dg.AssetCheckResult, ...]] = {}
    for trade_date in dates:
        results[f"gold_stk_mins_qfq_macd_kdj_{freq}m|{trade_date}"] = (
            dg.AssetCheckResult(passed=True, metadata={}),
            dg.AssetCheckResult(
                passed=True,
                metadata={"goldenshare/checked_row_count": 100},
            ),
        )
        results[f"gold_stk_mins_qfq_macd_kdj_state_{freq}m|{trade_date}"] = (
            dg.AssetCheckResult(passed=True, metadata={}),
            dg.AssetCheckResult(
                passed=True,
                metadata={"goldenshare/state_row_count": 10},
            ),
        )
    return results


def _nineturn_audit(
    _lake_root: Path,
    _resource: Any,
    _freq: int,
    _trade_date: str,
) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=True,
        metadata={"goldenshare/checked_row_count": 10},
    )


def test_plan_uses_exact_union_of_recursive_manifests(tmp_path: Path) -> None:
    recursive_rows = [
        _row(tmp_path, family=family, freq=freq, dates=DATES)
        for family in ("macd_kdj", "macd_kdj_state")
        for freq in events.RECURSIVE_EVENT_REFRESH_FREQUENCIES
    ]
    follow_up_rows = [
        _row(tmp_path, family="nineturn", freq=freq, dates=(DATES[-1],))
        for freq in (60, 90, 120)
    ]
    manifests = (
        _write_manifest(tmp_path / "recursive.json", recursive_rows),
        _write_manifest(tmp_path / "follow-up.json", follow_up_rows),
    )

    plan = events.plan_bse_recursive_event_refresh(
        instance=_PlanInstance(),
        manifest_paths=manifests,
        lake_root=tmp_path,
        stock_audit_builder=_stock_audits,
        nineturn_audit_builder=_nineturn_audit,
    )

    assert not plan.should_stop
    assert plan.lake_root == tmp_path.resolve()
    assert len(plan.assets) == 17
    assert plan.planned_materialization_count == 283
    assert plan.planned_check_count == 563
    assert plan.planned_event_count == 846
    assert {
        spec.asset_key for spec in plan.assets if spec.asset_family == "nineturn"
    } == {
        "gold_stk_mins_qfq_nineturn_60m",
        "gold_stk_mins_qfq_nineturn_90m",
        "gold_stk_mins_qfq_nineturn_120m",
    }
    assert all("wealth_market_turnover" not in spec.asset_key for spec in plan.assets)


def test_plan_stops_for_missing_registered_partition(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path / "recursive.json",
        [_row(tmp_path, family="macd_kdj", freq=5, dates=DATES)],
    )

    plan = events.plan_bse_recursive_event_refresh(
        instance=_PlanInstance(DATES[:-1]),
        manifest_paths=(manifest,),
        lake_root=tmp_path,
        stock_audit_builder=_stock_audits,
        nineturn_audit_builder=_nineturn_audit,
    )

    assert plan.should_stop
    assert plan.missing_registered_partitions == (DATES[-1],)


def test_plan_rejects_dates_outside_latest_registered_window(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path / "recursive.json",
        [_row(tmp_path, family="macd_kdj", freq=5, dates=(DATES[0],))],
    )
    registered_dates = (*DATES, "2026-07-21")

    with pytest.raises(events.BseRecursiveEventRefreshError, match="latest 20"):
        events.plan_bse_recursive_event_refresh(
            instance=_PlanInstance(registered_dates),
            manifest_paths=(manifest,),
            lake_root=tmp_path,
            stock_audit_builder=_stock_audits,
            nineturn_audit_builder=_nineturn_audit,
        )


def test_apply_is_append_only_latest_bound_and_idempotent(tmp_path: Path) -> None:
    partition_key = "2026-07-20"
    target_path = tmp_path / "nineturn.parquet"
    target_path.write_bytes(b"ready")
    result = dg.AssetCheckResult(
        passed=True,
        metadata={"goldenshare/checked_row_count": 10},
    )
    spec = events.RecursiveEventRefreshAssetSpec(
        asset_family="nineturn",
        asset_key="gold_stk_mins_qfq_nineturn_60m",
        freq=60,
        partition_keys=(partition_key,),
        check_names=("gold_stk_mins_qfq_nineturn_60m_integrity_check",),
        row_count_by_partition={partition_key: 10},
    )
    plan = events.RecursiveEventRefreshPlan(
        plan_hash="reviewed-plan",
        lake_root=tmp_path,
        manifest_paths=(tmp_path / "manifest.json",),
        manifest_evidence=({"manifest_hash": "manifest"},),
        target_fingerprint_hash="fingerprint",
        target_file_count=1,
        assets=(spec,),
        check_results={f"{spec.asset_key}|{partition_key}": (result,)},
        active_run_count=0,
        missing_registered_partitions=(),
        failed_check_items=(),
        elapsed_ms=0,
    )
    checkpoint = tmp_path / "checkpoint.json"

    with dg.DagsterInstance.ephemeral(tempdir=str(tmp_path / "instance")) as instance:
        report = events.apply_bse_recursive_event_refresh(
            instance=instance,
            reviewed_plan=plan,
            expected_plan_hash=plan.plan_hash,
            checkpoint_path=checkpoint,
        )
        post = events.post_audit_bse_recursive_event_refresh(
            instance=instance,
            plan=plan,
        )
        repeated = events.apply_bse_recursive_event_refresh(
            instance=instance,
            reviewed_plan=plan,
            expected_plan_hash=plan.plan_hash,
            checkpoint_path=checkpoint,
        )

        assert report.reported_materialization_count == 1
        assert report.reported_check_count == 1
        assert post.completed_item_count == 2
        assert repeated.reported_materialization_count == 0
        assert repeated.reported_check_count == 0
        assert repeated.skipped_materialization_count == 1
        assert repeated.skipped_check_count == 1
        assert instance.get_runs_count() == 0


def test_cli_requires_explicit_event_write_confirmation(tmp_path: Path) -> None:
    parser = cli._parser()
    args = parser.parse_args(
        [
            "apply",
            "--plan-report",
            str(tmp_path / "plan.json"),
            "--expected-plan-hash",
            "plan",
            "--checkpoint",
            str(tmp_path / "checkpoint.json"),
            "--output",
            str(tmp_path / "apply.json"),
        ]
    )

    with pytest.raises(SystemExit):
        cli._validate(parser, args)


def test_event_tool_scope_does_not_include_upstream_or_turnover_assets() -> None:
    source = Path(events.__file__).read_text(encoding="utf-8")

    for forbidden in (
        'asset_key="raw_stk_mins',
        'asset_key="silver_stk_mins',
        'asset_key="gold_stk_mins_qfq_',
        "gold_wealth_market_turnover",
    ):
        assert forbidden not in source
