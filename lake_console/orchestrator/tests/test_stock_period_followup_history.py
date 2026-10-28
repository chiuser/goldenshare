"""Real tiny Raw producers; no formal paths, credentials, or source requests.

Wire rows and baseline come from the existing contract fixtures. Expected prices,
scope and interruption outcomes below are independent literals.
"""

import os
from datetime import date
from pathlib import Path

import dagster as dg
import pytest

from orchestrator.defs import stock_period_update as update
from orchestrator.defs.bootstrap import stock_period_history as history
from orchestrator.defs.io import stock_period_raw as raw
from orchestrator.defs.run_contracts.stock_period import VERSION, digest, execution_id
from tests.test_stock_period_combined import (
    A,
    B,
    bootstrap,
    combined_intent,
    combined_source,
    row,
    values,
    wire,
)


def manual_intent(request="manual-first"):
    return {
        "version": VERSION,
        "mode": "history",
        "frequencies": ["week"],
        "codes": [A],
        "request_id": request,
    }


def forbidden(*args, **kwargs):
    pytest.fail("unexpected source, current scope, factor scan, or file rewrite")


def test_coordinator_recovers_rename_before_checkpoint_without_rewriting(
    tmp_path, monkeypatch
):
    arguments = bootstrap(tmp_path)
    intent = combined_intent("rename-gap")
    original = raw.atomic_json
    failed = []

    def interrupt(path, payload):
        if "committed" in Path(path).parts:
            failed.append((Path(path), payload))
            raise OSError("after_rename_before_cp")
        return original(path, payload)

    monkeypatch.setattr(raw, "atomic_json", interrupt)
    with pytest.raises(OSError, match="after_rename_before_cp"):
        history.run_period(**arguments, intent=intent, transport=combined_source)
    checkpoint, item = failed[0]
    before = raw.file_version(item["target"])
    assert not checkpoint.exists() and not Path(item["candidate"]).exists()
    assert before == item["version"]
    monkeypatch.setattr(raw, "atomic_json", original)
    original_digest = raw.file_digest
    hashes = []

    def counted(path):
        hashes.append(str(path))
        return original_digest(path)

    monkeypatch.setattr(raw, "file_digest", counted)
    monkeypatch.setattr(
        raw.os,
        "replace",
        lambda source, target: (
            forbidden() if str(target) == item["target"] else os_replace(source, target)
        ),
    )
    result = history.run_period(**arguments, intent=intent, transport=forbidden)
    assert hashes.count(item["target"]) == 1
    assert raw.file_version(item["target"]) == before
    assert raw.read_json(checkpoint)["version"] == before
    assert len(result["files"]) == 3
    assert [(r[0], str(r[2])) for r in values(arguments["root"], "2026-10-16")] == [
        (A, "3.0000"),
        (B, "8.0000"),
    ]


os_replace = os.replace


def test_manual_history_registration_survives_before_manifest(tmp_path, monkeypatch):
    arguments = bootstrap(tmp_path)
    intent = manual_intent()
    run = (
        arguments["staging"] / "stock_period/runs" / execution_id(intent["request_id"])
    )
    original = history.atomic_json

    def interrupt(path, payload):
        if Path(path) == run / "manifest.json":
            raise OSError("before_manifest")
        return original(path, payload)

    monkeypatch.setattr(history, "atomic_json", interrupt)
    with pytest.raises(OSError, match="before_manifest"):
        history.run_period(**arguments, intent=intent, transport=forbidden)
    state_path = arguments["staging"] / "stock_period/daily.json"
    state = raw.read_json(state_path)
    assert set(state) == {"pending_work"}
    work = state["pending_work"][run.name]
    assert work["kind"] == "history" and "consumed" not in work
    assert history.ordered_pending_work(arguments["staging"]) == [work]
    monkeypatch.setattr(history, "atomic_json", original)
    result = history.run_period(**arguments, intent=intent, transport=combined_source)
    assert raw.read_json(run / "manifest.json")["started_at"] == work["started_at"]
    assert raw.read_json(state_path)["pending_work"][run.name] == work
    assert [item["period"] for item in result["files"]] == [
        "2026-10-02",
        "2026-10-09",
        "2026-10-16",
    ]


def test_manual_history_blocks_new_history_and_daily_without_consumption(
    tmp_path, monkeypatch
):
    arguments = bootstrap(tmp_path)
    result = history.run_period(
        **arguments, intent=manual_intent(), transport=combined_source
    )
    path = arguments["staging"] / "stock_period/daily.json"
    state = raw.read_json(path)
    state.update(
        factor_through="2026-10-15",
        last_refresh={},
        completed_through={"week": "2026-10-09", "month": "2026-09"},
    )
    raw.atomic_json(path, state)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="period_original_run_required"):
        history.run_period(
            **arguments, intent=manual_intent("manual-next"), transport=forbidden
        )
    monkeypatch.setattr(update, "calendar_days", forbidden)
    monkeypatch.setattr(update, "factor_changes", forbidden)
    monkeypatch.setattr(update, "_consume_daily_files", forbidden)
    with pytest.raises(ValueError, match="period_original_history_required"):
        update.execute_daily(
            **arguments, today=date(2026, 10, 19), freq="week", transport=forbidden
        )
    assert path.read_bytes() == before
    assert all(
        raw.file_version(item["target"]) == item["version"] for item in result["files"]
    )


def test_history_real_confirmation_closes_queue_without_daily_watermarks(tmp_path):
    from tests.test_stock_period_delivery_confirmation import _emit

    arguments = bootstrap(tmp_path)
    result = history.run_period(
        **arguments, intent=manual_intent(), transport=combined_source
    )
    path = arguments["staging"] / "stock_period/daily.json"
    instance_path = tmp_path / "instance"
    instance_path.mkdir()
    (instance_path / "dagster.yaml").write_text("telemetry:\n  enabled: false\n")
    with dg.DagsterInstance.local_temp(str(instance_path)) as instance:
        _emit(instance, result)
        confirmation = lambda run: update.confirm_period_delivery(
            instance, run, root=arguments["root"], staging=arguments["staging"]
        )
        history.replay_events(
            Path(result["path"]),
            root=arguments["root"],
            staging=arguments["staging"],
            confirm_delivery=confirmation,
        )
        assert raw.read_json(path) == {"pending_work": {}}
        history.replay_events(
            Path(result["path"]),
            root=arguments["root"],
            staging=arguments["staging"],
            confirm_delivery=confirmation,
        )
        assert raw.read_json(path) == {"pending_work": {}}


@pytest.mark.parametrize("problem", ["hash", "version", "missing", "interval_hole"])
def test_history_rejects_bad_range_before_old_sql(tmp_path, monkeypatch, problem):
    arguments = bootstrap(tmp_path)
    baseline = arguments["staging"] / "stock_period/baseline.json"
    facts = raw.read_json(baseline)
    if problem == "hash":
        facts["stock_ranges"]["week"][A] = [["2026-10-16", "2026-10-16"]]
    elif problem == "interval_hole":
        facts["files"] = [
            item for item in facts["files"] if item["period"] != "2026-10-09"
        ]
        facts["range_index_hash"] = digest(
            {key: facts[key] for key in ("files", "stock_ranges")}
        )
    else:
        target = raw.target_path(arguments["root"], "week", "2026-10-02")
        if problem == "missing":
            target.unlink()
        else:
            stamp = target.stat()
            os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1))
    raw.atomic_json(baseline, facts)
    stages = []
    original = raw.execute

    def tracked(*args, **kwargs):
        stages.append(kwargs.get("stage"))
        return original(*args, **kwargs)

    monkeypatch.setattr(raw, "execute", tracked)
    with pytest.raises(ValueError):
        history.run_period(
            **arguments, intent=combined_intent(), transport=combined_source
        )
    assert not {"locate_old_keys", "read_affected_once", "partition_copy"} & set(stages)


def test_new_stock_with_no_old_range_preserves_existing_stocks(tmp_path):
    arguments = bootstrap(tmp_path)
    arguments["listed"] = {A, B, "000003.SZ"}
    intent = {**manual_intent("new-stock"), "codes": ["000003.SZ"]}
    result = history.run_period(
        **arguments,
        intent=intent,
        transport=lambda params: wire([row("000003.SZ", "20261016", value="5")]),
    )
    assert len(result["files"]) == 1
    assert [(r[0], str(r[2])) for r in values(arguments["root"], "2026-10-16")] == [
        (A, "1.0000"),
        (B, "9.0000"),
        ("000003.SZ", "5.0000"),
    ]


def test_pure_period_keeps_invalid_index_but_registers_current_file(tmp_path):
    arguments = bootstrap(tmp_path)
    baseline = arguments["staging"] / "stock_period/baseline.json"
    facts = raw.read_json(baseline)
    facts["range_index_hash"] = "bad-index"
    raw.atomic_json(baseline, facts)
    intent = {**combined_intent("period-only"), "codes": []}
    first = history.run_period(**arguments, intent=intent, transport=combined_source)
    updated = raw.read_json(baseline)
    assert (
        updated["range_index_hash"] == "bad-index"
        and "range_index_version" not in updated
    )
    item = next(item for item in updated["files"] if item["period"] == "2026-10-16")
    assert item["version"] == first["files"][0]["version"]
    second = history.run_period(
        **arguments,
        intent={**intent, "request_id": "period-next"},
        transport=combined_source,
    )
    assert len(second["files"]) == 1


@pytest.mark.parametrize("fault", ["target", "content", "preimage", "hash", "device"])
def test_rename_gap_does_not_claim_bad_target(tmp_path, monkeypatch, fault):
    arguments = bootstrap(tmp_path)
    intent = combined_intent("bad-rename")
    run = (
        arguments["staging"] / "stock_period/runs" / execution_id(intent["request_id"])
    )
    original = raw.atomic_json
    interrupted = []

    def stop(path, item):
        if "committed" in Path(path).parts:
            interrupted.append((Path(path), item))
            raise OSError("cp_failed")
        return original(path, item)

    monkeypatch.setattr(raw, "atomic_json", stop)
    with pytest.raises(OSError):
        history.run_period(**arguments, intent=intent, transport=combined_source)
    monkeypatch.setattr(raw, "atomic_json", original)
    cp, item = interrupted[0]
    target = Path(item["target"])
    if fault == "target":
        target.write_bytes(target.read_bytes())
    elif fault == "content":
        stamp = target.stat()
        payload = target.read_bytes()
        target.write_bytes(b"BAD!" + payload[4:])
        os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    elif fault == "device":
        saved = raw.read_json(run / "manifest.json")
        saved["devices"]["root"] += 1
        original(run / "manifest.json", saved)
    else:
        candidates = raw.read_json(run / "week.candidates.json")
        if fault == "preimage":
            candidates[0].pop("target_preimage")
        else:
            candidates[0]["sha256"] = "0" * 64
        original(run / "week.candidates.json", candidates)
    before = raw.file_version(target)
    with pytest.raises((ValueError, OSError)):
        history.run_period(**arguments, intent=intent, transport=forbidden)
    assert not cp.exists() and raw.file_version(target) == before


def test_history_scope_is_frozen_and_current_configuration_conflicts_reject(tmp_path):
    arguments = bootstrap(tmp_path)
    intent = manual_intent("frozen-scope")
    history.run_period(**arguments, intent=intent, transport=combined_source)
    work = history.frozen_history_work(arguments["root"], arguments["staging"], intent)
    assert work["listed"] == [A, B]
    with pytest.raises(ValueError, match="period_manifest_changed"):
        history.frozen_history_work(
            arguments["root"], arguments["staging"], {**intent, "codes": [B]}
        )
    wrong_root = arguments["root"].parent / "other-lake"
    with pytest.raises(ValueError, match="period_manifest_changed"):
        history.frozen_history_work(wrong_root, arguments["staging"], intent)


def test_minimal_history_daily_is_not_a_handoff_and_sensor_skips(tmp_path, monkeypatch):
    from datetime import datetime
    from types import SimpleNamespace as NS

    arguments = bootstrap(tmp_path)
    history.run_period(**arguments, intent=manual_intent(), transport=combined_source)
    monkeypatch.setattr(update, "calendar_days", forbidden)
    monkeypatch.setattr(update, "_daily_work", forbidden)
    with pytest.raises(ValueError, match="period_daily_handoff_required"):
        update.execute_daily(
            **arguments, today=date(2026, 10, 19), freq="week", transport=forbidden
        )
    context = NS(instance=NS(get_runs=lambda **kwargs: []))
    result = update.evaluate_daily_sensor(
        context,
        datetime.fromisoformat("2026-10-19T20:00:00+08:00"),
        freq="week",
        staging_root=arguments["staging"],
    )
    assert result.skip_reason is not None and not result.run_requests


def test_missing_history_range_evidence_refuses_before_old_read(tmp_path, monkeypatch):
    from tests.test_stock_period_raw import sample

    stages = []
    original = raw.execute
    monkeypatch.setattr(
        raw,
        "execute",
        lambda *args, **kwargs: (
            stages.append(kwargs.get("stage")),
            original(*args, **kwargs),
        )[1],
    )
    with pytest.raises(ValueError, match="period_history_range_unverified"):
        raw.assemble(
            [sample(tmp_path / "source", [row(A, "20261016")])],
            work=tmp_path / "build",
            root=tmp_path / "lake",
            mode="history",
            freq="week",
            codes=[A],
            policy=history.DEFAULT_POLICY,
        )
    assert not {"locate_old_keys", "read_affected_once", "partition_copy"} & set(stages)


def test_superseded_code_old_only_rows_are_removed(tmp_path):
    arguments = bootstrap(tmp_path)
    replacement = "000003.SZ"
    arguments.update(
        listed={B, replacement}, aliases={A: replacement, replacement: replacement}
    )
    intent = {
        **manual_intent("superseded"),
        "codes": [replacement],
        "superseded_codes": [A],
    }
    history.run_period(
        **arguments,
        intent=intent,
        transport=lambda params: wire([row(replacement, "20261016", value="5")]),
    )
    assert [(r[0], str(r[2])) for r in values(arguments["root"], "2026-10-02")] == [
        (B, "9.0000")
    ]
    assert [(r[0], str(r[2])) for r in values(arguments["root"], "2026-10-16")] == [
        (B, "9.0000"),
        (replacement, "5.0000"),
    ]


@pytest.mark.parametrize("count", [2, 100])
def test_range_selection_never_stats_unselected_files(tmp_path, monkeypatch, count):
    from datetime import timedelta

    root = tmp_path / "lake"
    periods = [
        (date(2026, 1, 2) + timedelta(weeks=index)).isoformat()
        for index in range(count)
    ]
    files = [
        {
            "freq": "week",
            "period": period,
            "target": str(raw.target_path(root, "week", period)),
            "version": [1, index + 100, 100, 200, 300],
            "rows": 1,
        }
        for index, period in enumerate(periods)
    ]
    facts = {
        "files": files,
        "stock_ranges": {"week": {A: [[periods[0], periods[1]]]}},
        "listed": [A],
        "range_index_version": VERSION,
    }
    facts["range_index_hash"] = digest(
        {key: facts[key] for key in ("files", "stock_ranges")}
    )
    unselected = {item["target"] for item in files[2:]}
    original_stat = Path.stat

    def tracked(path, *args, **kwargs):
        assert str(path) not in unselected
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", tracked)
    monkeypatch.setattr(Path, "glob", forbidden)
    monkeypatch.setattr(raw, "file_version", forbidden)
    assert raw._old_range_paths(root, "week", {A}, facts) == [
        (files[0]["target"], periods[0]),
        (files[1]["target"], periods[1]),
    ]


def test_actual_sdk_history_asset_reuses_original_scope_and_finishes_native_checks(
    tmp_path, monkeypatch
):
    from orchestrator.defs import paths
    from orchestrator.defs.assets import stock_monthly, stock_weekly
    from orchestrator.defs.checks import stock_weekly_checks
    from orchestrator.defs.jobs import stock_weekly as weekly_jobs
    from orchestrator.defs.resources import LakeRootResource
    from orchestrator.defs.run_contracts.stock_weekly import (
        StockWeeklySource,
        weekly_check_names,
    )
    from tests.test_stock_period_recovery import daily_source

    arguments = bootstrap(tmp_path)
    intent = {**manual_intent("sdk-original-history"), "frequencies": ["week", "month"]}
    first = history.run_period(**arguments, intent=intent, transport=daily_source)
    original_versions = {item["target"]: item["version"] for item in first["files"]}
    monkeypatch.setattr(paths, "DEFAULT_LAKE_STAGING_ROOT", str(arguments["staging"]))
    monkeypatch.setattr(LakeRootResource, "ensure_available_for_run", lambda self: None)
    monkeypatch.setattr(history, "load_scope", forbidden)
    monkeypatch.setattr(history, "HttpPage", forbidden)
    definitions = dg.Definitions(
        assets=[
            stock_weekly.raw_tushare_stk_period_bar_adj_week,
            stock_monthly.raw_tushare_stk_period_bar_adj_month,
        ],
        asset_checks=[
            getattr(stock_weekly_checks, name)
            for name in weekly_check_names(StockWeeklySource.PRIMARY_ADJUSTED)
        ],
        jobs=[weekly_jobs.raw_stk_period_bar_adj_week_update_job],
        resources={"lake_root": LakeRootResource(root_path=str(arguments["root"]))},
    )
    instance_path = tmp_path / "sdk-instance"
    instance_path.mkdir()
    (instance_path / "dagster.yaml").write_text("telemetry:\n  enabled: false\n")
    configuration = {
        "ops": {
            "raw_tushare_stk_period_bar_adj_week": {
                "config": {
                    "intent": "history",
                    "stock_codes": [A],
                    "request_id": intent["request_id"],
                }
            }
        }
    }
    with dg.DagsterInstance.local_temp(str(instance_path)) as instance:
        instance.add_dynamic_partitions("cn_a_stock_week_ends", ["2026-10-16"])
        job = definitions.resolve_job_def("raw_stk_period_bar_adj_week_update_job")
        result = job.execute_in_process(
            instance=instance, partition_key="2026-10-16", run_config=configuration
        )
        assert result.success
        assert len(result.get_asset_check_evaluations()) == 3
        # The next execution continues the same request; today's scope/source
        # are forbidden, even though this is a new physical Dagster run.
        repeated = job.execute_in_process(
            instance=instance, partition_key="2026-10-16", run_config=configuration
        )
        assert repeated.success
        assert not raw.read_json(arguments["staging"] / "stock_period/daily.json")[
            "pending_work"
        ]
        bad_config = {
            "ops": {
                "raw_tushare_stk_period_bar_adj_week": {
                    "config": {
                        "intent": "history",
                        "stock_codes": [B],
                        "request_id": intent["request_id"],
                    }
                }
            }
        }
        bad = job.execute_in_process(
            instance=instance,
            partition_key="2026-10-16",
            run_config=bad_config,
            raise_on_error=False,
        )
        assert not bad.success
    assert all(
        raw.file_version(path) == version for path, version in original_versions.items()
    )


@pytest.mark.parametrize("stage", ["phase", "pending"])
def test_history_ack_interruption_keeps_exact_progress(tmp_path, monkeypatch, stage):
    from tests.test_stock_period_delivery_confirmation import _emit

    arguments = bootstrap(tmp_path)
    result = history.run_period(
        **arguments, intent=manual_intent("ack-gap"), transport=combined_source
    )
    run = Path(result["path"])
    state_path = arguments["staging"] / "stock_period/daily.json"
    instance_path = tmp_path / "ack-instance"
    instance_path.mkdir()
    (instance_path / "dagster.yaml").write_text("telemetry:\n  enabled: false\n")
    original = update.atomic_json
    interrupted = []

    def stop(path, payload):
        original(path, payload)
        selected = run / "manifest.json" if stage == "phase" else state_path
        if Path(path) == selected and not interrupted:
            interrupted.append(str(path))
            raise OSError("after_control_write")

    with dg.DagsterInstance.local_temp(str(instance_path)) as instance:
        _emit(instance, result)
        confirmation = lambda path: update.confirm_period_delivery(
            instance, path, root=arguments["root"], staging=arguments["staging"]
        )
        monkeypatch.setattr(update, "atomic_json", stop)
        with pytest.raises(OSError, match="after_control_write"):
            history.replay_events(
                run,
                root=arguments["root"],
                staging=arguments["staging"],
                confirm_delivery=confirmation,
            )
        monkeypatch.setattr(update, "atomic_json", original)
        history.replay_events(
            run,
            root=arguments["root"],
            staging=arguments["staging"],
            confirm_delivery=confirmation,
        )
    assert interrupted and raw.read_json(state_path) == {"pending_work": {}}
    assert all(
        raw.file_version(item["target"]) == item["version"] for item in result["files"]
    )


def test_explicit_old_manifest_is_registered_before_later_pending_is_considered(
    tmp_path,
):
    arguments = bootstrap(tmp_path)
    first_intent = manual_intent("old-unregistered")
    cancelled = []
    with pytest.raises(raw.PeriodCancelled):
        history.run_period(
            **arguments,
            intent=first_intent,
            transport=combined_source,
            progress=lambda event: (
                cancelled.append(True)
                if event["stage"] == "source_unit_complete"
                else None
            ),
            cancel=lambda: bool(cancelled),
        )
    first = {
        "path": str(
            arguments["staging"]
            / "stock_period/runs"
            / execution_id(first_intent["request_id"])
        )
    }
    state_path = arguments["staging"] / "stock_period/daily.json"
    # Deliberate pre-fix state: this exact old manifest exists, but was not queued.
    raw.atomic_json(state_path, {"pending_work": {}})
    later = {**first_intent, "request_id": "later-pending"}
    identity = {
        "intent": later,
        "policy": arguments["policy"].payload(),
        "listed": sorted(arguments["listed"]),
        "aliases": {},
        "root": str(arguments["root"]),
    }
    work = history.ensure_history_pending(
        arguments["staging"] / "stock_period/runs" / execution_id(later["request_id"]),
        root=arguments["root"],
        staging=arguments["staging"],
        identity=identity,
    )
    saved = raw.read_json(Path(first["path"]) / "manifest.json")
    assert saved["started_at"] < work["started_at"]
    history.run_period(**arguments, intent=first_intent, transport=forbidden)
    ordered = history.ordered_pending_work(arguments["staging"])
    assert [item["intent"]["request_id"] for item in ordered] == [
        "old-unregistered",
        "later-pending",
    ]


def test_handoff_blocks_history_before_calendar_and_preserves_queue(
    tmp_path, monkeypatch
):
    from tests.test_stock_period_delivery_confirmation import _emit

    arguments = bootstrap(tmp_path)
    parent = arguments["staging"] / "stock_period/runs" / execution_id("bootstrap")
    original = {**raw.read_json(parent / "complete.json"), "path": str(parent)}
    instance_path = tmp_path / "handoff-instance"
    instance_path.mkdir()
    (instance_path / "dagster.yaml").write_text("telemetry:\n  enabled: false\n")
    with dg.DagsterInstance.local_temp(str(instance_path)) as instance:
        _emit(instance, original)
        # Existing fixture notification CPs are explicit callback substitutes;
        # remove only those private test CPs before binding actual SDK events.
        for cp in (parent / "events/completion").glob("*.json"):
            cp.unlink()
        confirmation = lambda path: update.confirm_period_delivery(
            instance, path, root=arguments["root"], staging=arguments["staging"]
        )
        history.replay_events(
            parent,
            root=arguments["root"],
            staging=arguments["staging"],
            confirm_delivery=confirmation,
        )
        history.run_period(
            **arguments,
            intent=manual_intent("handoff-blocker"),
            transport=combined_source,
        )
        state_path = arguments["staging"] / "stock_period/daily.json"
        before = state_path.read_bytes()
        monkeypatch.setattr(update, "calendar_days", forbidden)
        monkeypatch.setattr(update, "factor_changes", forbidden)
        with pytest.raises(ValueError, match="period_original_run_required"):
            update.handoff_bootstrap(
                root=arguments["root"],
                staging=arguments["staging"],
                run=parent,
                events=forbidden,
                confirm_delivery=confirmation,
            )
        assert state_path.read_bytes() == before


def test_handoff_final_state_preserves_newly_registered_history(tmp_path, monkeypatch):
    from tests.test_stock_period_handoff import captured, options
    from tests.test_stock_period_recovery import daily_source

    arguments, parent, _ = captured(tmp_path, monkeypatch)
    state_path = arguments["staging"] / "stock_period/daily.json"
    original_watermarks = update.bootstrap_watermarks
    registered = []

    def record_after_child(today, days):
        result = original_watermarks(today, days)
        intent = manual_intent("registered-before-state-write")
        identity = {
            "intent": intent,
            "policy": arguments["policy"].payload(),
            "listed": sorted(arguments["listed"]),
            "aliases": {},
            "root": str(arguments["root"]),
        }
        registered.append(
            history.ensure_history_pending(
                arguments["staging"]
                / "stock_period/runs"
                / execution_id(intent["request_id"]),
                root=arguments["root"],
                staging=arguments["staging"],
                identity=identity,
            )
        )
        return result

    def source(params):
        if params["freq"] == "month":
            return wire(
                [row(A, "20261031", "month", "3")]
                + ([] if "ts_code" in params else [row(B, "20261031", "month", "9")])
            )
        return daily_source(params)

    monkeypatch.setattr(update, "bootstrap_watermarks", record_after_child)
    result = update.handoff_bootstrap(
        **options(arguments, parent),
        transport=source,
        events=lambda item, **kwargs: True,
        completion_events=lambda notice: 1,
    )
    # Metadata-only registration at the last state boundary exercises preservation;
    # native event correctness is covered by the actual SDK history test above.
    key = execution_id("registered-before-state-write")
    assert result["pending_work"] == {key: registered[0]}
    assert raw.read_json(state_path)["pending_work"] == {key: registered[0]}


def test_unregistered_files_complete_history_is_queued_before_range_recovery(tmp_path, monkeypatch):
    arguments = bootstrap(tmp_path)
    intent = manual_intent("range-recovery-gap")
    baseline = arguments["staging"] / "stock_period/baseline.json"
    previous_baseline = baseline.read_bytes()
    result = history.run_period(**arguments, intent=intent, transport=combined_source)
    run = Path(result["path"])
    saved = raw.read_json(run / "manifest.json")
    original_started = saved["started_at"]
    # Reproduce the pre-fix control boundary: files and complete are durable,
    # but the range record and manual pending registration did not finish.
    saved["ranges_recorded"] = False
    raw.atomic_json(run / "manifest.json", saved)
    baseline.write_bytes(previous_baseline)
    state_path = arguments["staging"] / "stock_period/daily.json"
    raw.atomic_json(state_path, {"pending_work": {}})
    before = {item["target"]: raw.file_version(item["target"]) for item in result["files"]}
    record_ranges = history._record_ranges
    monkeypatch.setattr(history, "_record_ranges", lambda *args: (_ for _ in ()).throw(OSError("range_write_failed")))
    with pytest.raises(OSError, match="range_write_failed"):
        history.run_period(**arguments, intent=intent, transport=forbidden)
    pending = raw.read_json(state_path)["pending_work"][run.name]
    assert pending["kind"] == "history" and pending["started_at"] == original_started
    assert baseline.read_bytes() == previous_baseline
    with pytest.raises(ValueError, match="period_original_run_required"):
        history.run_period(**arguments, intent=manual_intent("must-wait-for-ranges"), transport=forbidden)
    monkeypatch.setattr(history, "_record_ranges", record_ranges)
    monkeypatch.setattr(history, "assemble", forbidden)
    monkeypatch.setattr(raw, "execute", forbidden)
    resumed = history.run_period(**arguments, intent=intent, transport=forbidden)
    assert resumed["files"] == result["files"]
    assert raw.read_json(run / "manifest.json")["ranges_recorded"] is True
    assert raw.read_json(state_path)["pending_work"][run.name] == pending
    assert all(raw.file_version(path) == version for path, version in before.items())


def test_history_pending_atomic_write_failure_precedes_manifest_and_source(tmp_path, monkeypatch):
    arguments = bootstrap(tmp_path)
    intent = manual_intent("registration-write-fails")
    run = arguments["staging"] / "stock_period/runs" / execution_id(intent["request_id"])
    state_path = arguments["staging"] / "stock_period/daily.json"
    original = history.atomic_json
    attempted = []
    def fail_registration(path, payload):
        attempted.append(str(path))
        if Path(path) == state_path:
            raise OSError("pending_write_failed")
        return original(path, payload)
    monkeypatch.setattr(history, "atomic_json", fail_registration)
    monkeypatch.setattr(history, "assemble", forbidden)
    monkeypatch.setattr(raw, "execute", forbidden)
    with pytest.raises(OSError, match="pending_write_failed"):
        history.run_period(**arguments, intent=intent, transport=forbidden)
    assert attempted == [str(state_path)]
    assert not state_path.exists() and not (run / "manifest.json").exists()


def test_multiple_rename_gaps_across_frequencies_do_not_hash_or_write_cp(tmp_path, monkeypatch):
    arguments = bootstrap(tmp_path)
    intent = {**combined_intent("two-frequency-gaps"), "frequencies": ["week", "month"],
              "periods": {"week": ["2026-10-16"], "month": ["2026-10"]}}
    original_publish = history.publish
    def source(params):
        if params["freq"] == "month":
            return wire([row(A, "20261031", "month", "3")] + ([] if "ts_code" in params else [row(B, "20261031", "month", "9")]))
        return combined_source(params)
    monkeypatch.setattr(history, "publish", lambda *args, **kwargs: (_ for _ in ()).throw(raw.PeriodCancelled("before_first_publish")))
    with pytest.raises(raw.PeriodCancelled, match="before_first_publish"):
        history.run_period(**arguments, intent=intent, transport=source)
    run = arguments["staging"] / "stock_period/runs" / execution_id(intent["request_id"])
    moved = []
    # Deliberately invalid interruption pattern: one writer cannot leave two
    # cross-frequency rename gaps. Both candidate lists are genuine producers.
    for freq in ("week", "month"):
        item = raw.read_json(run / (freq + ".candidates.json"))[0]
        os_replace(item["candidate"], item["target"])
        cp = run / "committed" / freq / (item["period"] + ".json")
        moved.append((item["target"], raw.file_version(item["target"]), cp))
    monkeypatch.setattr(history, "publish", original_publish)
    monkeypatch.setattr(raw, "file_digest", forbidden)
    monkeypatch.setattr(raw, "atomic_json", forbidden)
    with pytest.raises(ValueError, match="period_multiple_unrecorded_promotions"):
        history.run_period(**arguments, intent=intent, transport=forbidden)
    assert all(not cp.exists() and raw.file_version(path) == version for path, version, cp in moved)
