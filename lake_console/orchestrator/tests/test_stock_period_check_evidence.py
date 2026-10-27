"""SDK 1.13.26 plans allocate rows before results; expected order is literal.

Only an owned temporary Dagster/SQLite instance is used. Real SDK event producers
write plans and evaluations; deliberate SQL mutations below are negative cases.
"""

import dagster as dg
import pytest
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation,
    AssetCheckEvaluationPlanned,
    AssetCheckEvaluationTargetMaterializationData,
)
from dagster._core.events import DagsterEvent, DagsterEventType
from dagster._core.storage.event_log.schema import (
    AssetCheckExecutionsTable as Checks,
)
from dagster._core.storage.event_log.schema import SqlEventLogStorageTable as Events
from dagster_shared.serdes.errors import DeserializationError

from orchestrator.defs.asset_guards.stock_period_check_evidence import (
    read_latest_completed_checks,
)
from orchestrator.defs.asset_guards.stock_period_silver_readiness import (
    batch_event_evidence,
    raw_check_names,
)
from orchestrator.defs.bootstrap.stock_period_history_cli import _run_reporting
from orchestrator.defs.partitions import cn_a_stock_months, cn_a_stock_week_ends
from orchestrator.defs.run_contracts.stock_period_silver import (
    VERSION,
    asset_name,
    check_names,
)

ASSET = dg.AssetKey("raw_tushare_stk_period_bar_adj_week")
PARTITION = "2026-10-23"


def emit(instance, context, payload, kind):
    instance.report_dagster_event(
        DagsterEvent(
            event_type_value=kind.value,
            job_name=context.job_name,
            step_key=context.get_step_execution_context().step.key,
            event_specific_data=payload,
        ),
        run_id=context.run_id,
    )


def materialize(instance, version, *, asset=ASSET, partition=PARTITION, metadata=None):
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=asset,
            partition=partition,
            metadata={"goldenshare/period_file_version": version, **(metadata or {})},
        )
    )
    return instance.fetch_materializations(
        dg.AssetRecordsFilter(asset_key=asset, asset_partitions=[partition]), limit=1
    ).records[0]


def plan(
    instance, context, names, *, asset=ASSET, partition=PARTITION, partitions=None
):
    for name in names:
        emit(
            instance,
            context,
            AssetCheckEvaluationPlanned(
                asset_key=asset,
                check_name=name,
                partitions_subset=(
                    partitions or cn_a_stock_week_ends
                ).subset_with_partition_keys([partition]),
            ),
            DagsterEventType.ASSET_CHECK_EVALUATION_PLANNED,
        )


def evaluate(
    instance,
    context,
    names,
    target,
    *,
    passed=True,
    blocking=True,
    asset=ASSET,
    partition=PARTITION,
):
    for name in names:
        emit(
            instance,
            context,
            AssetCheckEvaluation(
                asset_key=asset,
                check_name=name,
                partition=partition,
                passed=passed,
                blocking=blocking,
                target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                    storage_id=target.storage_id,
                    run_id=target.event_log_entry.run_id,
                    timestamp=target.timestamp,
                ),
            ),
            DagsterEventType.ASSET_CHECK_EVALUATION,
        )


def instance_directory(tmp_path):
    directory = tmp_path / "instance"
    directory.mkdir()
    (directory / "dagster.yaml").write_text("telemetry:\n  enabled: false\n")
    return directory


@pytest.fixture
def evidence(tmp_path):
    directory = instance_directory(tmp_path)
    with dg.DagsterInstance.local_temp(str(directory)) as instance:
        instance.add_dynamic_partitions("cn_a_stock_week_ends", [PARTITION])
        names = raw_check_names("week")
        old = materialize(instance, "old-version")
        facts = {"old": old, "names": names}

        def run_a(context):
            plan(instance, context, names)

            def run_b(other):
                plan(instance, other, names)
                evaluate(instance, other, names, old)

            _run_reporting(instance, run_b)
            facts["current"] = materialize(instance, "new-version")
            evaluate(instance, context, names, facts["current"])

        _run_reporting(instance, run_a)
        yield instance, facts


def read(instance, names, **kwargs):
    return read_latest_completed_checks(
        instance, asset_key=ASSET, check_names=names, partition_key=PARTITION, **kwargs
    )


def test_batch_uses_late_result_despite_lower_planned_row_id(evidence):
    instance, facts = evidence
    current = facts["current"]
    result = batch_event_evidence(instance, "week", [PARTITION])[
        (ASSET.to_user_string(), PARTITION)
    ]
    assert result["materialization"].storage_id == current.storage_id
    assert len(result["checks"]) == 3
    assert {
        check.evaluation.target_materialization_data.storage_id
        for check in result["checks"].values()
    } == {current.storage_id}


def test_shared_reader_current_and_historical_cutoff(evidence):
    instance, facts = evidence
    current = read(instance, facts["names"])
    historical = read(
        instance, facts["names"], before_event_id=facts["current"].storage_id
    )
    assert len(current) == len(historical) == 3
    for name in facts["names"]:
        new_record, new_event, bound = current[name]
        old_record, old_event, old_bound = historical[name]
        assert new_record.id < old_record.id  # Plans, not completion order.
        assert new_event > old_event
        assert bound.storage_id == facts["current"].storage_id
        assert old_bound.storage_id == facts["old"].storage_id


@pytest.mark.parametrize("fault", ["failed", "wrong_binding", "nonblocking"])
def test_latest_bad_result_does_not_return_old_success(evidence, fault):
    instance, facts = evidence
    name = facts["names"][0]
    target = facts["old"] if fault == "wrong_binding" else facts["current"]
    _run_reporting(
        instance,
        lambda context: evaluate(
            instance,
            context,
            [name],
            target,
            passed=fault != "failed",
            blocking=fault != "nonblocking",
        ),
    )
    record, event_id, bound = read(instance, [name])[name]
    assert event_id > facts["current"].storage_id
    assert record.evaluation.passed is (fault != "failed")
    assert record.evaluation.blocking is (fault != "nonblocking")
    assert bound.storage_id == target.storage_id


@pytest.mark.parametrize(
    "fault", ["null", "duplicate", "missing_event", "wrong_event_type", "copy"]
)
def test_corrupt_latest_evidence_is_not_hidden_by_join_or_history(evidence, fault):
    instance, facts = evidence
    name = facts["names"][0]
    record, event_id, _ = read(instance, [name])[name]
    with instance.event_log_storage.index_connection() as connection:
        if fault == "null":
            connection.execute(
                Checks.update()
                .where(Checks.c.id == record.id)
                .values(evaluation_event_storage_id=None)
            )
        elif fault == "duplicate":
            connection.execute(
                Checks.update()
                .where(
                    Checks.c.asset_key == ASSET.to_string(),
                    Checks.c.check_name == name,
                    Checks.c.id != record.id,
                )
                .values(evaluation_event_storage_id=event_id)
            )
        elif fault == "missing_event":
            connection.execute(Events.delete().where(Events.c.id == event_id))
        elif fault == "wrong_event_type":
            connection.execute(
                Events.update()
                .where(Events.c.id == event_id)
                .values(dagster_event_type="ASSET_MATERIALIZATION")
            )
        else:
            connection.execute(
                Checks.update()
                .where(Checks.c.id == record.id)
                .values(evaluation_event="{}")
            )
    with pytest.raises((ValueError, DeserializationError)):
        read(instance, [name])


def test_null_terminal_after_historical_cutoff_still_rejects(evidence):
    instance, facts = evidence
    name = facts["names"][0]
    record, _, _ = read(instance, [name])[name]
    with instance.event_log_storage.index_connection() as connection:
        connection.execute(
            Checks.update()
            .where(Checks.c.id == record.id)
            .values(evaluation_event_storage_id=None)
        )
    with pytest.raises(ValueError, match="event_id_invalid"):
        read(instance, [name], before_event_id=facts["current"].storage_id)


@pytest.mark.parametrize(
    "freq,layer",
    [("week", "raw"), ("month", "raw"), ("week", "silver"), ("month", "silver")],
)
def test_both_frequencies_and_layers_use_actual_completion_order(tmp_path, freq, layer):
    asset = dg.AssetKey(
        f"raw_tushare_stk_period_bar_adj_{freq}" if layer == "raw" else asset_name(freq)
    )
    partition = PARTITION if freq == "week" else "2026-10"
    partitions = cn_a_stock_week_ends if freq == "week" else cn_a_stock_months
    names = raw_check_names(freq) if layer == "raw" else check_names(freq)
    with dg.DagsterInstance.local_temp(str(instance_directory(tmp_path))) as instance:
        instance.add_dynamic_partitions(partitions.name, [partition])
        old = materialize(instance, "old", asset=asset, partition=partition)
        current = None

        def run_a(context):
            nonlocal current
            plan(
                instance,
                context,
                names,
                asset=asset,
                partition=partition,
                partitions=partitions,
            )

            def run_b(other):
                plan(
                    instance,
                    other,
                    names,
                    asset=asset,
                    partition=partition,
                    partitions=partitions,
                )
                evaluate(instance, other, names, old, asset=asset, partition=partition)

            _run_reporting(instance, run_b)
            current = materialize(instance, "new", asset=asset, partition=partition)
            evaluate(
                instance, context, names, current, asset=asset, partition=partition
            )

        _run_reporting(instance, run_a)
        result = batch_event_evidence(
            instance, freq, [partition], include_raw=layer == "raw"
        )
        item = result[(asset.to_user_string(), partition)]
        assert len(item["checks"]) == len(item["check_event_storage_ids"]) == 3
        assert {
            r.evaluation.target_materialization_data.storage_id
            for r in item["checks"].values()
        } == {current.storage_id}


def test_legal_preimage_is_missing_current_check_but_late_wrong_binding_is_refused(
    tmp_path,
):
    from orchestrator.defs.asset_guards.stock_period_silver_readiness import (
        require_checks,
        require_recoverable_checks,
    )

    # Only the metadata classification boundary is under test. These literal
    # versions represent an already-validated Silver committed record; no file
    # validation or real-source integration is claimed by this metadata fixture.
    asset = dg.AssetKey(asset_name("week"))
    target = str(tmp_path / "part.parquet")
    metadata = {
        "dagster/uri": target,
        "goldenshare/silver_rule": VERSION,
        "goldenshare/silver_lower": "2014-01-01",
    }
    record = {
        "period": PARTITION,
        "target": target,
        "version": [2],
        "event_preimage": [1],
    }
    names = check_names("week")
    with dg.DagsterInstance.local_temp(str(instance_directory(tmp_path))) as instance:
        instance.add_dynamic_partitions("cn_a_stock_week_ends", [PARTITION])
        old = materialize(
            instance, dg.MetadataValue.json([1]), asset=asset, metadata=metadata
        )
        _run_reporting(
            instance,
            lambda context: evaluate(instance, context, names, old, asset=asset),
        )
        current = materialize(
            instance, dg.MetadataValue.json([2]), asset=asset, metadata=metadata
        )
        item = batch_event_evidence(instance, "week", [PARTITION], include_raw=False)[
            (asset.to_user_string(), PARTITION)
        ]
        require_recoverable_checks(item, "week", record)
        with pytest.raises(ValueError, match="checks_not_ready"):
            require_checks(item, "week", raw=False)
        _run_reporting(
            instance,
            lambda context: evaluate(instance, context, [names[0]], old, asset=asset),
        )
        late = batch_event_evidence(instance, "week", [PARTITION], include_raw=False)[
            (asset.to_user_string(), PARTITION)
        ]
        with pytest.raises(ValueError, match="checks_not_ready"):
            require_recoverable_checks(late, "week", record)
        _run_reporting(
            instance,
            lambda context: evaluate(instance, context, names, current, asset=asset),
        )
        fixed = batch_event_evidence(instance, "week", [PARTITION], include_raw=False)[
            (asset.to_user_string(), PARTITION)
        ]
        assert require_checks(fixed, "week", raw=False).storage_id == current.storage_id


def test_empty_scope_does_not_connect(evidence, monkeypatch):
    instance, _ = evidence

    def forbidden():
        pytest.fail("An empty check scope opened a database connection")

    monkeypatch.setattr(instance.event_log_storage, "index_connection", forbidden)
    assert read(instance, []) == {}
    assert batch_event_evidence(instance, "week", []) == {}
