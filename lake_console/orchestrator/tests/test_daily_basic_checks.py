"""Real ephemeral event identities and local fixtures only."""

from types import SimpleNamespace
from unittest.mock import patch

import dagster as dg
import pytest
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.asset_guards.daily_basic_readiness import (
    batch_daily_basic_readiness,
    daily_basic_materializations,
)
from orchestrator.defs.assets.daily_basic import raw_tushare_daily_basic
from orchestrator.defs.checks.daily_basic_checks import (
    daily_basic_check_result,
    raw_tushare_daily_basic_file_contract_check,
    raw_tushare_daily_basic_source_coverage_check,
)
from orchestrator.defs.daily_basic_contract import DAILY_BASIC_ASSET, DAILY_BASIC_CHECKS
from orchestrator.defs.jobs.daily_basic_update import raw_tushare_daily_basic_update_job
from orchestrator.defs.partitions import cn_a_daily_basic_trade_days
from orchestrator.defs.run_contracts.metadata import build_materialization_metadata
from tests.test_daily_basic_raw_io import DAY, DB, row, write

GUARD = "orchestrator.defs.asset_guards.daily_basic_readiness"


def materialize_event(instance, evidence):
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=DAILY_BASIC_ASSET,
            partition=DAY,
            metadata=build_materialization_metadata(
                uri="fixture",
                row_count=evidence["source_row_count"],
                extra_metadata=evidence,
            ),
        )
    )
    return daily_basic_materializations(instance, [DAY])[DAY]


def check_events(instance, record):
    for name in DAILY_BASIC_CHECKS:
        instance.report_runless_asset_event(
            dg.AssetCheckEvaluation(
                asset_key=dg.AssetKey(DAILY_BASIC_ASSET),
                check_name=name,
                passed=True,
                partition=DAY,
                target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                    storage_id=record.storage_id,
                    run_id=record.event_log_entry.run_id,
                    timestamp=record.event_log_entry.timestamp,
                ),
            )
        )


def test_materialized_is_not_ready_and_stale_identity(tmp_path):
    evidence = write(tmp_path)
    with (
        dg.DagsterInstance.ephemeral() as instance,
        DB().connect() as connection,
        patch(GUARD + ".load_daily_basic_input_codes", return_value=("000001.SZ",)),
    ):
        record = materialize_event(instance, evidence)
        assert not batch_daily_basic_readiness(
            instance, connection, tmp_path / "lake", [DAY]
        )[DAY].ready
        check_events(instance, record)
        assert batch_daily_basic_readiness(
            instance, connection, tmp_path / "lake", [DAY]
        )[DAY].ready
        materialize_event(instance, evidence)
        assert not batch_daily_basic_readiness(
            instance, connection, tmp_path / "lake", [DAY]
        )[DAY].ready


def test_file_change_invalidates_ready(tmp_path):
    evidence = write(tmp_path)
    with (
        dg.DagsterInstance.ephemeral() as instance,
        DB().connect() as connection,
        patch(GUARD + ".load_daily_basic_input_codes", return_value=("000001.SZ",)),
    ):
        check_events(instance, materialize_event(instance, evidence))
        write(tmp_path, [row(close="5")], write_mode="replace")
        assert (
            batch_daily_basic_readiness(instance, connection, tmp_path / "lake", [DAY])[
                DAY
            ].reason
            == "file_or_delivery_changed"
        )


def test_checks_evidence_and_concurrent_run(tmp_path):
    evidence = write(tmp_path)
    with (
        dg.DagsterInstance.ephemeral() as instance,
        patch(
            "orchestrator.defs.checks.daily_basic_checks.load_daily_basic_input_codes",
            return_value=("000001.SZ",),
        ),
    ):
        record = materialize_event(instance, evidence)
        context = SimpleNamespace(
            instance=instance,
            partition_key=DAY,
            run=SimpleNamespace(
                asset_selection=set(), run_id="check-only", step_keys_to_execute=None
            ),
        )
        root = SimpleNamespace(root=lambda: tmp_path / "lake")
        result = daily_basic_check_result(context, root, DB(), coverage=True)
        assert result.passed
        assert result.metadata["goldenshare/failed_rule_names"].value == []
        context.run.asset_selection = {dg.AssetKey(DAILY_BASIC_ASSET)}
        assert not daily_basic_check_result(context, root, DB(), coverage=True).passed
        context.run.step_keys_to_execute = [
            "raw_tushare_daily_basic_source_coverage_check"
        ]
        assert daily_basic_check_result(context, root, DB(), coverage=True).passed
        assert record.storage_id > 0


def test_partition_mapping_and_job_selection():
    key = dg.AssetKey(DAILY_BASIC_ASSET)
    assert raw_tushare_daily_basic.partitions_def == cn_a_daily_basic_trade_days
    assert isinstance(
        raw_tushare_daily_basic.get_partition_mapping(
            dg.AssetKey("raw_tushare_stock_daily")
        ),
        dg.IdentityPartitionMapping,
    )
    checks = [
        raw_tushare_daily_basic_file_contract_check,
        raw_tushare_daily_basic_source_coverage_check,
    ]
    for check in checks:
        assert (
            next(iter(check.check_specs)).partitions_def == cn_a_daily_basic_trade_days
        )
    upstream = dg.AssetSpec(
        "raw_tushare_stock_daily",
        partitions_def=dg.DynamicPartitionsDefinition(name="cn_a_stock_trade_days"),
    )
    defs = dg.Definitions(
        assets=[upstream, raw_tushare_daily_basic],
        asset_checks=checks,
        jobs=[raw_tushare_daily_basic_update_job],
        resources={"lake_root": object(), "duckdb": object(), "tushare": object()},
    )
    job = defs.resolve_job_def("raw_tushare_daily_basic_update_job")
    assert job.partitions_def == cn_a_daily_basic_trade_days
    assert job.asset_layer.executable_asset_keys == {key}


def test_bounded_window_rejects_full_history():
    with pytest.raises(ValueError, match="window"):
        daily_basic_materializations(None, list(map(str, range(11))))


def test_isolated_asset_and_two_checks_execute(tmp_path):
    from orchestrator.defs.resources import (
        DuckDBResource,
        LakeRootResource,
        TushareResource,
    )
    from tests.test_daily_basic_raw_io import Source

    root = LakeRootResource(root_path=str(tmp_path / "lake"))
    checks = [
        raw_tushare_daily_basic_file_contract_check,
        raw_tushare_daily_basic_source_coverage_check,
    ]
    with (
        dg.DagsterInstance.ephemeral() as instance,
        patch(
            "orchestrator.defs.assets.daily_basic.DEFAULT_LAKE_STAGING_ROOT",
            str(tmp_path / "stage"),
        ),
        patch.object(LakeRootResource, "ensure_available_for_run"),
        patch.object(DuckDBResource, "connect", lambda self: DB().connect()),
        patch.object(
            TushareResource, "call", lambda self, *args: Source([row()]).call(*args)
        ),
        patch(
            "orchestrator.defs.assets.daily_basic.load_daily_basic_input_codes",
            return_value=("000001.SZ",),
        ),
        patch(
            "orchestrator.defs.checks.daily_basic_checks.load_daily_basic_input_codes",
            return_value=("000001.SZ",),
        ),
    ):
        instance.add_dynamic_partitions(cn_a_daily_basic_trade_days.name, [DAY])
        definitions = dg.Definitions(
            assets=[
                dg.AssetSpec(
                    "raw_tushare_stock_daily",
                    partitions_def=dg.DynamicPartitionsDefinition(
                        name="cn_a_stock_trade_days"
                    ),
                ),
                raw_tushare_daily_basic,
            ],
            asset_checks=checks,
            jobs=[raw_tushare_daily_basic_update_job],
            resources={
                "lake_root": root,
                "duckdb": DuckDBResource(),
                "tushare": TushareResource(token="fake"),
            },
        )
        result = definitions.resolve_job_def(
            "raw_tushare_daily_basic_update_job"
        ).execute_in_process(partition_key=DAY, instance=instance)
        assert result.success
        evaluations = result.get_asset_check_evaluations()
        assert len(evaluations) == 2 and all(e.passed for e in evaluations)
        targets = {e.target_materialization_data.storage_id for e in evaluations}
        assert targets == {
            daily_basic_materializations(instance, [DAY])[DAY].storage_id
        }


@pytest.mark.parametrize(
    "select,passes",
    [
        ("SELECT '000001.SZ' ts_code,'20260914' trade_date", True),
        ("SELECT '000001.SZ' ts_code,'20260911' trade_date", False),
        ("SELECT NULL::VARCHAR ts_code,'20260914' trade_date", False),
        ("SELECT '000001.SZ' ts_code,'20260914' trade_date FROM range(2)", False),
        ("SELECT 'bad' bad_column", False),
    ],
)
def test_actual_upstream_file_keys(tmp_path, select, passes):
    from orchestrator.defs.asset_guards.daily_basic_readiness import (
        load_daily_basic_input_codes,
    )
    from orchestrator.defs.paths import raw_stock_daily_path

    path = raw_stock_daily_path(tmp_path, DAY)
    path.parent.mkdir(parents=True)
    with (
        DB().connect() as connection,
        patch(
            GUARD + ".raw_tushare_stock_daily_ready_for_trade_date",
            return_value=SimpleNamespace(ready=True),
        ),
    ):
        with pytest.raises(ValueError, match="upstream_file_missing"):
            load_daily_basic_input_codes(None, connection, tmp_path, DAY)
        connection.execute(f"COPY ({select}) TO ? (FORMAT PARQUET)", [str(path)])
        if passes:
            assert load_daily_basic_input_codes(None, connection, tmp_path, DAY) == (
                "000001.SZ",
            )
        else:
            with pytest.raises(ValueError, match="upstream_"):
                load_daily_basic_input_codes(None, connection, tmp_path, DAY)
