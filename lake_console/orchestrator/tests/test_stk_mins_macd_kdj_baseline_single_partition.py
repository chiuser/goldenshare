"""M2B write gates: real orchestration and event construction, isolated I/O."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import dagster as dg
import pytest

from orchestrator.defs.bootstrap import stk_mins_qfq_macd_kdj_baseline_events as events
from orchestrator.defs.bootstrap import stk_mins_qfq_macd_kdj_history as history

DAY = "2026-09-04"
OTHER_DAY = "2026-09-03"


@pytest.fixture
def rig(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError(
            "unexpected filesystem, database or formal instance access"
        )

    monkeypatch.setattr(dg.DagsterInstance, "get", forbidden)
    monkeypatch.setattr("socket.socket.connect", forbidden)
    monkeypatch.setattr(events, "connect_configured_duckdb", forbidden)
    for name in (
        "open",
        "glob",
        "rglob",
        "read_bytes",
        "write_bytes",
        "mkdir",
        "replace",
    ):
        monkeypatch.setattr(Path, name, forbidden)
    monkeypatch.setattr("os.replace", forbidden)
    instance = Mock(
        spec_set=["report_runless_asset_event", "get_materialized_partitions"]
    )
    instance.get_materialized_partitions.return_value = set()
    plan = events.StkMinsQfqMacdKdjBaselineEventPlan(
        selected_partition_keys=(DAY,),
        selected_freqs=(5,),
        selected_years=("2026",),
        history_plan=SimpleNamespace(),
        materialized_partition_counts={},
        check_success_counts={},
    )
    planner = Mock(return_value=plan)
    files = Mock(return_value=SimpleNamespace(passed=True))
    ready = Mock(return_value=False)

    def audit(*, lake_root, freq, partition_key, state=False):
        keys = (
            events.GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_ASSET_KEYS
            if state
            else events.GOLD_STK_MINS_QFQ_MACD_KDJ_ASSET_KEYS
        )
        names = (
            events.GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_CHECKS
            if state
            else events.GOLD_STK_MINS_QFQ_MACD_KDJ_CHECKS
        )
        return events.StkMinsQfqMacdKdjBootstrapAssetAudit(
            freq=freq,
            partition_key=partition_key,
            asset_key=keys[freq],
            output_uri=lake_root
            / f"{'state' if state else 'indicator'}-{freq}.parquet",
            row_count=7,
            observed_columns=("ts_code", "trade_time"),
            checks=tuple(
                events.StkMinsQfqMacdKdjBootstrapCheckAudit(
                    name, True, {"sample": "ok"}
                )
                for name in names
            ),
        )

    indicator = Mock(side_effect=audit)
    state = Mock(side_effect=lambda **kwargs: audit(**kwargs, state=True))
    latest = Mock(
        return_value=SimpleNamespace(
            storage_id=17, run_id="baseline-test", timestamp=123.0
        )
    )
    monkeypatch.setattr(events, "plan_stk_mins_qfq_macd_kdj_baseline_events", planner)
    monkeypatch.setattr(events, "audit_stk_mins_qfq_macd_kdj_files", files)
    monkeypatch.setattr(events, "_asset_ready", ready)
    monkeypatch.setattr(events, "_audit_indicator_asset_partition", indicator)
    monkeypatch.setattr(events, "_audit_state_asset_partition", state)
    monkeypatch.setattr(events, "_latest_materialization", latest)
    return SimpleNamespace(
        instance=instance,
        plan=plan,
        planner=planner,
        files=files,
        ready=ready,
        indicator=indicator,
        state=state,
        latest=latest,
    )


def run(rig, **kwargs):
    arguments = {
        "instance": rig.instance,
        "lake_root": Path("/contract/formal-lake"),
        "duckdb": object(),
        "registered_partition_keys": (OTHER_DAY, DAY),
        "start_date": DAY,
        "end_date": DAY,
    }
    arguments.update(kwargs)
    return events.report_stk_mins_qfq_macd_kdj_baseline_events(**arguments)


def assert_no_audit_or_events(rig):
    for capability in (
        rig.files,
        rig.ready,
        rig.indicator,
        rig.state,
        rig.latest,
        rig.instance.report_runless_asset_event,
    ):
        capability.assert_not_called()


@pytest.mark.parametrize("dry_run", (False, True))
@pytest.mark.parametrize(
    "invalid",
    (
        {"start_date": None},
        {"end_date": None},
        {"start_date": "", "end_date": ""},
        {"end_date": OTHER_DAY},
        {"start_date": "invalid", "end_date": "invalid"},
        {"partition_keys": ()},
        {"partition_keys": (OTHER_DAY,)},
        {"partition_keys": (DAY, OTHER_DAY)},
    ),
)
def test_direct_python_report_cannot_bypass_request_gate(rig, invalid, dry_run):
    with pytest.raises(ValueError):
        run(rig, dry_run=dry_run, **invalid)
    rig.planner.assert_not_called()
    assert_no_audit_or_events(rig)


@pytest.mark.parametrize("dry_run", (False, True))
@pytest.mark.parametrize("keys", ((), (DAY, OTHER_DAY), (OTHER_DAY,), (DAY, DAY)))
def test_actual_plan_is_checked_before_any_audit_or_event(rig, keys, dry_run):
    rig.planner.return_value = replace(rig.plan, selected_partition_keys=keys)
    with pytest.raises(ValueError, match="exactly the requested day's partition"):
        run(rig, dry_run=dry_run, skip_existing_ready=True)
    rig.planner.assert_called_once()
    assert_no_audit_or_events(rig)


@pytest.mark.parametrize("dry_run", (False, True))
@pytest.mark.parametrize("partition_keys", (None, (DAY,), (DAY, DAY)))
def test_single_partition_preserves_event_payloads_and_dry_run(
    rig, dry_run, partition_keys
):
    report = run(rig, dry_run=dry_run, partition_keys=partition_keys)
    rig.planner.assert_called_once()
    assert rig.planner.call_args.kwargs["include_check_success_counts"] is False
    assert rig.planner.call_args.kwargs["partition_keys"] == partition_keys
    rig.files.assert_called_once()
    rig.indicator.assert_called_once()
    rig.state.assert_called_once()
    assert report.plan is rig.plan
    assert report.failed_asset_partition_count == 0
    assert len(report.asset_audits) == 2
    assert report.skipped_ready_asset_partitions == ()
    emitted = [
        call.args[0] for call in rig.instance.report_runless_asset_event.call_args_list
    ]
    assert report.reported_event_count == len(emitted) == (0 if dry_run else 6)
    assert len(report.reported_asset_partitions) == (0 if dry_run else 2)
    if dry_run:
        rig.latest.assert_not_called()
    else:
        assert [type(event) for event in emitted] == [
            dg.AssetMaterialization,
            dg.AssetCheckEvaluation,
            dg.AssetCheckEvaluation,
        ] * 2
        assert {event.partition for event in emitted} == {DAY}
        assert tuple(
            event.check_name
            for event in emitted
            if isinstance(event, dg.AssetCheckEvaluation)
        ) == (
            *events.GOLD_STK_MINS_QFQ_MACD_KDJ_CHECKS,
            *events.GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_CHECKS,
        )
        for event in emitted:
            if isinstance(event, dg.AssetMaterialization):
                assert event.metadata["dagster/row_count"].value == 7
                assert event.metadata["goldenshare/partition_key"].value == DAY
                assert (
                    event.metadata["goldenshare/baseline_event_tracking"].value is True
                )
                assert (
                    event.metadata["goldenshare/source_method"].value
                    == "stk_mins_qfq_macd_kdj_history_generation"
                )
            else:
                assert event.passed and event.blocking
                assert event.target_materialization_data.storage_id == 17
                assert event.target_materialization_data.run_id == "baseline-test"


def test_all_frequencies_remain_supported_with_bounded_event_count(rig):
    rig.planner.return_value = replace(
        rig.plan, selected_freqs=events.STK_MINS_QFQ_FREQS
    )
    report = run(rig)
    assert len(events.STK_MINS_QFQ_FREQS) == 7
    assert report.plan.planned_event_count == report.reported_event_count == 42
    assert len(report.reported_asset_partitions) == 14
    rig.planner.assert_called_once()
    rig.files.assert_called_once()


@pytest.mark.parametrize("dry_run", (False, True))
def test_skip_ready_and_file_audit_semantics_are_unchanged(rig, dry_run):
    rig.ready.return_value = True
    report = run(rig, dry_run=dry_run, skip_existing_ready=True)
    assert len(report.skipped_ready_asset_partitions) == 2
    assert report.asset_audits == report.reported_asset_partitions == ()
    assert report.reported_event_count == 0
    rig.files.assert_called_once()
    assert rig.ready.call_count == 2
    rig.indicator.assert_not_called()
    rig.state.assert_not_called()
    rig.instance.report_runless_asset_event.assert_not_called()


@pytest.mark.parametrize("dry_run", (False, True))
def test_failed_file_audit_still_blocks_events(rig, dry_run):
    rig.files.return_value = SimpleNamespace(passed=False)
    with pytest.raises(RuntimeError, match="file audit failed"):
        run(rig, dry_run=dry_run)
    rig.indicator.assert_not_called()
    rig.state.assert_not_called()
    rig.instance.report_runless_asset_event.assert_not_called()


@pytest.mark.parametrize("dry_run", (False, True))
def test_failed_asset_check_still_blocks_events(rig, dry_run):
    good = rig.indicator.side_effect(
        lake_root=Path("/contract"), freq=5, partition_key=DAY
    )
    rig.indicator.side_effect = None
    rig.indicator.return_value = replace(
        good, checks=(replace(good.checks[0], passed=False),)
    )
    with pytest.raises(RuntimeError, match="baseline event audit failed"):
        run(rig, dry_run=dry_run)
    rig.instance.report_runless_asset_event.assert_not_called()


def test_planner_failure_propagates_without_retry(rig):
    failure = RuntimeError("planner failed")
    rig.planner.side_effect = failure
    with pytest.raises(RuntimeError) as exc:
        run(rig)
    assert exc.value is failure
    rig.planner.assert_called_once()
    assert_no_audit_or_events(rig)


@pytest.mark.parametrize(
    "keys,years",
    ((None, None), ((DAY, DAY), None), ((OTHER_DAY,), None), (None, ("2025",))),
)
def test_real_selection_keeps_single_day_gate_and_rejects_empty_or_other_day(
    monkeypatch, keys, years
):
    # Real report -> real baseline planner -> real history selector; discovery is isolated.
    discovery = Mock(return_value=())
    monkeypatch.setattr(
        history, "discover_gold_stk_mins_qfq_source_year_paths", discovery
    )
    instance = Mock(
        spec_set=["get_materialized_partitions", "report_runless_asset_event"]
    )
    instance.get_materialized_partitions.return_value = set()
    files = Mock(return_value=SimpleNamespace(passed=False))
    monkeypatch.setattr(events, "audit_stk_mins_qfq_macd_kdj_files", files)
    with pytest.raises(
        RuntimeError if keys != (OTHER_DAY,) and years is None else ValueError
    ):
        events.report_stk_mins_qfq_macd_kdj_baseline_events(
            instance=instance,
            lake_root=Path("/contract"),
            duckdb=object(),
            registered_partition_keys=(OTHER_DAY, DAY),
            start_date=DAY,
            end_date=DAY,
            partition_keys=keys,
            years=years,
            freqs=(5,),
            dry_run=True,
        )
    instance.report_runless_asset_event.assert_not_called()
    if years is None and keys != (OTHER_DAY,):
        discovery.assert_called_once_with(Path("/contract"), freq=5, trade_dates=(DAY,))
        files.assert_called_once()
    else:
        discovery.assert_not_called()
        files.assert_not_called()


def test_readonly_baseline_planner_keeps_multi_day_support(monkeypatch):
    discovery = Mock(return_value=())
    monkeypatch.setattr(
        history, "discover_gold_stk_mins_qfq_source_year_paths", discovery
    )
    instance = Mock(spec_set=["get_materialized_partitions"])
    instance.get_materialized_partitions.return_value = set()
    plan = events.plan_stk_mins_qfq_macd_kdj_baseline_events(
        instance=instance,
        lake_root=Path("/contract"),
        duckdb_resource=object(),
        registered_partition_keys=(OTHER_DAY, DAY),
        start_date=OTHER_DAY,
        end_date=DAY,
        freqs=(5,),
        include_check_success_counts=False,
    )
    assert plan.selected_partition_keys == (OTHER_DAY, DAY)
    discovery.assert_called_once_with(
        Path("/contract"), freq=5, trade_dates=(OTHER_DAY, DAY)
    )


def test_file_audit_keeps_existing_second_history_plan_without_extra_preflight(
    monkeypatch,
):
    # Baseline planner calls history once; the unchanged file audit calls it again.
    discovery = Mock(return_value=())
    monkeypatch.setattr(
        history, "discover_gold_stk_mins_qfq_source_year_paths", discovery
    )
    history_planner = Mock(wraps=history.plan_stk_mins_qfq_macd_kdj_history)
    monkeypatch.setattr(history, "plan_stk_mins_qfq_macd_kdj_history", history_planner)
    monkeypatch.setattr(events, "plan_stk_mins_qfq_macd_kdj_history", history_planner)
    baseline_planner = Mock(wraps=events.plan_stk_mins_qfq_macd_kdj_baseline_events)
    monkeypatch.setattr(
        events, "plan_stk_mins_qfq_macd_kdj_baseline_events", baseline_planner
    )
    instance = Mock(
        spec_set=["get_materialized_partitions", "report_runless_asset_event"]
    )
    instance.get_materialized_partitions.return_value = set()
    with pytest.raises(RuntimeError, match="file audit failed"):
        events.report_stk_mins_qfq_macd_kdj_baseline_events(
            instance=instance,
            lake_root=Path("/contract"),
            duckdb=object(),
            registered_partition_keys=(OTHER_DAY, DAY),
            start_date=DAY,
            end_date=DAY,
            freqs=(5,),
            dry_run=True,
        )
    baseline_planner.assert_called_once()
    assert history_planner.call_count == 2
    assert discovery.call_count == 3
    assert all(
        call.kwargs["trade_dates"] == (DAY,) for call in discovery.call_args_list
    )
    instance.report_runless_asset_event.assert_not_called()
