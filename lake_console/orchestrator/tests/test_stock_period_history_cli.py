"""Independent bootstrap CLI: no old daily completion notices or shared state."""

import json
from contextlib import contextmanager

import dagster as dg
import pytest

from orchestrator.defs.bootstrap import stock_period_history as history
from orchestrator.defs.bootstrap import stock_period_history_cli as cli
from orchestrator.defs.io import stock_period_raw as raw
from tests.test_stock_period_history import args


def test_prepare_is_readonly_and_apply_requires_explicit_delete(tmp_path, capsys):
    argv = [
        "--lake-root",
        str(tmp_path / "lake"),
        "--staging-root",
        str(tmp_path / "staging"),
        "--request-id",
        "sample",
    ]
    assert (
        cli.main(argv) == 0 and json.loads(capsys.readouterr().out)["applied"] is False
    )
    with pytest.raises(SystemExit):
        cli.main(["apply", *argv])
    assert not (tmp_path / "lake").exists() and not (tmp_path / "staging").exists()


def test_old_actions_and_old_prod_config_rejected():
    from orchestrator.defs.run_contracts.configs import StockPeriodRawConfig

    with pytest.raises(SystemExit):
        cli.main(["handoff"])
    for config in [
        {"delivery_batch_id": "old", "closure_revision": 1},
        {"write_mode": "create_or_identical"},
        {"source": "weekly"},
    ]:
        with pytest.raises(ValueError):
            StockPeriodRawConfig(**config)


def test_events_bind_both_frequencies_recover_missing_only_and_use_four_set_queries(
    tmp_path, monkeypatch
):
    kw = args(tmp_path)
    result = history.run_period(**kw)
    versions = {i["target"]: raw.file_version(i["target"]) for i in result["files"]}
    monkeypatch.setattr(
        history, "run_period", lambda **k: pytest.fail("event replay downloaded")
    )
    monkeypatch.setattr(
        raw, "assemble", lambda *a, **k: pytest.fail("event replay copied")
    )
    monkeypatch.setattr(
        raw, "publish", lambda *a, **k: pytest.fail("event replay replaced")
    )
    statements = []
    queries = history._bootstrap_event_evidence
    with dg.DagsterInstance.ephemeral() as instance:
        monkeypatch.setattr(
            instance,
            "fetch_materializations",
            lambda *a, **k: pytest.fail("per-file lookup"),
        )
        connect = instance.event_log_storage.index_connection

        def counted(*a, **kw):
            @contextmanager
            def connection():
                with connect() as real:

                    class Counted:
                        def execute(self, statement):
                            statements.append(statement)
                            return real.execute(statement)

                    yield Counted()

            with monkeypatch.context() as scoped:
                scoped.setattr(
                    instance.event_log_storage, "index_connection", connection
                )
                return queries(*a, **kw)

        monkeypatch.setattr(history, "_bootstrap_event_evidence", counted)
        report = instance.report_dagster_event
        failed = False

        def interrupt(dagster_event, **kw):
            event = dagster_event
            nonlocal failed
            if (
                event.event_type_value == "ASSET_CHECK_EVALUATION"
                and event.event_specific_data.asset_key.to_user_string().endswith(
                    "month"
                )
                and not failed
            ):
                failed = True
                raise OSError("event interrupted")
            return report(event, **kw)

        monkeypatch.setattr(instance, "report_dagster_event", interrupt)

        def operation(ctx):
            return history.replay_events(
                raw.safe_path(result["path"]),
                root=kw["root"],
                staging=kw["staging"],
                events=lambda files: history.report_bootstrap_events(
                    instance, ctx, files
                ),
            )

        with pytest.raises(Exception, match="event interrupted"):
            cli._run_reporting(instance, operation)
        monkeypatch.setattr(instance, "report_dagster_event", report)
        statements.clear()
        done = cli._run_reporting(instance, operation)
        assert done["events_complete"] and len(statements) == 4
        assert versions == {p: raw.file_version(p) for p in versions}
        counts = {}
        for i in result["files"]:
            evidence = queries(instance, [i])
            entry = evidence[
                (f"raw_tushare_stk_period_bar_adj_{i['freq']}", i["period"])
            ]
            assert len(entry["checks"]) == 3
            assert all(
                c[2].storage_id == entry["materialization"].storage_id
                for c in entry["checks"].values()
            )
            counts[i["freq"]] = entry["materialization"].storage_id
        statements.clear()
        assert (
            cli._run_reporting(instance, operation)["events_complete"]
            and len(statements) == 4
        )
        assert not instance.fetch_observations(
            dg.AssetKey("raw_tushare_stk_period_bar_adj_week"), limit=1
        ).records
    assert not (kw["staging"] / "stock_period/baseline.json").exists()


@pytest.mark.parametrize("fault", ["failed", "wrong_binding", "changed_version"])
def test_bootstrap_existing_bad_evidence_is_not_replaced(tmp_path, fault):
    from dagster._core.definitions.asset_checks.asset_check_evaluation import (
        AssetCheckEvaluation,
        AssetCheckEvaluationTargetMaterializationData,
    )
    from dagster._core.events import DagsterEvent, DagsterEventType

    from orchestrator.defs.asset_guards.stock_period_silver_readiness import (
        raw_check_names,
    )

    kw = args(tmp_path)
    result = history.run_period(**kw)
    files = result["files"]
    with dg.DagsterInstance.ephemeral() as instance:
        cli._run_reporting(
            instance, lambda ctx: history.report_bootstrap_events(instance, ctx, files)
        )
        item = files[0]
        asset = dg.AssetKey(f"raw_tushare_stk_period_bar_adj_{item['freq']}")
        record = instance.fetch_materializations(
            dg.AssetRecordsFilter(asset_key=asset, asset_partitions=[item["period"]]),
            limit=1,
        ).records[0]
        if fault == "changed_version":
            instance.report_runless_asset_event(
                dg.AssetMaterialization(
                    asset_key=asset,
                    partition=item["period"],
                    metadata={"goldenshare/period_file_version": [1, 2, 3, 4, 5]},
                )
            )
        else:

            def bad(ctx):
                target = AssetCheckEvaluationTargetMaterializationData(
                    storage_id=record.storage_id,
                    run_id="wrong"
                    if fault == "wrong_binding"
                    else record.event_log_entry.run_id,
                    timestamp=record.timestamp,
                )
                instance.report_dagster_event(
                    DagsterEvent(
                        event_type_value=DagsterEventType.ASSET_CHECK_EVALUATION.value,
                        job_name=ctx.job_name,
                        step_key=ctx.get_step_execution_context().step.key,
                        event_specific_data=AssetCheckEvaluation(
                            asset_key=asset,
                            partition=item["period"],
                            check_name=raw_check_names(item["freq"])[0],
                            passed=fault != "failed",
                            blocking=True,
                            target_materialization_data=target,
                        ),
                    ),
                    run_id=ctx.run_id,
                )

            cli._run_reporting(instance, bad)
        before = len(
            instance.fetch_materializations(
                dg.AssetRecordsFilter(asset_key=asset), limit=10
            ).records
        )
        with pytest.raises(Exception, match="period_"):
            cli._run_reporting(
                instance,
                lambda ctx: history.report_bootstrap_events(instance, ctx, files),
            )
        assert (
            len(
                instance.fetch_materializations(
                    dg.AssetRecordsFilter(asset_key=asset), limit=10
                ).records
            )
            == before
        )


@pytest.mark.parametrize("phase", ["files_complete", "events_complete"])
def test_apply_after_file_completion_refuses_before_scope_or_deletion(
    tmp_path, monkeypatch, phase
):
    kw = args(tmp_path)
    result = history.run_period(**kw)
    manifest = raw.safe_path(result["path"]) / "manifest.json"
    saved = raw.read_json(manifest)
    # files_complete is the real producer; the phase-only variation verifies
    # the same explicit prohibition after event completion, without fake events.
    saved["phase"] = phase
    raw.atomic_json(manifest, saved)
    versions = {i["target"]: raw.file_version(i["target"]) for i in result["files"]}
    monkeypatch.setattr(
        cli, "load_scope", lambda *a: pytest.fail("completed apply read current scope")
    )
    monkeypatch.setattr(
        cli, "run_period", lambda **k: pytest.fail("completed apply entered writer")
    )
    with pytest.raises(SystemExit) as rejected:
        cli.main(
            [
                "apply",
                "--lake-root",
                str(kw["root"]),
                "--staging-root",
                str(kw["staging"]),
                "--request-id",
                "test",
                "--confirm-delete-existing",
            ]
        )
    assert rejected.value.code == 2
    assert versions == {p: raw.file_version(p) for p in versions}
