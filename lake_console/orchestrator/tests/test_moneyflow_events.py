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

from orchestrator.defs.asset_guards.moneyflow_readiness import (
    batch_stock_moneyflow_readiness,
)
from orchestrator.defs.bootstrap import moneyflow_event_plan as planner
from orchestrator.defs.bootstrap import moneyflow_history_events as writer
from orchestrator.defs.bootstrap.moneyflow_event_preview import (
    read_stock_moneyflow_event_state,
)
from orchestrator.defs.bootstrap.moneyflow_events import (
    report_stock_moneyflow_history_events,
)
from orchestrator.defs.bootstrap.moneyflow_history_cohort import _large_json
from orchestrator.defs.bootstrap.moneyflow_stock_event_plan import (
    build_stock_moneyflow_event_plan,
)
from orchestrator.defs.io.moneyflow_candidates import moneyflow_writer_lock
from orchestrator.defs.partitions import cn_a_moneyflow_trade_days
from orchestrator.defs.paths import raw_moneyflow_path
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_MAX_RSS_BYTES,
    MoneyflowContractError,
    moneyflow_peak_rss_bytes,
)
from orchestrator.defs.run_contracts.moneyflow_automation import (
    STOCK_MONEYFLOW_AUTOMATION as CONTRACT,
)

from .test_moneyflow_history_promote import (
    DAY,
    Source,
    hashes,
    operation,
    run,
    setup,
)


def stock_rows(days=(DAY,), *, first_count=5572):
    fixture = json.loads(Path("tests/fixtures/moneyflow_20260930.json").read_text())
    return [
        {**r, "trade_date": day}
        for i, day in enumerate(days)
        for r in fixture[: first_count if i == 0 else 5572]
    ]


@pytest.fixture
def environment(tmp_path):
    rows = Source().rows
    rows["moneyflow"] = stock_rows()
    staging, lake, source = setup(tmp_path, rows)
    assert run(staging, lake, apply=True)["stage"] == "files_complete"
    home = tmp_path / "instance"
    home.mkdir()
    with dg.DagsterInstance.local_temp(
        str(home), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        plan = build_plan(instance, staging, lake)
        yield instance, plan, source


def build_plan(instance, staging, lake, **kwargs):
    return build_stock_moneyflow_event_plan(
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
    return read_stock_moneyflow_event_state(
        instance, plan["entries"], plan["recent_check_dates"]
    )


def execute(instance, plan, **kwargs):
    return report_stock_moneyflow_history_events(instance=instance, plan=plan, **kwargs)


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
    readiness = batch_stock_moneyflow_readiness(
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
            ("raw_tushare_moneyflow", CONTRACT.raw_check),
            ("silver_moneyflow", CONTRACT.silver_check),
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
            and key.asset_key == dg.AssetKey("silver_moneyflow")
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
            plan,
            entry,
            layer,
            writer._path(plan, entry, layer),
            record,
            contract=CONTRACT,
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
        from orchestrator.defs.bootstrap.moneyflow_event_preview import (
            read_stock_moneyflow_event_state,
        )

        with pytest.raises(MoneyflowContractError, match="record_limit"):
            read_stock_moneyflow_event_state(
                instance, [entry, {**entry, "day": "2026-09-29"}], []
            )
        return
    with pytest.raises(MoneyflowContractError):
        execute(instance, plan, apply=True)
    assert not instance.get_dynamic_partitions(cn_a_moneyflow_trade_days.name)
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
from orchestrator.defs.bootstrap import moneyflow_history_events as writer
from orchestrator.defs.bootstrap.moneyflow_events import report_stock_moneyflow_history_events
plan = json.loads(Path(sys.argv[1]).read_text())
original = writer._atomic_json
def save(path, payload, **kwargs):
    if path.name == "checkpoint.json" and payload["written_events_this_attempt"] == 1:
        os._exit(47)
    original(path, payload, **kwargs)
writer._atomic_json = save
with dg.DagsterInstance.get() as instance:
    report_stock_moneyflow_history_events(instance=instance, plan=plan, apply=True)
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
        path = raw_moneyflow_path(Path(plan["lake_root"]), "moneyflow", DAY)
        path.write_bytes(path.read_bytes() + b"changed")
    elif kind == "control":
        path = Path(next(iter(plan["controls"])))
        path.write_bytes(path.read_bytes() + b"changed")
    elif kind == "active":
        instance.create_run_for_job(
            dg.define_asset_job("raw_tushare_moneyflow_update_job").resolve(
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
        dg.AssetKey("raw_tushare_moneyflow"), limit=100
    ).records
    assert not instance.get_dynamic_partitions(cn_a_moneyflow_trade_days.name)


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
    # 2040 events + ten partition batches + twenty-one batch readbacks +
    # frozen plan, initial progress and final progress = 2074 atomic saves.
    [(1000, 3040, 2040, 251, 2074), (4067, 12241, 8174, 953, 8313)],
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
    rows["moneyflow"] = [
        {**Source.row("moneyflow"), "trade_date": d} for d in days[:-20]
    ] + stock_rows(days[-20:])
    staging, lake, source = setup(tmp_path, rows)
    assert run(staging, lake, apply=True)["stage"] == "files_complete"
    home = tmp_path / "instance"
    home.mkdir()
    with dg.DagsterInstance.local_temp(
        str(home), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        from orchestrator.defs.bootstrap.moneyflow_stock_event_plan import (
            build_stock_moneyflow_event_plans,
        )

        plans = build_stock_moneyflow_event_plans(
            instance=instance,
            staging_root=staging,
            lake_root=lake,
            operation_id="cohort",
            cutoff=DAY,
            expected_cohort_hash=_large_json(operation(staging) / "cohort.json")[
                "cohort_hash"
            ],
        )
        plan = {
            **plans[0],
            "entries": [e for item in plans for e in item["entries"]],
            "recent_check_dates": [
                d for item in plans for d in item["recent_check_dates"]
            ],
        }
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
        unit_results = [execute(instance, item, apply=True) for item in plans]
        assert all(
            r["stage"] == "complete"
            and r["metadata_reads"] <= 256
            and r["total"] <= 4096
            for r in unit_results
        )
        result = {
            "stage": "complete",
            **{
                key: sum(r[key] for r in unit_results)
                for key in (
                    "total",
                    "completed",
                    "written_events_this_attempt",
                    "registered_keys_this_attempt",
                    "metadata_reads",
                )
            },
        }
        applied_saves = tuple(saves)
        assert result["total"] == result["completed"] == work_items
        assert result["written_events_this_attempt"] == event_count
        assert result["registered_keys_this_attempt"] == date_count
        assert result["metadata_reads"] == read_count and max(batches) == 100
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
        capacity = {
            "scope": "isolated SQLite/P3 files: synthetic date scope, older one-row days and recent20 archived5572-row fixture days; not formal source histories",
            "unit_results": unit_results,
            "dates": date_count,
            "rows": date_count - 20 + 20 * 5572,
            "result": result,
            "read_batch_sizes": sorted(set(batches)),
            "atomic_control_saves": len(applied_saves),
            "atomic_control_save_seconds": sum(applied_saves),
            "max_atomic_control_save_seconds": max(applied_saves),
            "process_peak_rss_bytes": moneyflow_peak_rss_bytes(),
        }
        (tmp_path / f"stock-moneyflow-event-capacity-{date_count}.json").write_text(
            json.dumps(capacity, indent=2)
        )
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


def test_stock_native_metadata_uses_frozen_per_day_counts_and_real_columns(tmp_path):
    rows = Source().rows
    days = ("2026-09-29", DAY)
    rows["moneyflow"] = stock_rows(days, first_count=5571)
    staging, lake, source = setup(tmp_path, rows)
    assert run(staging, lake, apply=True)["stage"] == "files_complete"
    home = tmp_path / "instance"
    home.mkdir()
    with dg.DagsterInstance.local_temp(
        str(home), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        plan = build_plan(instance, staging, lake)
        assert [e["row_count"] for e in plan["entries"]] == [5571, 5572]
        before = physical(plan), source.calls
        result = execute(instance, plan, apply=True)
        assert result["total"] == result["completed"] == 10
        native = state(instance, plan)
        for entry in plan["entries"]:
            for layer in ("raw", "silver"):
                mat = native["mats"][(entry["day"], layer)]
                metadata = mat.asset_materialization.metadata
                assert metadata["dagster/row_count"].value == entry["row_count"]
                assert (
                    metadata["goldenshare/source_row_count"].value == entry["row_count"]
                )
                assert len(metadata["goldenshare/observed_columns"].value) == 20
                assert metadata["goldenshare/observed_columns"].value == [
                    "ts_code",
                    "trade_date",
                    "buy_sm_vol",
                    "buy_sm_amount",
                    "sell_sm_vol",
                    "sell_sm_amount",
                    "buy_md_vol",
                    "buy_md_amount",
                    "sell_md_vol",
                    "sell_md_amount",
                    "buy_lg_vol",
                    "buy_lg_amount",
                    "sell_lg_vol",
                    "sell_lg_amount",
                    "buy_elg_vol",
                    "buy_elg_amount",
                    "sell_elg_vol",
                    "sell_elg_amount",
                    "net_mf_vol",
                    "net_mf_amount",
                ]
                assert "scope_row_counts" not in entry
                assert "goldenshare/scope_row_counts" not in metadata
                check = native["checks"][
                    (entry["day"], layer)
                ].event.dagster_event.event_specific_data
                assert (
                    check.partition == entry["day"] and check.passed and check.blocking
                )
                assert (
                    check.metadata["goldenshare/checked_row_count"].value
                    == entry["row_count"]
                )
                assert "goldenshare/scope_row_counts" not in check.metadata
                assert check.target_materialization_data.storage_id == mat.storage_id
                assert (
                    check.target_materialization_data.run_id
                    == mat.event_log_entry.run_id
                )
                assert check.target_materialization_data.timestamp == mat.timestamp
        assert instance.get_dynamic_partitions("cn_a_moneyflow_mkt_dc_trade_days") == []
        assert set(instance.get_asset_keys()) == {
            dg.AssetKey(CONTRACT.raw_asset),
            dg.AssetKey(CONTRACT.silver_asset),
        }
        assert before == (physical(plan), source.calls)
        replay = execute(instance, plan, apply=True)
        assert (
            replay["written_events_this_attempt"]
            == replay["registered_keys_this_attempt"]
            == 0
        )
        (tmp_path / "stock-moneyflow-two-day-sample.json").write_text(
            json.dumps(
                {
                    "scope": "isolated SQLite; archived Sep30 fixture copied to two synthetic dates, first truncated5571 vs5572; not formal sourceSep29 values",
                    "days": list(days),
                    "row_counts": [e["row_count"] for e in plan["entries"]],
                    "result": result,
                    "replay": replay,
                    "fields": 20,
                    "rejects": 0,
                    "physical_unchanged": True,
                    "source_calls_during_events": 0,
                    "native_materializations": len(native["mats"]),
                    "native_checks": len(native["checks"]),
                },
                indent=2,
            )
        )


@pytest.mark.parametrize("bad", [None, 1, 0, 5573, "5572", 5572.0, True])
def test_rehashed_false_stock_counts_cannot_be_registered(environment, bad):
    from orchestrator.defs.bootstrap.moneyflow_history_plan import _hash

    instance, plan, _ = environment
    changed = copy.deepcopy(plan)
    if bad is None:
        del changed["entries"][0]["row_count"]
    else:
        changed["entries"][0]["row_count"] = bad
    changed["plan_hash"] = _hash({k: v for k, v in changed.items() if k != "plan_hash"})
    with pytest.raises(MoneyflowContractError, match="plan_changed"):
        execute(instance, changed, apply=True)
    assert state(instance, plan)["mats"] == {} and not checkpoint(plan).exists()
    assert instance.get_dynamic_partitions(CONTRACT.partition_set) == []


@pytest.mark.parametrize(
    "other_dataset", ["market", "industry", "concept", "board", "dc_stock", "ths_stock"]
)
def test_other_plans_cannot_cross_bound_stock_entries(environment, other_dataset):
    from orchestrator.defs.bootstrap.moneyflow_cnt_ths_event_plan import (
        build_concept_moneyflow_ths_event_plan,
    )
    from orchestrator.defs.bootstrap.moneyflow_cnt_ths_events import (
        report_concept_moneyflow_ths_history_events,
    )
    from orchestrator.defs.bootstrap.moneyflow_dc_event_plan import (
        build_stock_moneyflow_dc_event_plan,
    )
    from orchestrator.defs.bootstrap.moneyflow_dc_events import (
        report_stock_moneyflow_dc_history_events,
    )
    from orchestrator.defs.bootstrap.moneyflow_ind_dc_event_plan import (
        build_board_moneyflow_dc_event_plan,
    )
    from orchestrator.defs.bootstrap.moneyflow_ind_dc_events import (
        report_board_moneyflow_dc_history_events,
    )
    from orchestrator.defs.bootstrap.moneyflow_ind_ths_event_plan import (
        build_industry_moneyflow_ths_event_plan,
    )
    from orchestrator.defs.bootstrap.moneyflow_ind_ths_events import (
        report_industry_moneyflow_ths_history_events,
    )
    from orchestrator.defs.bootstrap.moneyflow_mkt_dc_event_plan import (
        build_market_moneyflow_event_plan,
    )
    from orchestrator.defs.bootstrap.moneyflow_mkt_dc_events import (
        report_market_moneyflow_history_events,
    )
    from orchestrator.defs.bootstrap.moneyflow_ths_event_plan import (
        build_stock_moneyflow_ths_event_plan,
    )
    from orchestrator.defs.bootstrap.moneyflow_ths_events import (
        report_stock_moneyflow_ths_history_events,
    )

    instance, plan, _ = environment
    build, report = {
        "market": (
            build_market_moneyflow_event_plan,
            report_market_moneyflow_history_events,
        ),
        "industry": (
            build_industry_moneyflow_ths_event_plan,
            report_industry_moneyflow_ths_history_events,
        ),
        "concept": (
            build_concept_moneyflow_ths_event_plan,
            report_concept_moneyflow_ths_history_events,
        ),
        "board": (
            build_board_moneyflow_dc_event_plan,
            report_board_moneyflow_dc_history_events,
        ),
        "dc_stock": (
            build_stock_moneyflow_dc_event_plan,
            report_stock_moneyflow_dc_history_events,
        ),
        "ths_stock": (
            build_stock_moneyflow_ths_event_plan,
            report_stock_moneyflow_ths_history_events,
        ),
    }[other_dataset]
    other = build(
        instance=instance,
        staging_root=Path(plan["staging_root"]),
        lake_root=Path(plan["lake_root"]),
        operation_id=plan["operation_id"],
        cutoff=plan["cutoff"],
        expected_cohort_hash=plan["cohort_hash"],
    )
    assert other["plan_hash"] != plan["plan_hash"]
    with pytest.raises(MoneyflowContractError, match="history_event_dataset"):
        execute(instance, other, apply=True)
    with pytest.raises(MoneyflowContractError, match="history_event_dataset"):
        report(instance=instance, plan=plan, apply=True)
    assert not checkpoint(plan).exists() and instance.get_asset_keys() == []


def test_row_count_audit_mismatch_does_not_publish_green_checks(
    environment, monkeypatch
):
    instance, plan, _ = environment
    original = writer.audit_moneyflow_automation_standardization

    def wrong_count(*args):
        return original(*args) + 1

    monkeypatch.setattr(
        writer, "audit_moneyflow_automation_standardization", wrong_count
    )
    with pytest.raises(MoneyflowContractError, match="history_event_row_count"):
        execute(instance, plan, apply=True)
    actual = state(instance, plan)
    assert len(actual["mats"]) == 2 and actual["checks"] == {}
    monkeypatch.setattr(writer, "audit_moneyflow_automation_standardization", original)
    assert execute(instance, plan, apply=True)["written_events_this_attempt"] == 2


@pytest.mark.parametrize("kind", ["materialization", "source_row_count", "check"])
def test_native_wrong_row_counts_are_not_reused_or_overwritten(environment, kind):
    instance, plan, _ = environment
    entry = plan["entries"][0]
    path = writer._path(plan, entry, "raw")
    event = writer._materialization(plan, entry, "raw", path)
    if kind in {"materialization", "source_row_count"}:
        key = (
            "dagster/row_count"
            if kind == "materialization"
            else "goldenshare/source_row_count"
        )
        event = event._replace(
            metadata={**event.metadata, key: dg.MetadataValue.int(1)}
        )
    instance.report_runless_asset_event(event)
    mat = instance.fetch_materializations(event.asset_key, limit=1).records[0]
    if kind == "check":
        check = writer._evaluation(plan, entry, "raw", path, mat, contract=CONTRACT)
        instance.report_runless_asset_event(
            writer.AssetCheckEvaluation(
                asset_key=check.asset_key,
                check_name=check.check_name,
                partition=check.partition,
                passed=check.passed,
                blocking=check.blocking,
                severity=check.severity,
                target_materialization_data=check.target_materialization_data,
                metadata={
                    **check.metadata,
                    "goldenshare/checked_row_count": dg.MetadataValue.int(1),
                },
            )
        )
    with pytest.raises(
        MoneyflowContractError, match="history_event_existing_row_count"
    ):
        execute(instance, plan, apply=True)
    assert (
        not checkpoint(plan).exists()
        and instance.get_dynamic_partitions(CONTRACT.partition_set) == []
    )
    assert state(instance, plan)["mats"][(DAY, "raw")].storage_id == mat.storage_id


@pytest.mark.parametrize(
    "date_count,expected",
    [
        (999, [999]),
        (1000, [1000]),
        (1001, [1000, 1]),
        (4067, [1000, 1000, 1000, 1000, 67]),
    ],
)
def test_full_plan_segments_share_one_proof_and_cover_every_source_date(
    environment, monkeypatch, date_count, expected
):
    import orchestrator.defs.bootstrap.moneyflow_stock_event_plan as stock_planner

    instance, original, _ = environment
    days = [
        (date(2010, 1, 4) + timedelta(days=i)).isoformat() for i in range(date_count)
    ]
    entry = original["entries"][0]
    proof = {
        "entries": [{**entry, "day": day} for day in days],
        "recent_check_dates": days[-20:],
        "cohort_hash": original["cohort_hash"],
        "cutoff": original["cutoff"],
        "controls": original["controls"],
    }
    seen = []

    def frozen_proof(**kwargs):
        seen.append(kwargs)
        return proof

    monkeypatch.setattr(stock_planner, "stock_moneyflow_history_proof", frozen_proof)
    plans = stock_planner.build_stock_moneyflow_event_plans(
        instance=instance,
        staging_root=Path(original["staging_root"]),
        lake_root=Path(original["lake_root"]),
        operation_id=original["operation_id"],
        cutoff=original["cutoff"],
        expected_cohort_hash=original["cohort_hash"],
    )
    assert len(seen) == 1 and [len(p["entries"]) for p in plans] == expected
    assert [e["day"] for p in plans for e in p["entries"]] == days
    assert len({p["plan_hash"] for p in plans}) == len(plans)
    assert sum(p["total_work_items"] for p in plans) == 3 * date_count + 40
    assert [d for p in plans for d in p["recent_check_dates"]] == days[-20:]
    assert all(
        p["controls"] == original["controls"]
        and p["instance_identity"] == original["instance_identity"]
        and p["dataset"] == "moneyflow"
        for p in plans
    )
    assert all(
        p["total_work_items"] <= 4096 and p["limits"] == original["limits"]
        for p in plans
    )
    if date_count == 4067:
        with pytest.raises(MoneyflowContractError, match="history_event_write_budget"):
            planner._assemble(
                proof,
                staging_root=Path(original["staging_root"]),
                lake_root=Path(original["lake_root"]),
                operation_id=original["operation_id"],
                identity=original["instance_identity"],
                contract=CONTRACT,
            )


def test_segment_constant_keeps_all_existing_shared_limits():
    from orchestrator.defs.run_contracts import moneyflow as limits

    assert limits.MONEYFLOW_STOCK_EVENT_PLAN_MAX_DATES == 1000
    assert (
        limits.MONEYFLOW_EVENT_DATE_BATCH,
        limits.MONEYFLOW_EVENT_MAX_WRITES,
        limits.MONEYFLOW_EVENT_MAX_SECONDS,
        limits.MONEYFLOW_EVENT_MAX_METADATA_READS,
    ) == (100, 4096, 600, 256)
