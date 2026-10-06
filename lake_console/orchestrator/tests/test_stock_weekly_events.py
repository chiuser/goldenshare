"""Offline event tests: isolated instance and temporary files only."""

import dagster as dg
import pytest

from orchestrator.defs.bootstrap import stock_weekly_events as events
from orchestrator.defs.bootstrap.stock_weekly_candidates import fingerprint
from orchestrator.defs.bootstrap.stock_weekly_capture import WeeklyCaptureError
from orchestrator.defs.run_contracts.stock_weekly import (
    StockWeeklySource,
    stable_weekly_hash,
)


def entry(tmp_path):
    from orchestrator.defs.bootstrap.stock_weekly_event_files import (
        audit_weekly_event_files,
    )
    from orchestrator.defs.stock_weekly_point import deliver_stock_weekly_point

    from .test_stock_weekly_definitions import frame_for

    source = StockWeeklySource.PRIMARY_UNADJUSTED
    result = deliver_stock_weekly_point(
        source,
        "2020-02-28",
        target_root=tmp_path / "lake",
        staging_root=tmp_path / "stage",
        worker=None,
        fetch=lambda *args: frame_for(source),
    )
    path = __import__("pathlib").Path(result["audit_path"])
    return audit_weekly_event_files([{"path": str(path), "sha256": fingerprint(path)}])[
        0
    ]


def apply_all(instance, plan, tmp_path):
    for stage in ("register", "materializations", "checks"):
        events.apply_weekly_events(
            instance, plan, stage=stage, checkpoint=tmp_path / "checkpoint.json"
        )


def test_partition_target_readback_and_idempotent_replay(tmp_path):
    e = entry(tmp_path)
    with dg.DagsterInstance.ephemeral() as instance:
        plan = events.freeze_weekly_event_plan(
            instance, [e], instance_identity={"isolated": True}
        )
        assert plan["counts"]["materializations"] == 1
        assert plan["counts"]["checks"] == 3
        apply_all(instance, plan, tmp_path)
        after = events.freeze_weekly_event_plan(
            instance, [e], instance_identity={"isolated": True}
        )
        assert after["counts"]["materializations"] == after["counts"]["checks"] == 0
        assert events.audit_weekly_readiness_samples(instance, [e])[0]["ready"]
        for stage in ("register", "materializations", "checks"):
            assert (
                events.apply_weekly_events(
                    instance, plan, stage=stage, checkpoint=tmp_path / "checkpoint.json"
                )["writes"]
                == 0
            )


def test_committed_event_survives_checkpoint_failure(tmp_path, monkeypatch):
    e = entry(tmp_path)
    with dg.DagsterInstance.ephemeral() as instance:
        plan = events.freeze_weekly_event_plan(instance, [e], instance_identity={})
        events.apply_weekly_events(
            instance, plan, stage="register", checkpoint=tmp_path / "checkpoint.json"
        )
        real = events._atomic_json
        monkeypatch.setattr(
            events,
            "_atomic_json",
            lambda *args: (_ for _ in ()).throw(OSError("checkpoint unavailable")),
        )
        with pytest.raises(OSError):
            events.apply_weekly_events(
                instance,
                plan,
                stage="materializations",
                checkpoint=tmp_path / "checkpoint.json",
            )
        monkeypatch.setattr(events, "_atomic_json", real)
        assert (
            events.apply_weekly_events(
                instance,
                plan,
                stage="materializations",
                checkpoint=tmp_path / "checkpoint.json",
            )["writes"]
            == 0
        )
        events.apply_weekly_events(
            instance, plan, stage="checks", checkpoint=tmp_path / "checkpoint.json"
        )


def test_mutated_file_and_plan_are_rejected(tmp_path):
    e = entry(tmp_path)
    with dg.DagsterInstance.ephemeral() as instance:
        plan = events.freeze_weekly_event_plan(instance, [e], instance_identity={})
        plan["entries"][0]["rows"] = 2
        with pytest.raises(WeeklyCaptureError, match="event_plan_hash_mismatch"):
            events.apply_weekly_events(
                instance,
                plan,
                stage="register",
                checkpoint=tmp_path / "checkpoint.json",
            )
        plan = events.freeze_weekly_event_plan(instance, [e], instance_identity={})
        Path = __import__("pathlib").Path
        Path(e["path"]).write_bytes(b"changed")
        with pytest.raises(WeeklyCaptureError, match="event_formal_evidence_changed"):
            events.apply_weekly_events(
                instance,
                plan,
                stage="register",
                checkpoint=tmp_path / "checkpoint.json",
            )
        assert instance.get_dynamic_partitions("cn_a_stock_week_ends") == []


def test_external_new_materialization_stops_checks(tmp_path):
    e = entry(tmp_path)
    with dg.DagsterInstance.ephemeral() as instance:
        plan = events.freeze_weekly_event_plan(instance, [e], instance_identity={})
        events.apply_weekly_events(
            instance, plan, stage="register", checkpoint=tmp_path / "checkpoint.json"
        )
        events.apply_weekly_events(
            instance,
            plan,
            stage="materializations",
            checkpoint=tmp_path / "checkpoint.json",
        )
        instance.report_runless_asset_event(
            dg.AssetMaterialization(asset_key=events._asset(e), partition=e["week"])
        )
        with pytest.raises(WeeklyCaptureError, match="event_materialization_changed"):
            events.apply_weekly_events(
                instance, plan, stage="checks", checkpoint=tmp_path / "checkpoint.json"
            )


def test_cancel_and_duplicate_scope(tmp_path):
    e = entry(tmp_path)
    with dg.DagsterInstance.ephemeral() as instance:
        with pytest.raises(WeeklyCaptureError, match="event_entry_duplicate"):
            events.freeze_weekly_event_plan(instance, [e, e], instance_identity={})
        plan = events.freeze_weekly_event_plan(instance, [e], instance_identity={})
        with pytest.raises(WeeklyCaptureError):
            events.apply_weekly_events(
                instance,
                plan,
                stage="register",
                checkpoint=tmp_path / "checkpoint.json",
                cancel=lambda: True,
            )
        assert instance.get_dynamic_partitions("cn_a_stock_week_ends") == []


def test_record_budget_fails_closed(tmp_path):
    e = entry(tmp_path)
    with dg.DagsterInstance.ephemeral() as instance:
        plan = events.freeze_weekly_event_plan(instance, [e], instance_identity={})
        apply_all(instance, plan, tmp_path)
        with pytest.raises(WeeklyCaptureError, match="event_record_read_cap_exceeded"):
            events.read_weekly_event_state(instance, [e], record_cap=1)


def test_frozen_scope_cannot_add_unknown_check(tmp_path):
    e = entry(tmp_path)
    with dg.DagsterInstance.ephemeral() as instance:
        plan = events.freeze_weekly_event_plan(instance, [e], instance_identity={})
        plan["entries"][0]["missing_checks"].append("unknown")
        plan["plan_hash"] = stable_weekly_hash(
            {k: v for k, v in plan.items() if k != "plan_hash"}
        )
        with pytest.raises(WeeklyCaptureError, match="event_check_scope_invalid"):
            events.verify_weekly_event_plan(plan)


def test_explicit_batch_selector_cannot_bypass_limits(tmp_path):
    e = entry(tmp_path)
    with dg.DagsterInstance.ephemeral() as instance:
        plan = events.freeze_weekly_event_plan(instance, [e], instance_identity={})
        for start, count in ((-1, 1), (0, 101), (0, 0)):
            with pytest.raises(WeeklyCaptureError, match="event_batch_scope_invalid"):
                events.apply_weekly_events(
                    instance,
                    plan,
                    stage="register",
                    checkpoint=tmp_path / "c.json",
                    start=start,
                    count=count,
                )
        assert instance.get_dynamic_partitions("cn_a_stock_week_ends") == []


def test_check_committed_before_checkpoint_failure_replays_once(tmp_path, monkeypatch):
    e = entry(tmp_path)
    with dg.DagsterInstance.ephemeral() as instance:
        plan = events.freeze_weekly_event_plan(instance, [e], instance_identity={})
        for stage in ("register", "materializations"):
            events.apply_weekly_events(
                instance, plan, stage=stage, checkpoint=tmp_path / "c.json"
            )
        real = events._atomic_json
        monkeypatch.setattr(
            events,
            "_atomic_json",
            lambda *args: (_ for _ in ()).throw(OSError("journal failed")),
        )
        with pytest.raises(OSError):
            events.apply_weekly_events(
                instance, plan, stage="checks", checkpoint=tmp_path / "c.json"
            )
        monkeypatch.setattr(events, "_atomic_json", real)
        assert (
            events.apply_weekly_events(
                instance, plan, stage="checks", checkpoint=tmp_path / "c.json"
            )["writes"]
            == 2
        )
        assert (
            events.freeze_weekly_event_plan(instance, [e], instance_identity={})[
                "counts"
            ]["checks"]
            == 0
        )


def test_historical_failed_check_is_counted(tmp_path):
    from dagster._core.definitions.asset_checks.asset_check_evaluation import (
        AssetCheckEvaluation,
    )

    e = entry(tmp_path)
    with dg.DagsterInstance.ephemeral() as instance:
        instance.report_runless_asset_event(
            AssetCheckEvaluation(
                asset_key=events._asset(e),
                check_name=events.weekly_check_names(StockWeeklySource(e["source"]))[0],
                partition=e["week"],
                passed=False,
                blocking=True,
            )
        )
        plan = events.freeze_weekly_event_plan(instance, [e], instance_identity={})
        assert plan["counts"]["historical_latest_failed"] == 1
        assert plan["counts"]["blocked_checks"] == 1
        with pytest.raises(
            WeeklyCaptureError, match="event_existing_check_requires_review"
        ):
            apply_all(instance, plan, tmp_path)
        assert instance.get_dynamic_partitions("cn_a_stock_week_ends") == []


def test_stable_materialization_cursor_is_required(tmp_path):
    from types import SimpleNamespace

    e = entry(tmp_path)

    class Stuck:
        def fetch_materializations(self, *args, **kwargs):
            return SimpleNamespace(records=[], has_more=True, cursor="stuck")

    with pytest.raises(WeeklyCaptureError, match="event_cursor_not_advancing"):
        events.read_weekly_event_state(Stuck(), [e])


def test_cli_rejects_unapproved_write_before_instance_open(tmp_path, monkeypatch):
    from orchestrator.defs.bootstrap import stock_weekly_events_cli as cli

    with dg.DagsterInstance.ephemeral() as instance:
        plan = events.freeze_weekly_event_plan(
            instance, [entry(tmp_path)], instance_identity={}
        )
    path = tmp_path / "plan.json"
    __import__("json").dump(plan, path.open("w"))
    monkeypatch.setattr(
        cli,
        "open_weekly_event_instance",
        lambda **kwargs: pytest.fail("instance opened before apply guard"),
    )
    with pytest.raises(SystemExit) as error:
        cli.main(
            [
                "--mode",
                "checks",
                "--plan",
                str(path),
                "--report",
                str(tmp_path / "report.json"),
            ]
        )
    assert error.value.code == 2


def test_new_event_helpers_do_not_reintroduce_deep_history_or_discovery():
    import ast
    from pathlib import Path

    root = Path(events.__file__).parent
    for name in (
        "stock_weekly_events.py",
        "stock_weekly_events_cli.py",
        "stock_weekly_event_files.py",
        "stock_weekly_event_instance.py",
    ):
        text = (root / name).read_text()
        ast.parse(text)
        for forbidden in (
            "get_asset_check_execution_history",
            "DagsterInstance.get(",
            "DagsterInstance.from_ref(",
            "should_autocreate_tables=True",
            "kopia",
            "old_lake_root",
        ):
            assert forbidden not in text


def test_source_receipt_changed_after_freeze_stops_apply(tmp_path):
    import json
    from pathlib import Path

    e = entry(tmp_path)
    with dg.DagsterInstance.ephemeral() as instance:
        plan = events.freeze_weekly_event_plan(instance, [e], instance_identity={})
        audit = json.loads(Path(e["audit_path"]).read_text())
        source = Path(audit["source_evidence"][0]["path"])
        source.write_bytes(source.read_bytes() + b"changed")
        with pytest.raises(WeeklyCaptureError, match="delivery_evidence_changed"):
            events.apply_weekly_events(
                instance, plan, stage="register", checkpoint=tmp_path / "c.json"
            )
        assert instance.get_dynamic_partitions("cn_a_stock_week_ends") == []


def test_forged_business_identity_rejected_even_with_recomputed_plan_hash(tmp_path):
    e = entry(tmp_path)
    with dg.DagsterInstance.ephemeral() as instance:
        plan = events.freeze_weekly_event_plan(instance, [e], instance_identity={})
        plan["entries"][0]["rows"] += 1
        plan["plan_hash"] = stable_weekly_hash(
            {k: v for k, v in plan.items() if k != "plan_hash"}
        )
        with pytest.raises(WeeklyCaptureError, match="event_audit_entry_mismatch"):
            events.apply_weekly_events(
                instance, plan, stage="register", checkpoint=tmp_path / "c.json"
            )
        assert instance.get_dynamic_partitions("cn_a_stock_week_ends") == []


def test_finished_bootstrap_checks_survive_removed_proofs(tmp_path):
    import shutil
    from types import SimpleNamespace

    from orchestrator.defs.checks import stock_weekly_checks as checks
    from orchestrator.defs.resources import LakeRootResource
    from orchestrator.defs.run_contracts.stock_weekly import (
        weekly_check_names,
    )
    from orchestrator.defs.stock_weekly_update_state import weekly_period_status

    e = entry(tmp_path)
    source = StockWeeklySource(e["source"])
    check_defs = [getattr(checks, name) for name in weekly_check_names(source)]
    with dg.DagsterInstance.ephemeral() as instance:
        plan = events.freeze_weekly_event_plan(
            instance, [e], instance_identity={"isolated": True}
        )
        apply_all(instance, plan, tmp_path)
        assert (
            weekly_period_status(instance, tmp_path / "lake", source, e["week"])
            == "ready"
        )
        shutil.rmtree(tmp_path / "stage")
        check_context = SimpleNamespace(instance=instance, partition_key=e["week"])
        for definition in check_defs:
            result = definition.node_def.compute_fn.decorated_fn(
                check_context, LakeRootResource(root_path=str(tmp_path / "lake"))
            )
            assert result.passed
        assert (
            weekly_period_status(instance, tmp_path / "lake", source, e["week"])
            == "ready"
        )
