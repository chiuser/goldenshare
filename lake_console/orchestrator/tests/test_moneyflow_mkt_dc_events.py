"""Native temporary storage proves resumability; no formal services or source access."""

import copy
import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from time import monotonic

import dagster as dg
import pytest

from orchestrator.defs.asset_guards.moneyflow_mkt_dc_readiness import (
    batch_market_moneyflow_readiness,
)
from orchestrator.defs.bootstrap import moneyflow_mkt_dc_event_plan as planner
from orchestrator.defs.bootstrap import moneyflow_mkt_dc_events as writer
from orchestrator.defs.bootstrap.moneyflow_history_cohort import _large_json
from orchestrator.defs.bootstrap.moneyflow_mkt_dc_event_plan import (
    build_market_moneyflow_event_plan,
)
from orchestrator.defs.bootstrap.moneyflow_mkt_dc_event_preview import (
    read_market_moneyflow_event_state,
)
from orchestrator.defs.io.moneyflow_candidates import moneyflow_writer_lock
from orchestrator.defs.partitions import cn_a_moneyflow_mkt_dc_trade_days
from orchestrator.defs.paths import raw_moneyflow_path
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_MAX_RSS_BYTES,
    MoneyflowContractError,
    moneyflow_peak_rss_bytes,
)

from .test_moneyflow_history_promote import (
    DAY,
    Source,
    hashes,
    operation,
    run,
    setup,
)


@pytest.fixture
def environment(tmp_path):
    staging, lake, source = setup(tmp_path)
    assert run(staging, lake, apply=True)["stage"] == "files_complete"
    home = tmp_path / "instance"
    home.mkdir()
    with dg.DagsterInstance.local_temp(
        str(home), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        plan = build_plan(instance, staging, lake)
        yield instance, plan, source


def build_plan(instance, staging, lake, **kwargs):
    return build_market_moneyflow_event_plan(
        instance=instance,
        staging_root=staging,
        lake_root=lake,
        operation_id="cohort",
        cutoff=DAY,
        expected_cohort_hash=_large_json(operation(staging) / "cohort.json")[
            "cohort_hash"
        ],
        **kwargs,
    )


def checkpoint(plan):
    return (
        Path(plan["staging_root"])
        / "moneyflow/cohort/events"
        / plan["plan_hash"]
        / "checkpoint.json"
    )


def physical(plan):
    return hashes(Path(plan["lake_root"])), {
        p: Path(p).read_bytes() for p in plan["controls"]
    }


def state(instance, plan):
    return read_market_moneyflow_event_state(
        instance, plan["entries"], plan["recent_check_dates"]
    )


def execute(instance, plan, **kwargs):
    return writer.report_market_moneyflow_history_events(
        instance=instance, plan=plan, **kwargs
    )


def test_default_is_read_only_and_plan_identity_excludes_event_ids(environment):
    instance, plan, source = environment
    before = physical(plan), source.calls
    files = {
        p: p.read_bytes() for p in Path(plan["staging_root"]).rglob("*") if p.is_file()
    }
    result = execute(instance, plan)
    assert result["formal_writes"] == 0
    assert result["missing_partition_keys"] == 1
    assert result["missing_materializations"] == result["missing_checks"] == 2
    assert not checkpoint(plan).exists()
    assert files == {
        p: p.read_bytes() for p in Path(plan["staging_root"]).rglob("*") if p.is_file()
    }
    assert "storage_id" not in json.dumps(plan)
    assert not state(instance, plan)["mats"]
    assert before == (physical(plan), source.calls)


def test_native_registration_readiness_and_idempotent_replay(environment):
    instance, plan, source = environment
    before = physical(plan), source.calls
    progress = []
    result = execute(instance, plan, apply=True, progress=progress.append)
    assert result["stage"] == "complete" and result["completed"] == result["total"] == 5
    assert (
        result["written_events_this_attempt"] == 4
        and result["registered_keys_this_attempt"] == 1
    )
    saved = json.loads(checkpoint(plan).read_text())
    assert saved["stage"] == "complete" and saved["percent"] == 100
    assert [p["completed"] for p in progress] == sorted(
        p["completed"] for p in progress
    )
    assert all(p["updated_at"] and p["total"] == 5 for p in progress)
    readiness = batch_market_moneyflow_readiness(
        instance, Path(plan["lake_root"]), [DAY]
    )
    assert all(readiness[layer][DAY].ready for layer in ("raw", "silver"))
    existing = state(instance, plan)
    replay = execute(instance, plan, apply=True)
    assert (
        replay["written_events_this_attempt"]
        == replay["registered_keys_this_attempt"]
        == 0
    )
    assert {k: v.storage_id for k, v in existing["mats"].items()} == {
        k: v.storage_id for k, v in state(instance, plan)["mats"].items()
    }
    assert all(
        len(
            instance.event_log_storage.get_asset_check_execution_history(
                dg.AssetCheckKey(dg.AssetKey(key), check), limit=100
            )
        )
        == 1
        for key, check in (
            ("raw_tushare_moneyflow_mkt_dc", writer.MONEYFLOW_MKT_DC_RAW_CHECK),
            ("silver_moneyflow_mkt_dc", writer.MONEYFLOW_MKT_DC_SILVER_CHECK),
        )
    )
    assert before == (physical(plan), source.calls)


def test_cancel_after_committed_event_resumes_from_native_storage(environment):
    instance, plan, _ = environment
    observed = []

    def cancel():
        return any(p["written_events_this_attempt"] == 1 for p in observed)

    with pytest.raises(MoneyflowContractError, match="history_event_cancelled"):
        execute(instance, plan, apply=True, cancel=cancel, progress=observed.append)
    assert json.loads(checkpoint(plan).read_text())["stage"] == "cancelled"
    assert len(state(instance, plan)["mats"]) == 1
    native_id = state(instance, plan)["mats"][(DAY, "raw")].storage_id
    result = execute(instance, plan, apply=True)
    assert result["written_events_this_attempt"] == 3
    assert state(instance, plan)["mats"][(DAY, "raw")].storage_id == native_id


def test_missing_checkpoint_is_rebuilt_from_native_events(environment):
    instance, plan, _ = environment
    execute(instance, plan, apply=True)
    checkpoint(plan).unlink()  # only this test's temporary observation file
    result = execute(instance, plan, apply=True)
    assert result["completed"] == 5 and result["written_events_this_attempt"] == 0
    assert json.loads(checkpoint(plan).read_text())["stage"] == "complete"


def test_cancellation_during_final_native_read_is_honored(environment, monkeypatch):
    instance, plan, _ = environment
    history = instance.event_log_storage.get_asset_check_execution_history
    observations = []
    cancelled = False

    def read(key, **kwargs):
        nonlocal cancelled
        result = history(key, **kwargs)
        if (
            observations
            and observations[-1]["stage"] == "audit"
            and key.asset_key == dg.AssetKey("silver_moneyflow_mkt_dc")
        ):
            cancelled = True
        return result

    monkeypatch.setattr(
        instance.event_log_storage, "get_asset_check_execution_history", read
    )
    with pytest.raises(MoneyflowContractError, match="history_event_cancelled"):
        execute(
            instance,
            plan,
            apply=True,
            cancel=lambda: cancelled,
            progress=observations.append,
        )
    assert json.loads(checkpoint(plan).read_text())["stage"] == "cancelled"
    monkeypatch.setattr(
        instance.event_log_storage, "get_asset_check_execution_history", history
    )
    assert execute(instance, plan, apply=True)["written_events_this_attempt"] == 0


@pytest.mark.parametrize(
    "kind", ["revision", "upstream", "failed_check", "stale_check", "saturated"]
)
def test_conflicting_native_evidence_cannot_be_overwritten(environment, kind):
    instance, plan, _ = environment
    entry = plan["entries"][0]
    layer = "silver" if kind == "upstream" else "raw"
    event = writer._materialization(
        plan, entry, layer, writer._path(plan, entry, layer)
    )
    if kind in {"revision", "upstream"}:
        metadata = dict(event.metadata)
        metadata[
            "goldenshare/raw_sha256"
            if kind == "upstream"
            else "goldenshare/file_sha256"
        ] = dg.MetadataValue.text("0" * 64)
        event = event._replace(metadata=metadata)
    for _ in range(100 if kind == "saturated" else 1):
        instance.report_runless_asset_event(event)
    record = instance.fetch_materializations(event.asset_key, limit=1).records[0]
    if kind in {"failed_check", "stale_check"}:
        check = writer._evaluation(
            plan, entry, layer, writer._path(plan, entry, layer), record
        )
        target = check.target_materialization_data
        check = writer.AssetCheckEvaluation(
            asset_key=check.asset_key,
            check_name=check.check_name,
            passed=kind != "failed_check",
            partition=check.partition,
            blocking=check.blocking,
            severity=check.severity,
            metadata=check.metadata,
            target_materialization_data=writer.AssetCheckEvaluationTargetMaterializationData(
                storage_id=0 if kind == "stale_check" else target.storage_id,
                run_id=target.run_id,
                timestamp=target.timestamp,
            ),
        )
        instance.report_runless_asset_event(check)
    if kind == "saturated":
        # A second source date cannot be proved by a saturated single-date history.
        from orchestrator.defs.bootstrap.moneyflow_mkt_dc_event_preview import (
            read_market_moneyflow_event_state,
        )

        with pytest.raises(MoneyflowContractError, match="record_limit"):
            read_market_moneyflow_event_state(
                instance, [entry, {**entry, "day": "2026-09-29"}], []
            )
        return
    with pytest.raises(MoneyflowContractError):
        execute(instance, plan, apply=True)
    assert not instance.get_dynamic_partitions(cn_a_moneyflow_mkt_dc_trade_days.name)
    assert (
        instance.fetch_materializations(event.asset_key, limit=1).records[0].storage_id
        == record.storage_id
    )
    assert not checkpoint(plan).exists()


@pytest.mark.parametrize("kind", ["future_counter", "bad_stage", "symlink"])
def test_checkpoint_cannot_claim_uncommitted_work_or_redirect_writes(
    environment, tmp_path, kind
):
    instance, plan, _ = environment
    path = checkpoint(plan)
    path.parent.mkdir(parents=True)
    if kind == "symlink":
        outside = tmp_path / "outside.json"
        outside.write_text("untouched")
        path.symlink_to(outside)
    else:
        path.write_text(
            json.dumps(
                {
                    "plan_hash": plan["plan_hash"],
                    "completed": 5 if kind == "future_counter" else 0,
                    "total": 5,
                    "stage": "invented" if kind == "bad_stage" else "complete",
                }
            )
        )
    with pytest.raises(MoneyflowContractError):
        execute(instance, plan, apply=True)
    assert not state(instance, plan)["mats"]
    if kind == "symlink":
        assert outside.read_text() == "untouched"


def test_actual_process_exit_before_checkpoint_does_not_duplicate_event(
    environment, tmp_path
):
    instance, plan, _ = environment
    plan_file = tmp_path / "child-plan.json"
    plan_file.write_text(json.dumps(plan))
    script = tmp_path / "exit-child.py"
    script.write_text("""import json, os, sys
from pathlib import Path
import dagster as dg
from orchestrator.defs.bootstrap import moneyflow_mkt_dc_events as writer
plan = json.loads(Path(sys.argv[1]).read_text())
original = writer._atomic_json
def save(path, payload, **kwargs):
    if path.name == "checkpoint.json" and payload["written_events_this_attempt"] == 1:
        os._exit(47)
    original(path, payload, **kwargs)
writer._atomic_json = save
with dg.DagsterInstance.get() as instance:
    writer.report_market_moneyflow_history_events(instance=instance, plan=plan, apply=True)
""")
    env = {
        **os.environ,
        "DAGSTER_HOME": str(instance.root_directory),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    result = subprocess.run(
        [sys.executable, "-B", str(script), str(plan_file)],
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 47, result.stderr
    assert len(state(instance, plan)["mats"]) == 1
    assert json.loads(checkpoint(plan).read_text())["written_events_this_attempt"] == 0
    assert execute(instance, plan, apply=True)["written_events_this_attempt"] == 3


def test_checkpoint_failure_preserves_event_and_progress_failure_is_observable(
    environment, monkeypatch, caplog
):
    instance, plan, _ = environment
    original = writer._atomic_json

    def fail(path, payload, **kwargs):
        if (
            path.name == "checkpoint.json"
            and payload["written_events_this_attempt"] == 1
        ):
            raise OSError("isolated checkpoint failure")
        return original(path, payload, **kwargs)

    monkeypatch.setattr(writer, "_atomic_json", fail)
    with pytest.raises(OSError, match="isolated checkpoint failure"):
        execute(instance, plan, apply=True)
    assert len(state(instance, plan)["mats"]) == 1
    assert "终态进度保存失败" in caplog.text
    monkeypatch.setattr(writer, "_atomic_json", original)

    def bad_observer(_):
        raise RuntimeError("isolated observer failure")

    assert (
        execute(instance, plan, apply=True, progress=bad_observer)[
            "written_events_this_attempt"
        ]
        == 3
    )
    assert "进度输出失败" in caplog.text


@pytest.mark.parametrize(
    "kind",
    [
        "plan",
        "file",
        "control",
        "active",
        "lock",
        "apply",
        "instance",
        "checkpoint",
        "oversized_checkpoint",
        "time",
        "reads",
        "cancel",
    ],
)
def test_rejects_unsafe_or_exhausted_execution_before_events(
    environment, monkeypatch, tmp_path, kind
):
    instance, plan, _ = environment
    kwargs = {"apply": True}
    if kind == "plan":
        plan = copy.deepcopy(plan)
        plan["entries"][0]["day"] = "2026-10-01"
    elif kind == "file":
        path = raw_moneyflow_path(Path(plan["lake_root"]), "moneyflow_mkt_dc", DAY)
        path.write_bytes(path.read_bytes() + b"changed")
    elif kind == "control":
        path = Path(next(iter(plan["controls"])))
        path.write_bytes(path.read_bytes() + b"changed")
    elif kind == "active":
        instance.create_run_for_job(
            dg.define_asset_job("raw_tushare_moneyflow_mkt_dc_update_job").resolve(
                dg.Definitions(assets=[]).resolve_asset_graph()
            )
        )
    elif kind == "apply":
        kwargs["apply"] = "false"
    elif kind == "instance":
        home = tmp_path / "other"
        home.mkdir()
        with (
            dg.DagsterInstance.local_temp(
                str(home), overrides={"telemetry": {"enabled": False}}
            ) as other,
            pytest.raises(MoneyflowContractError, match="instance_changed"),
        ):
            execute(other, plan, **kwargs)
        return
    elif kind in {"checkpoint", "oversized_checkpoint"}:
        path = checkpoint(plan)
        path.parent.mkdir(parents=True)
        path.write_text(
            " " * (256 * 1024 + 1)
            if kind == "oversized_checkpoint"
            else json.dumps({"plan_hash": "wrong", "completed": 5})
        )
    elif kind == "time":
        monkeypatch.setattr(writer, "MONEYFLOW_EVENT_MAX_SECONDS", 0)
    elif kind == "reads":
        monkeypatch.setattr(writer, "MONEYFLOW_EVENT_MAX_METADATA_READS", 1)
    elif kind == "cancel":
        kwargs["cancel"] = lambda: True
    if kind == "lock":
        with (
            moneyflow_writer_lock(Path(plan["staging_root"]) / "moneyflow"),
            pytest.raises(MoneyflowContractError),
        ):
            execute(instance, plan, **kwargs)
    else:
        with pytest.raises((MoneyflowContractError, ValueError)):
            execute(instance, plan, **kwargs)
    assert not instance.fetch_materializations(
        dg.AssetKey("raw_tushare_moneyflow_mkt_dc"), limit=100
    ).records
    assert not instance.get_dynamic_partitions(cn_a_moneyflow_mkt_dc_trade_days.name)


@pytest.mark.parametrize("selection", [[], [DAY, DAY], ["2026-10-01"], "2026-09-30"])
def test_selection_cannot_invent_or_duplicate_source_dates(environment, selection):
    instance, plan, _ = environment
    with pytest.raises(MoneyflowContractError, match="history_event_selection"):
        build_plan(
            instance,
            Path(plan["staging_root"]),
            Path(plan["lake_root"]),
            dates=selection,
        )


def test_plan_refuses_work_over_frozen_budget(environment, monkeypatch):
    instance, plan, _ = environment
    monkeypatch.setattr(planner, "MONEYFLOW_EVENT_MAX_WRITES", 4)
    with pytest.raises(MoneyflowContractError, match="write_budget"):
        build_plan(instance, Path(plan["staging_root"]), Path(plan["lake_root"]))
    assert not state(instance, plan)["mats"] and not checkpoint(plan).exists()


@pytest.mark.parametrize(
    ("date_count", "work_items", "event_count", "read_count", "save_count"),
    [(101, 343, 242, 83, 252), (839, 2557, 1718, 229, 1749)],
)
def test_date_batches_and_only_last_20_have_checks(
    tmp_path, monkeypatch, date_count, work_items, event_count, read_count, save_count
):
    # The original small-fixture metadata sink writes once. Real Prod streams
    # bounded chunks; retain the production 64KiB guard for a full-size fixture.
    original_metadata = Source.metadata

    def bounded_metadata(self, request, sink, check):
        class ChunkedSink:
            @staticmethod
            def write(payload):
                for offset in range(0, len(payload), 65536):
                    sink.write(payload[offset : offset + 65536])
                    check()

        return original_metadata(self, request, ChunkedSink(), check)

    monkeypatch.setattr(Source, "metadata", bounded_metadata)
    rows = Source().rows
    days = [
        (date(2026, 9, 30) - timedelta(days=date_count - 1 - i)).isoformat()
        for i in range(date_count)
    ]
    rows["moneyflow_mkt_dc"] = [
        {**Source.row("moneyflow_mkt_dc"), "trade_date": day} for day in days
    ]
    staging, lake, source = setup(tmp_path, rows)
    assert run(staging, lake, apply=True)["stage"] == "files_complete"
    home = tmp_path / "instance"
    home.mkdir()
    with dg.DagsterInstance.local_temp(
        str(home), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        plan = build_plan(instance, staging, lake)
        before = physical(plan), source.calls
        fetch = instance.fetch_materializations
        batches = []
        saves = []
        atomic = writer._atomic_json

        def measured_save(path, payload, **kwargs):
            started = monotonic()
            atomic(path, payload, **kwargs)
            saves.append(monotonic() - started)

        def bounded_query(records_filter, **kwargs):
            batches.append(len(records_filter.asset_partitions))
            assert kwargs["limit"] == 100
            return fetch(records_filter, **kwargs)

        monkeypatch.setattr(instance, "fetch_materializations", bounded_query)
        monkeypatch.setattr(writer, "_atomic_json", measured_save)
        result = execute(instance, plan, apply=True)
        applied_saves = tuple(saves)
        assert result["total"] == result["completed"] == work_items
        assert result["written_events_this_attempt"] == event_count
        assert result["registered_keys_this_attempt"] == date_count
        assert result["metadata_reads"] == read_count <= 256 and max(batches) == 100
        assert len(applied_saves) == save_count
        assert plan["recent_check_dates"] == days[-20:]
        actual = state(instance, plan)
        assert len(actual["mats"]) == 2 * date_count and len(actual["checks"]) == 40
        assert all(day in days[-20:] for day, _ in actual["checks"])
        selection = build_plan(instance, staging, lake, dates=[days[0]])
        assert not selection["recent_check_dates"]
        assert (
            execute(instance, selection, apply=True)["written_events_this_attempt"] == 0
        )
        assert before == (physical(plan), source.calls)
        assert moneyflow_peak_rss_bytes() <= MONEYFLOW_MAX_RSS_BYTES
        print(
            json.dumps(
                {
                    "native_sqlite_dates": date_count,
                    "result": result,
                    "read_batch_sizes": sorted(set(batches)),
                    "atomic_control_saves": len(applied_saves),
                    "atomic_control_save_seconds": sum(applied_saves),
                    "max_atomic_control_save_seconds": max(applied_saves),
                    "process_peak_rss_bytes": moneyflow_peak_rss_bytes(),
                }
            )
        )
