"""Actual single-partition asset/job/check integration, without Raw execution."""

from uuid import uuid4

import dagster as dg
import pytest

from orchestrator.defs import paths, stock_period_silver
from orchestrator.defs.assets.stock_monthly import silver_stock_monthly
from orchestrator.defs.assets.stock_weekly import silver_stock_weekly
from orchestrator.defs.checks import stock_period_silver_checks as checks
from orchestrator.defs.jobs.stock_monthly import silver_stock_monthly_update_job
from orchestrator.defs.jobs.stock_weekly import silver_stock_weekly_update_job
from orchestrator.defs.resources import LakeRootResource
from orchestrator.defs.run_contracts.stock_period_silver import check_names
from tests.test_stock_period_silver_contracts import (
    period_fixture as period_fixture,  # noqa: PLC0414 -- Explicit pytest fixture re-export.
)
from tests.test_stock_period_silver_contracts import (
    update_fixture as update_fixture,  # noqa: PLC0414 -- Explicit pytest fixture re-export.
)


def definitions(root):
    return dg.Definitions(
        assets=[silver_stock_weekly, silver_stock_monthly],
        asset_checks=[
            getattr(checks, n) for f in ("week", "month") for n in check_names(f)
        ],
        jobs=[silver_stock_weekly_update_job, silver_stock_monthly_update_job],
        resources={"lake_root": LakeRootResource(root_path=str(root))},
    )


@pytest.mark.parametrize(
    "freq,label,period,expected_rows",
    [("week", "weekly", "2014-01-03", 1), ("month", "monthly", "2020-02", 1)],
)
def test_real_job_selects_only_silver_and_binds_three_checks(
    period_fixture, monkeypatch, freq, label, period, expected_rows
):
    f = period_fixture
    monkeypatch.setattr(paths, "DEFAULT_LAKE_STAGING_ROOT", str(f["staging"]))
    monkeypatch.setattr(checks, "DEFAULT_LAKE_STAGING_ROOT", str(f["staging"]))
    calls = []
    original = stock_period_silver.select_period

    def tracked(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(stock_period_silver, "select_period", tracked)
    defs = definitions(f["lake"])
    dg.Definitions.validate_loadable(defs)
    job = defs.resolve_job_def(f"silver_stock_{label}_update_job")
    with dg.DagsterInstance.ephemeral() as instance:
        instance.add_dynamic_partitions(
            "cn_a_stock_week_ends" if freq == "week" else "cn_a_stock_months", [period]
        )
        result = job.execute_in_process(
            instance=instance,
            partition_key=period,
            run_config={
                "ops": {
                    f"silver_stock_{label}": {
                        "config": {
                            "execution_id": str(uuid4()),
                            "audit_report": str(f["report"]),
                        }
                    }
                }
            },
        )
        assert result.success
        assert len(calls) == 1  # the three checks reuse the writer validation
        materializations = result.get_asset_materialization_events()
        assert len(materializations) == 1
        assert materializations[0].asset_key == dg.AssetKey(f"silver_stock_{label}")
        record = instance.fetch_materializations(
            dg.AssetRecordsFilter(
                asset_key=dg.AssetKey(f"silver_stock_{label}"),
                asset_partitions=[period],
            ),
            limit=1,
        ).records[0]
        assert (
            record.asset_materialization.metadata["dagster/row_count"].value
            == expected_rows
        )
        evaluations = result.get_asset_check_evaluations()
        assert len(evaluations) == 3
        assert all(
            e.passed
            and e.blocking
            and e.partition == period
            and e.target_materialization_data.storage_id == record.storage_id
            for e in evaluations
        )


def test_catalog_entries_and_governance_are_complete():
    from orchestrator.defs.catalog import (
        get_lake_asset_catalog_entry,
        get_partition_model_definition,
    )
    from tests.test_asset_check_incremental_governance import ASSET_CHECK_GOVERNANCE

    for freq, label in (("week", "weekly"), ("month", "monthly")):
        entry = get_lake_asset_catalog_entry(f"silver_stock_{label}")
        assert entry.dataset_id == f"stock_{label}"
        assert entry.data_contract == f"stock_{label}@1"
        assert len(entry.column_schema) == 21
        assert entry.source_api is None
        assert entry.blocking_check_names == check_names(freq)
        assert set(ASSET_CHECK_GOVERNANCE[entry.asset_key]) == set(check_names(freq))
        assert get_partition_model_definition(
            entry.partition_model
        ).dagster_partition_dimension == ("week_end" if freq == "week" else "month")


def test_real_update_job_batches_history_and_planned_checks_do_not_hide_passed_evidence(
    update_fixture, monkeypatch
):
    from dagster._core.event_api import PartitionKeyFilter

    from orchestrator.defs.bootstrap import stock_period_silver_cli as cli
    from orchestrator.defs.io.stock_period_raw import file_version
    from orchestrator.defs.io.stock_period_silver import read_json, run_directory
    from tests.test_stock_period_silver_execution import capture_history_change

    f = update_fixture
    reference = capture_history_change(f)
    monkeypatch.setattr(paths, "DEFAULT_LAKE_STAGING_ROOT", str(f["staging"]))
    monkeypatch.setattr(checks, "DEFAULT_LAKE_STAGING_ROOT", str(f["staging"]))
    select, inputs = (
        stock_period_silver.select_period,
        stock_period_silver.update_inputs,
    )
    calls, statuses = [], []

    def tracked(*args, **kwargs):
        calls.append(args[3])
        return select(*args, **kwargs)

    def captured(*args, **kwargs):
        latest = f["instance"].event_log_storage.get_asset_check_execution_history(
            dg.AssetCheckKey(
                dg.AssetKey("silver_stock_weekly"), check_names("week")[0]
            ),
            limit=1,
            partition_filter=PartitionKeyFilter(key="2026-10-16"),
        )[0]
        statuses.append(latest.status.value)
        return inputs(*args, **kwargs)

    monkeypatch.setattr(stock_period_silver, "select_period", tracked)
    monkeypatch.setattr(stock_period_silver, "update_inputs", captured)
    run_id = str(uuid4())
    job = definitions(f["lake"]).resolve_job_def("silver_stock_weekly_update_job")
    result = job.execute_in_process(
        instance=f["instance"],
        partition_key="2026-10-16",
        run_config={
            "ops": {
                "silver_stock_weekly": {
                    "config": {
                        "intent": "update",
                        "execution_id": run_id,
                        "source_completion": reference,
                    }
                }
            }
        },
    )
    assert result.success
    assert calls == ["2014-01-03", "2020-04-03", "2026-10-16"]
    assert statuses == ["PLANNED"]
    work = run_directory(f["staging"], run_id)
    assert not (
        work / "events_complete.json"
    ).exists()  # Native anchor had not run when the asset returned.
    versions = {
        p: file_version(unit["target"])
        for p, unit in (
            (u["period"], u)
            for u in read_json(work / "execution.json")["identity"]["units"]
        )
    }
    monkeypatch.setattr(
        stock_period_silver,
        "connect_configured_duckdb",
        lambda *a, **k: pytest.fail("event completion computed data"),
    )
    completed = cli.run_reporting(
        f["instance"],
        lambda context: cli.replay_events(
            f["lake"], f["staging"], run_id, f["instance"], context
        ),
    )
    assert completed["files"] == 3 and completed["checks"] == 9
    for period, version in versions.items():
        assert (
            file_version(stock_period_silver.target_path(f["lake"], "week", period))
            == version
        )
        materialization = (
            f["instance"]
            .fetch_materializations(
                dg.AssetRecordsFilter(
                    asset_key=dg.AssetKey("silver_stock_weekly"),
                    asset_partitions=[period],
                ),
                limit=1,
            )
            .records[0]
        )
        for name in check_names("week"):
            evaluation = (
                f["instance"]
                .event_log_storage.get_asset_check_execution_history(
                    dg.AssetCheckKey(dg.AssetKey("silver_stock_weekly"), name),
                    limit=1,
                    partition_filter=PartitionKeyFilter(key=period),
                )[0]
                .evaluation
            )
            assert evaluation.passed and evaluation.blocking
            assert (
                evaluation.target_materialization_data.storage_id
                == materialization.storage_id
            )


def test_update_job_uses_actual_successor_for_anchor_and_events(
    update_fixture, monkeypatch
):
    from orchestrator.defs.bootstrap import stock_period_silver_cli as cli
    from orchestrator.defs.io.stock_period_silver import read_json, run_directory
    from tests.test_stock_period_silver_execution import (
        interrupted_update,
        refresh_recovery_tail,
    )

    f = update_fixture
    old_id, reference, committed = interrupted_update(f, monkeypatch)
    refresh_recovery_tail(f)
    monkeypatch.setattr(paths, "DEFAULT_LAKE_STAGING_ROOT", str(f["staging"]))
    monkeypatch.setattr(checks, "DEFAULT_LAKE_STAGING_ROOT", str(f["staging"]))
    job = definitions(f["lake"]).resolve_job_def("silver_stock_weekly_update_job")
    result = job.execute_in_process(
        instance=f["instance"],
        partition_key="2026-10-16",
        run_config={
            "ops": {
                "silver_stock_weekly": {
                    "config": {
                        "intent": "update",
                        "execution_id": old_id,
                        "source_completion": reference,
                    }
                }
            }
        },
    )
    assert result.success
    materialization = (
        f["instance"]
        .fetch_materializations(
            dg.AssetRecordsFilter(
                asset_key=dg.AssetKey("silver_stock_weekly"),
                asset_partitions=["2026-10-16"],
            ),
            limit=1,
        )
        .records[0]
    )
    actual_id = materialization.asset_materialization.metadata[
        "goldenshare/silver_execution_id"
    ].value
    assert actual_id != old_id
    complete = cli.run_reporting(
        f["instance"],
        lambda ctx: cli.replay_events(
            f["lake"], f["staging"], actual_id, f["instance"], ctx
        ),
    )
    assert complete["files"] == 3 and complete["status"] == "complete"
    assert (
        read_json(run_directory(f["staging"], old_id) / "events_complete.json")[
            "covered_by_execution_id"
        ]
        == actual_id
    )
    assert all(
        stock_period_silver.file_version(r["target"]) == r["version"] for r in committed
    )


def test_event_readiness_uses_two_real_set_queries_instead_of_per_period_api(
    update_fixture, monkeypatch
):
    from contextlib import contextmanager

    from orchestrator.defs.asset_guards.stock_period_silver_readiness import (
        batch_event_evidence,
        require_checks,
    )

    f = update_fixture
    storage = f["instance"].event_log_storage
    connect, statements = storage.index_connection, []

    @contextmanager
    def connection():
        with connect() as real:

            class Counted:
                def execute(self, statement):
                    statements.append(statement)
                    return real.execute(statement)

            yield Counted()

    monkeypatch.setattr(storage, "index_connection", connection)
    result = batch_event_evidence(
        f["instance"], "week", ["2014-01-03", "2020-04-03", "2026-10-16"]
    )
    assert len(statements) == 2
    assert len(result) == 6
    for (asset, _), item in result.items():
        require_checks(item, "week", raw=asset.startswith("raw_"))
        assert len(item["checks"]) == 3
