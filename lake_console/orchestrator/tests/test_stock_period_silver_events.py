"""Real isolated Dagster event storage, with faults only at the event write."""

from types import SimpleNamespace

import dagster as dg
import pytest
from dagster._core.event_api import PartitionKeyFilter
from dagster._core.storage.asset_check_execution_record import (
    COMPLETED_ASSET_CHECK_EXECUTION_RECORD_STATUSES,
)

from orchestrator.defs import stock_period_silver as silver
from orchestrator.defs.bootstrap import stock_period_silver_cli as cli
from orchestrator.defs.checks import stock_period_silver_checks as checks
from orchestrator.defs.io.stock_period_raw import file_version
from orchestrator.defs.io.stock_period_silver import read_json, run_directory
from orchestrator.defs.run_contracts.stock_period_silver import (
    asset_name,
    check_names,
    target_path,
)
from tests.test_stock_period_silver_contracts import (
    period_fixture as period_fixture,  # noqa: PLC0414 -- Explicit pytest fixture re-export.
)
from tests.test_stock_period_silver_contracts import (
    update_fixture as update_fixture,  # noqa: PLC0414 -- Explicit pytest fixture re-export.
)
from tests.test_stock_period_silver_execution import execute


def emit_test_check(instance, asset, period, name, materialization, *, passed):
    """Deliberately bad evidence, written through real Dagster APIs in an isolated run."""
    from dagster._core.definitions.asset_checks.asset_check_evaluation import (
        AssetCheckEvaluation,
        AssetCheckEvaluationTargetMaterializationData,
    )
    from dagster._core.events import DagsterEvent, DagsterEventType

    def operation(context):
        instance.report_dagster_event(
            DagsterEvent(
                event_type_value=DagsterEventType.ASSET_CHECK_EVALUATION.value,
                job_name=context.job_name,
                step_key=context.get_step_execution_context().step.key,
                event_specific_data=AssetCheckEvaluation(
                    asset_key=dg.AssetKey(asset),
                    check_name=name,
                    partition=period,
                    passed=passed,
                    blocking=True,
                    target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                        storage_id=materialization.storage_id,
                        run_id=materialization.event_log_entry.run_id,
                        timestamp=materialization.event_log_entry.timestamp,
                    ),
                ),
            ),
            run_id=context.run_id,
        )

    cli.run_reporting(instance, operation)


@pytest.mark.parametrize("fault", ["raw_failure", "silver_failure", "wrong_binding"])
def test_update_events_reject_real_failures_before_new_materializations(
    update_fixture, fault
):
    from tests.test_stock_period_silver_execution import capture_history_change, update

    f = update_fixture
    result = update(f, capture_history_change(f))
    raw = fault == "raw_failure"
    asset = "raw_tushare_stk_period_bar_adj_week" if raw else "silver_stock_weekly"
    name = (
        "raw_tushare_stk_period_bar_adj_week_file_contract_check"
        if raw
        else check_names("week")[0]
    )
    bound = "2014-01-03" if fault == "wrong_binding" else "2020-04-03"
    mat = (
        f["instance"]
        .fetch_materializations(
            dg.AssetRecordsFilter(
                asset_key=dg.AssetKey(asset), asset_partitions=[bound]
            ),
            limit=1,
        )
        .records[0]
    )
    emit_test_check(
        f["instance"], asset, "2020-04-03", name, mat, passed=fault == "wrong_binding"
    )
    before = (
        f["instance"]
        .fetch_materializations(
            dg.AssetRecordsFilter(asset_key=dg.AssetKey("silver_stock_weekly")),
            limit=20,
        )
        .records
    )
    with pytest.raises(ValueError, match="checks_not_ready"):
        cli.run_reporting(
            f["instance"],
            lambda ctx: cli.replay_events(
                f["lake"], f["staging"], result["run_id"], f["instance"], ctx
            ),
        )
    after = (
        f["instance"]
        .fetch_materializations(
            dg.AssetRecordsFilter(asset_key=dg.AssetKey("silver_stock_weekly")),
            limit=20,
        )
        .records
    )
    assert [r.storage_id for r in after] == [r.storage_id for r in before]


def test_update_event_receipt_failure_reads_back_actual_events_without_duplicates(
    update_fixture, monkeypatch
):
    from tests.test_stock_period_silver_execution import capture_history_change, update

    f = update_fixture
    result = update(f, capture_history_change(f))
    original, armed = cli.atomic_json, [True]

    def fail(path, value):
        if armed[0] and "events/week" in str(path):
            armed[0] = False
            raise OSError("receipt unavailable")
        return original(path, value)

    with monkeypatch.context() as patch:
        patch.setattr(cli, "atomic_json", fail)
        with pytest.raises(OSError, match="receipt unavailable"):
            cli.run_reporting(
                f["instance"],
                lambda ctx: cli.replay_events(
                    f["lake"], f["staging"], result["run_id"], f["instance"], ctx
                ),
            )
    monkeypatch.setattr(
        silver,
        "connect_configured_duckdb",
        lambda *a, **k: pytest.fail("events computed"),
    )
    complete = cli.run_reporting(
        f["instance"],
        lambda ctx: cli.replay_events(
            f["lake"], f["staging"], result["run_id"], f["instance"], ctx
        ),
    )
    assert complete["status"] == "complete"
    for period in ("2014-01-03", "2020-04-03", "2026-10-16"):
        mats = (
            f["instance"]
            .fetch_materializations(
                dg.AssetRecordsFilter(
                    asset_key=dg.AssetKey("silver_stock_weekly"),
                    asset_partitions=[period],
                ),
                limit=10,
            )
            .records
        )
        assert len(mats) == 2


def test_partial_ancestor_coverage_can_finish_without_recomputing(
    update_fixture, monkeypatch
):
    from tests.test_stock_period_silver_execution import (
        interrupted_update,
        refresh_recovery_tail,
    )

    f = update_fixture
    old_id, _, committed = interrupted_update(f, monkeypatch)
    refresh_recovery_tail(f)
    result = silver.build(
        f["lake"], f["staging"], old_id, instance=f["instance"], emit=lambda _: None
    )
    actual_id = result["run_id"]
    original = cli.atomic_json
    parent_work = run_directory(f["staging"], old_id)

    def fail(path, value):
        if path == parent_work / "events/week/2020-04-03.json":
            raise OSError("ancestor acknowledgement failed")
        return original(path, value)

    with monkeypatch.context() as patch:
        patch.setattr(cli, "atomic_json", fail)
        with pytest.raises(OSError, match="ancestor acknowledgement failed"):
            cli.run_reporting(
                f["instance"],
                lambda ctx: cli.replay_events(
                    f["lake"], f["staging"], actual_id, f["instance"], ctx
                ),
            )
    assert not (parent_work / "events_complete.json").exists()
    monkeypatch.setattr(
        silver,
        "connect_configured_duckdb",
        lambda *a, **k: pytest.fail("coverage recomputed"),
    )
    partial = cli.run_reporting(
        f["instance"],
        lambda ctx: cli.replay_events(
            f["lake"], f["staging"], old_id, f["instance"], ctx
        ),
    )
    assert partial["status"] == "partial" and partial["files"] == 2
    complete = cli.run_reporting(
        f["instance"],
        lambda ctx: cli.replay_events(
            f["lake"], f["staging"], actual_id, f["instance"], ctx
        ),
    )
    assert complete["status"] == "complete"
    assert (
        read_json(parent_work / "events_complete.json")["covered_by_execution_id"]
        == actual_id
    )
    assert all(file_version(r["target"]) == r["version"] for r in committed)


@pytest.mark.parametrize(
    "fault", ["upstream_failure", "target_failure", "wrong_binding"]
)
def test_update_rejects_real_failed_or_wrong_bound_checks_before_files(
    update_fixture, fault
):
    from tests.test_stock_period_silver_execution import capture_history_change, update

    f = update_fixture
    reference = capture_history_change(f)
    paths = [
        target_path(f["lake"], "week", p)
        for p in ("2014-01-03", "2020-04-03", "2026-10-16")
    ]
    versions = [file_version(p) for p in paths]
    asset = (
        "silver_stock_weekly"
        if fault == "target_failure"
        else "raw_tushare_stk_period_bar_adj_week"
    )
    name = (
        "silver_stock_weekly_file_contract_check"
        if fault == "target_failure"
        else "raw_tushare_stk_period_bar_adj_week_file_contract_check"
    )
    bound_period = "2014-01-03" if fault == "wrong_binding" else "2020-04-03"
    materialization = (
        f["instance"]
        .fetch_materializations(
            dg.AssetRecordsFilter(
                asset_key=dg.AssetKey(asset), asset_partitions=[bound_period]
            ),
            limit=1,
        )
        .records[0]
    )
    emit_test_check(
        f["instance"],
        asset,
        "2020-04-03",
        name,
        materialization,
        passed=fault == "wrong_binding",
    )
    with pytest.raises(ValueError, match="checks_not_ready"):
        update(f, reference)
    assert [file_version(p) for p in paths] == versions


def test_update_event_failure_resumes_events_only_and_does_not_duplicate_materializations(
    update_fixture, monkeypatch
):
    from tests.test_stock_period_silver_execution import capture_history_change, update

    f = update_fixture
    result = update(f, capture_history_change(f))
    run_id = result["run_id"]
    paths = [
        target_path(f["lake"], "week", p)
        for p in ("2014-01-03", "2020-04-03", "2026-10-16")
    ]
    versions = [file_version(p) for p in paths]
    calls = len(f["source_calls"])
    monkeypatch.setattr(
        silver,
        "connect_configured_duckdb",
        lambda *a, **k: pytest.fail("events recomputed file"),
    )
    original = f["instance"].report_dagster_event
    armed = [True]

    def fault(*args, **kwargs):
        event = args[0] if args else kwargs["dagster_event"]
        if (
            armed[0]
            and getattr(event.event_specific_data, "check_name", None)
            == check_names("week")[1]
        ):
            armed[0] = False
            raise OSError("update event failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(f["instance"], "report_dagster_event", fault)
    with pytest.raises(OSError, match="update event failure"):
        cli.run_reporting(
            f["instance"],
            lambda context: cli.replay_events(
                f["lake"], f["staging"], run_id, f["instance"], context
            ),
        )
    assert [file_version(p) for p in paths] == versions
    monkeypatch.setattr(f["instance"], "report_dagster_event", original)
    result = cli.run_reporting(
        f["instance"],
        lambda context: cli.replay_events(
            f["lake"], f["staging"], run_id, f["instance"], context
        ),
    )
    assert result["files"] == 3 and result["checks"] == 9
    assert [file_version(p) for p in paths] == versions
    assert len(f["source_calls"]) == calls
    for period in ("2014-01-03", "2020-04-03", "2026-10-16"):
        mats = (
            f["instance"]
            .fetch_materializations(
                dg.AssetRecordsFilter(
                    asset_key=dg.AssetKey("silver_stock_weekly"),
                    asset_partitions=[period],
                ),
                limit=10,
            )
            .records
        )
        assert (
            len(mats) == 2
        )  # one real baseline and one changed file, even across event failure
        for name in check_names("week"):
            record = f["instance"].event_log_storage.get_asset_check_execution_history(
                dg.AssetCheckKey(dg.AssetKey("silver_stock_weekly"), name),
                limit=1,
                partition_filter=PartitionKeyFilter(key=period),
            )[0]
            assert record.evaluation.passed and record.evaluation.blocking
            assert (
                record.evaluation.target_materialization_data.storage_id
                == mats[0].storage_id
            )


def test_same_source_and_reference_versions_reuse_already_validated_silver(
    update_fixture, monkeypatch
):
    from tests.test_stock_period_silver_execution import update

    f = update_fixture
    paths = [
        target_path(f["lake"], "week", p)
        for p in ("2014-01-03", "2020-04-03", "2026-10-16")
    ]
    versions = [file_version(p) for p in paths]
    monkeypatch.setattr(
        silver,
        "connect_configured_duckdb",
        lambda *a, **k: pytest.fail("same version recomputed"),
    )
    result = update(f, f["base_reference"])
    assert result["totals"]["week"] == {"files": 3, "rows": 6}
    assert [file_version(p) for p in paths] == versions


@pytest.mark.parametrize("freq", ["week", "month"])
def test_partial_update_events_do_not_need_batch_complete_or_compute(
    update_fixture, monkeypatch, freq
):
    from tests.test_stock_period_silver_execution import interrupted_update

    f = update_fixture
    run_id, _, committed = interrupted_update(f, monkeypatch, freq)
    work = run_directory(f["staging"], run_id)
    assert not (work / "complete.json").exists()
    monkeypatch.setattr(
        silver,
        "connect_configured_duckdb",
        lambda *a, **k: pytest.fail("partial events computed"),
    )
    source_count = len(f["source_calls"])
    result = cli.run_reporting(
        f["instance"],
        lambda context: cli.replay_events(
            f["lake"], f["staging"], run_id, f["instance"], context
        ),
    )
    assert result["files"] == 2 and result["checks"] == 6
    assert result["status"] == "partial"
    assert len(result["pending_files"]) == 1
    assert not (work / "events_complete.json").exists()
    assert all(file_version(r["target"]) == r["version"] for r in committed)
    again = cli.run_reporting(
        f["instance"],
        lambda context: cli.replay_events(
            f["lake"], f["staging"], run_id, f["instance"], context
        ),
    )
    assert again["files"] == 2
    for record in committed:
        mats = (
            f["instance"]
            .fetch_materializations(
                dg.AssetRecordsFilter(
                    asset_key=dg.AssetKey(asset_name(freq)),
                    asset_partitions=[record["period"]],
                ),
                limit=10,
            )
            .records
        )
        assert (
            len(mats) == 2
        )  # real baseline and one changed file, no replay duplication
    assert len(f["source_calls"]) == source_count


def test_event_failure_resumes_without_sql_or_file_changes(period_fixture, monkeypatch):
    f = period_fixture
    execute(f)
    versions = {
        str(target_path(f["lake"], freq, period)): file_version(
            target_path(f["lake"], freq, period)
        )
        for freq, period in f["data"]
    }
    # No generation, COPY, source projection or DuckDB connection is allowed in events.
    monkeypatch.setattr(
        silver,
        "connect_configured_duckdb",
        lambda *a, **k: pytest.fail("events computed data"),
    )
    with dg.DagsterInstance.ephemeral() as instance:
        original = instance.report_dagster_event
        armed = [True]

        def fault(*args, **kwargs):
            event = args[0] if args else kwargs["dagster_event"]
            evaluation = event.event_specific_data
            if (
                armed[0]
                and getattr(evaluation, "check_name", None) == check_names("week")[1]
            ):
                armed[0] = False
                raise OSError("injected event failure")
            return original(*args, **kwargs)

        monkeypatch.setattr(instance, "report_dagster_event", fault)
        with pytest.raises(OSError, match="injected event failure"):
            cli.run_reporting(
                instance,
                lambda context: cli.replay_events(
                    f["lake"], f["staging"], f["run_id"], instance, context
                ),
            )
        monkeypatch.setattr(instance, "report_dagster_event", original)
        result = cli.run_reporting(
            instance,
            lambda context: cli.replay_events(
                f["lake"], f["staging"], f["run_id"], instance, context
            ),
        )
        assert result["materializations"] == 6 and result["checks"] == 18
        counts = {}
        for freq, period in f["data"]:
            asset = dg.AssetKey(asset_name(freq))
            materializations = instance.fetch_materializations(
                dg.AssetRecordsFilter(asset_key=asset, asset_partitions=[period]),
                limit=10,
            ).records
            assert len(materializations) == 1
            for name in check_names(freq):
                history = instance.event_log_storage.get_asset_check_execution_history(
                    dg.AssetCheckKey(asset, name),
                    limit=10,
                    status=COMPLETED_ASSET_CHECK_EXECUTION_RECORD_STATUSES,
                    partition_filter=PartitionKeyFilter(key=period),
                )
                assert len(history) == 1
                evaluation = history[0].evaluation
                assert (
                    evaluation.passed
                    and evaluation.blocking
                    and evaluation.partition == period
                )
                assert (
                    evaluation.asset_key == asset
                    and evaluation.target_materialization_data.storage_id
                    == materializations[0].storage_id
                )
                assert instance.get_run_by_id(history[0].run_id) is not None
                counts[(freq, period, name)] = history[0].id
        # A repeat acknowledges already registered facts, with no duplicate events.
        cli.run_reporting(
            instance,
            lambda context: cli.replay_events(
                f["lake"], f["staging"], f["run_id"], instance, context
            ),
        )
        assert all(file_version(path) == version for path, version in versions.items())
        assert len(counts) == 18


def test_standalone_checks_need_no_bootstrap_receipt_and_share_one_validation(
    period_fixture, monkeypatch
):
    f = period_fixture
    execute(f)
    with dg.DagsterInstance.ephemeral() as instance:
        cli.run_reporting(
            instance,
            lambda context: cli.replay_events(
                f["lake"], f["staging"], f["run_id"], instance, context
            ),
        )
        calls = []
        original = silver.select_period

        def tracked(*args, **kwargs):
            calls.append(1)
            return original(*args, **kwargs)

        monkeypatch.setattr(silver, "select_period", tracked)
        # Check path uses current files and materialization metadata, not execution.json.
        monkeypatch.setattr(
            silver,
            "load_execution",
            lambda *a, **k: pytest.fail("bootstrap proof dependency"),
        )
        silver._VALIDATED.clear()
        ctx = SimpleNamespace(instance=instance, partition_key="2020-02")
        for kind in ("file_contract", "key_partition", "source_projection"):
            assert checks.evaluate(ctx, f["lake"], f["staging"], "month", kind).passed
        assert len(calls) == 1
        record = instance.fetch_materializations(
            dg.AssetRecordsFilter(
                asset_key=dg.AssetKey("silver_stock_monthly"),
                asset_partitions=["2020-02"],
            ),
            limit=1,
        ).records[0]
        metadata = {k: v for k, v in record.asset_materialization.metadata.items()}
        metadata["dagster/row_count"] = 999
        instance.report_runless_asset_event(
            dg.AssetMaterialization(
                asset_key="silver_stock_monthly", partition="2020-02", metadata=metadata
            )
        )
        with pytest.raises(ValueError, match="partition_path_or_rows"):
            checks.evaluate(ctx, f["lake"], f["staging"], "month", "source_projection")


def test_events_reject_changed_file_missing_checks_or_fake_run(
    period_fixture, monkeypatch
):
    f = period_fixture
    execute(f)
    work = run_directory(f["staging"], f["run_id"])
    identity = read_json(work / "execution.json")["identity"]
    unit = identity["units"][0]
    item = read_json(silver.checkpoint_path(work, unit))
    with dg.DagsterInstance.ephemeral() as instance:
        with pytest.raises(ValueError, match="real_run_required"):
            cli.report_file(instance, SimpleNamespace(run_id="fake"), item, identity)
        with open(item["target"], "ab") as handle:
            handle.write(b"changed")
        with pytest.raises(ValueError, match="event_file_changed"):
            cli.run_reporting(
                instance,
                lambda context: cli.replay_events(
                    f["lake"], f["staging"], f["run_id"], instance, context
                ),
            )
        assert not instance.fetch_materializations(
            dg.AssetRecordsFilter(asset_key=dg.AssetKey(asset_name(unit["freq"]))),
            limit=1,
        ).records


@pytest.mark.parametrize(
    "case",
    ["planned_only", "failed", "wrong_binding", "wrong_partition", "nonblocking"],
)
def test_event_reporting_never_accepts_planned_or_misbound_checks(period_fixture, case):
    from dagster._core.definitions.asset_checks.asset_check_evaluation import (
        AssetCheckEvaluation,
        AssetCheckEvaluationPlanned,
        AssetCheckEvaluationTargetMaterializationData,
    )
    from dagster._core.events import DagsterEvent, DagsterEventType

    from orchestrator.defs.partitions import cn_a_stock_week_ends

    f = period_fixture
    execute(f)
    work = run_directory(f["staging"], f["run_id"])
    execution = read_json(work / "execution.json")
    identity = execution["identity"]
    unit = identity["units"][0]
    item = read_json(silver.checkpoint_path(work, unit))
    asset, partition, name = (
        dg.AssetKey("silver_stock_weekly"),
        unit["period"],
        check_names("week")[0],
    )
    with dg.DagsterInstance.ephemeral() as instance:
        instance.add_dynamic_partitions("cn_a_stock_week_ends", [partition])
        instance.report_runless_asset_event(
            dg.AssetMaterialization(
                asset_key=asset,
                partition=partition,
                metadata=silver.materialization_metadata(item, identity),
            )
        )
        mat = instance.fetch_materializations(
            dg.AssetRecordsFilter(asset_key=asset, asset_partitions=[partition]),
            limit=1,
        ).records[0]

        def emit(context, payload, kind):
            instance.report_dagster_event(
                DagsterEvent(
                    event_type_value=kind.value,
                    job_name=context.job_name,
                    step_key=context.get_step_execution_context().step.key,
                    event_specific_data=payload,
                ),
                run_id=context.run_id,
            )
            return True

        if case != "planned_only":
            bad = AssetCheckEvaluation(
                asset_key=asset,
                check_name=name,
                partition="2026-10-16" if case == "wrong_partition" else partition,
                passed=case != "failed",
                blocking=case != "nonblocking",
                target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                    storage_id=mat.storage_id + int(case == "wrong_binding"),
                    run_id=mat.event_log_entry.run_id,
                    timestamp=mat.event_log_entry.timestamp,
                ),
            )
            cli.run_reporting(
                instance,
                lambda ctx: emit(ctx, bad, DagsterEventType.ASSET_CHECK_EVALUATION),
            )
        plan = AssetCheckEvaluationPlanned(
            asset_key=asset,
            check_name=name,
            partitions_subset=cn_a_stock_week_ends.subset_with_partition_keys(
                [partition]
            ),
        )
        cli.run_reporting(
            instance,
            lambda ctx: emit(
                ctx, plan, DagsterEventType.ASSET_CHECK_EVALUATION_PLANNED
            ),
        )
        cli.run_reporting(
            instance, lambda ctx: cli.report_file(instance, ctx, item, identity)
        )
        history = instance.event_log_storage.get_asset_check_execution_history(
            dg.AssetCheckKey(asset, name),
            limit=1,
            status=COMPLETED_ASSET_CHECK_EXECUTION_RECORD_STATUSES,
            partition_filter=PartitionKeyFilter(key=partition),
        )
        evaluation = history[0].evaluation
        assert (
            evaluation.passed
            and evaluation.blocking
            and evaluation.partition == partition
        )
        assert evaluation.target_materialization_data.storage_id == mat.storage_id
        assert (
            getattr(
                evaluation.metadata.get("goldenshare/reused_file_validation"),
                "value",
                None,
            )
            is True
        )
