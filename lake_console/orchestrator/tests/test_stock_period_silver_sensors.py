"""Real isolated event storage and source receipts; no production resources."""

import json
from types import SimpleNamespace

import dagster as dg
import pytest

from orchestrator.defs import stock_period_silver as silver
from orchestrator.defs.io.stock_period_silver import run_directory
from orchestrator.defs.resources import LakeRootResource
from orchestrator.defs.run_contracts.stock_period import (
    completion_notice,
    completion_reference,
    validate_completion_notice,
)
from orchestrator.defs.sensors.silver_stock_monthly_update_job_sensor import (
    silver_stock_monthly_update_job_sensor,
)
from orchestrator.defs.sensors.silver_stock_weekly_update_job_sensor import (
    silver_stock_weekly_update_job_sensor,
)
from tests.test_stock_period_silver_contracts import (
    period_fixture as period_fixture,  # noqa: PLC0414
)
from tests.test_stock_period_silver_contracts import (
    update_fixture as update_fixture,  # noqa: PLC0414
)


def context(f, *, after=None, cursor=None):
    if after is None:
        after = max(
            f["instance"]
            .fetch_observations(
                dg.AssetKey(f"raw_tushare_stk_period_bar_adj_{freq}"), limit=1
            )
            .records[0]
            .storage_id
            for freq in ("week", "month")
        )
    value = SimpleNamespace(
        instance=f["instance"],
        resources=SimpleNamespace(lake_root=LakeRootResource(root_path=str(f["lake"]))),
        cursor=cursor or json.dumps({"schema_version": 1, "after": after}),
    )
    value.update_cursor = lambda cursor: setattr(value, "cursor", cursor)
    return value


@pytest.mark.parametrize(
    "freq,definition,job",
    [
        (
            "week",
            silver_stock_weekly_update_job_sensor,
            "silver_stock_weekly_update_job",
        ),
        (
            "month",
            silver_stock_monthly_update_job_sensor,
            "silver_stock_monthly_update_job",
        ),
    ],
)
def test_exact_definition_contract(freq, definition, job):
    assert definition.name == job + "_sensor"
    assert definition.default_status == dg.DefaultSensorStatus.STOPPED
    assert definition.minimum_interval_seconds == 60
    assert definition.job_name == job
    assert definition.tags == {
        "goldenshare/sensor_domain": "quote_data",
        "goldenshare/sensor_target_layer": "silver",
        "goldenshare/sensor_role": "asset_update",
    }


@pytest.mark.parametrize("change", ["version", "freq", "count", "batch", "path"])
def test_notice_rejects_non_contract_inputs(change):
    ref = completion_reference("a" * 64, "b" * 64, "week")
    notice = completion_notice(ref, "week", 3)
    assert validate_completion_notice(notice, "week") == ref
    if change == "version":
        notice["version"] = "other"
    if change == "freq":
        notice["freq"] = "month"
    if change == "count":
        notice["file_count"] = True
    if change == "batch":
        notice["upstream_batch_id"] = "wrong"
    if change == "path":
        notice["path"] = "/arbitrary"
    with pytest.raises(ValueError):
        validate_completion_notice(notice, "week")


def test_idle_tick_does_not_read_receipts_or_market_data(update_fixture, monkeypatch):
    f = update_fixture
    ctx = context(f)
    monkeypatch.setattr(
        silver, "read_completion", lambda *a, **k: pytest.fail("idle receipt read")
    )
    monkeypatch.setattr(
        silver, "connect_configured_duckdb", lambda *a, **k: pytest.fail("sensor SQL")
    )
    result = silver.evaluate_update_sensor(ctx, freq="week", staging_root=f["staging"])
    assert not result.run_requests
    assert result.skip_reason.skip_message == "silver_no_completion"


def test_observation_without_actual_checks_is_not_ready(update_fixture):
    f = update_fixture
    ctx = context(f)
    ref = f["capture"]()
    from orchestrator.defs.asset_guards.stock_period_silver_readiness import (
        raw_check_names,
    )
    from tests.test_stock_period_silver_events import emit_test_check

    asset = "raw_tushare_stk_period_bar_adj_week"
    mat = (
        f["instance"]
        .fetch_materializations(
            dg.AssetRecordsFilter(
                asset_key=dg.AssetKey(asset), asset_partitions=["2026-10-16"]
            ),
            limit=1,
        )
        .records[0]
    )
    emit_test_check(
        f["instance"],
        asset,
        "2026-10-16",
        raw_check_names("week")[0],
        mat,
        passed=False,
    )
    result = silver.evaluate_update_sensor(ctx, freq="week", staging_root=f["staging"])
    assert not result.run_requests
    assert "checks_not_ready" in result.skip_reason.skip_message
    assert (
        json.loads(ctx.cursor)["pending"]["completion"]["raw_execution_id"]
        == ref["raw_execution_id"]
    )


def test_stable_key_pending_cursor_and_failed_run_do_not_auto_retry(update_fixture):
    from tests.test_stock_period_silver_jobs import definitions

    f = update_fixture
    ctx = context(f)
    f["capture"]()
    first = silver.evaluate_update_sensor(
        ctx, freq="week", staging_root=f["staging"]
    ).run_requests[0]
    again = silver.evaluate_update_sensor(
        ctx, freq="week", staging_root=f["staging"]
    ).run_requests[0]
    assert first.run_key == again.run_key
    assert first.run_config == again.run_config
    assert len(ctx.cursor) < 1024
    f["instance"].create_run_for_job(
        definitions(f["lake"]).resolve_job_def(first.job_name),
        run_config=first.run_config,
        status=dg.DagsterRunStatus.FAILURE,
        tags={"dagster/run_key": first.run_key},
    )
    result = silver.evaluate_update_sensor(ctx, freq="week", staging_root=f["staging"])
    assert not result.run_requests
    assert "requires_review" in result.skip_reason.skip_message
    assert "pending" in json.loads(ctx.cursor)


@pytest.mark.parametrize("active_label", ["weekly", "monthly"])
def test_active_run_short_circuits_notification_and_data_reads(
    update_fixture, monkeypatch, active_label
):
    from tests.test_stock_period_silver_jobs import definitions

    f = update_fixture
    ctx = context(f)
    f["instance"].create_run_for_job(
        definitions(f["lake"]).resolve_job_def(
            f"silver_stock_{active_label}_update_job"
        ),
        run_config={
            "ops": {
                f"silver_stock_{active_label}": {
                    "config": {
                        "execution_id": f["run_id"],
                        "audit_report": str(f["report"]),
                    }
                }
            }
        },
        status=dg.DagsterRunStatus.STARTED,
    )
    monkeypatch.setattr(
        f["instance"],
        "fetch_observations",
        lambda *a, **k: pytest.fail("active notification read"),
    )
    result = silver.evaluate_update_sensor(ctx, freq="week", staging_root=f["staging"])
    assert result.skip_reason.skip_message == "silver_run_active"


def test_false_count_and_unknown_target_cannot_trigger(update_fixture):
    from orchestrator.defs.stock_period_update import report_completion_events

    f = update_fixture
    ctx = context(f)
    ref = f["capture"]()
    # Deliberately bad notification, with an otherwise valid immutable receipt.
    ctx.cursor = json.dumps(
        {
            "schema_version": 1,
            "after": f["instance"]
            .fetch_observations(
                dg.AssetKey("raw_tushare_stk_period_bar_adj_week"), limit=1
            )
            .records[0]
            .storage_id,
        }
    )
    report_completion_events(f["instance"], completion_notice(ref, "week", 99))
    result = silver.evaluate_update_sensor(ctx, freq="week", staging_root=f["staging"])
    assert not result.run_requests
    assert result.skip_reason.skip_message == "silver_completion_count_mismatch"
    assert not (
        run_directory(f["staging"], json.loads(ctx.cursor)["pending"]["execution_id"])
        / "execution.json"
    ).exists()


def test_tick_storage_budget_has_no_per_period_queries(update_fixture, monkeypatch):
    import orchestrator.defs.asset_guards.stock_period_silver_readiness as readiness

    f = update_fixture
    ctx = context(f)
    f["capture"]()
    counts = {"runs": 0, "observations": 0, "readiness_sql": 0}
    get_runs, observations = f["instance"].get_runs, f["instance"].fetch_observations
    evidence = readiness.batch_event_evidence

    def runs(*args, **kwargs):
        counts["runs"] += 1
        return get_runs(*args, **kwargs)

    def observed(*args, **kwargs):
        counts["observations"] += 1
        assert kwargs["limit"] == 1
        return observations(*args, **kwargs)

    def queried(*args, **kwargs):
        counts["readiness_sql"] += (
            2  # Real two-query helper, separately verified below.
        )
        return evidence(*args, **kwargs)

    monkeypatch.setattr(f["instance"], "get_runs", runs)
    monkeypatch.setattr(f["instance"], "fetch_observations", observed)
    monkeypatch.setattr(readiness, "batch_event_evidence", queried)
    monkeypatch.setattr(
        silver,
        "connect_configured_duckdb",
        lambda *a, **k: pytest.fail("sensor read market data"),
    )
    assert (
        len(
            silver.evaluate_update_sensor(
                ctx, freq="week", staging_root=f["staging"]
            ).run_requests
        )
        == 1
    )
    assert counts == {"runs": 2, "observations": 1, "readiness_sql": 2}


def test_full_history_metadata_capacity_is_two_queries_per_frequency(
    update_fixture, monkeypatch, record_property
):
    """656 weeks + 154 months of synthetic events, zero market files or COPY."""
    import time
    from contextlib import contextmanager
    from datetime import date, timedelta

    from dagster._core.definitions.asset_checks.asset_check_evaluation import (
        AssetCheckEvaluation,
        AssetCheckEvaluationTargetMaterializationData,
    )
    from dagster._core.events import DagsterEvent, DagsterEventType

    from orchestrator.defs.asset_guards.stock_period_silver_readiness import (
        batch_event_evidence,
        raw_check_names,
        require_checks,
    )
    from orchestrator.defs.bootstrap.stock_period_silver_cli import run_reporting
    from orchestrator.defs.run_contracts.stock_period_silver import (
        asset_name,
        check_names,
    )

    instance = update_fixture["instance"]
    periods = {
        "week": [
            (date(2014, 1, 3) + timedelta(weeks=i)).isoformat() for i in range(656)
        ],
        "month": [f"{2014 + i // 12:04d}-{i % 12 + 1:02d}" for i in range(154)],
    }
    for freq, keys in periods.items():
        for name in (asset_name(freq), f"raw_tushare_stk_period_bar_adj_{freq}"):
            for period in keys:
                instance.report_runless_asset_event(
                    dg.AssetMaterialization(
                        asset_key=dg.AssetKey(name), partition=period,
                        # Literal metadata follows the real producer's required
                        # scope/row/version contract; no physical file is claimed.
                        metadata={
                            "dagster/uri": f"/synthetic/{name}/{period}.parquet",
                            "dagster/row_count": 0,
                            "goldenshare/period_file_version": dg.MetadataValue.json(
                                [1, 2, 128, 3, 4]
                            ),
                            "goldenshare/silver_rule": "stock-period-silver@1",
                            "goldenshare/silver_lower": "2014-01-01",
                            "goldenshare/silver_asof": "2026-10-16",
                        },
                    )
                )
    mats = {
        freq: batch_event_evidence(instance, freq, keys)
        for freq, keys in periods.items()
    }

    def seed_checks(ctx):
        for freq, evidence in mats.items():
            for (name, period), item in evidence.items():
                mat = item["materialization"]
                for check in (
                    raw_check_names(freq)
                    if name.startswith("raw_")
                    else check_names(freq)
                ):
                    instance.report_dagster_event(
                        DagsterEvent(
                            event_type_value=DagsterEventType.ASSET_CHECK_EVALUATION.value,
                            job_name=ctx.job_name,
                            step_key=ctx.get_step_execution_context().step.key,
                            event_specific_data=AssetCheckEvaluation(
                                asset_key=dg.AssetKey(name),
                                partition=period,
                                check_name=check,
                                passed=True,
                                blocking=True,
                                target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                                    storage_id=mat.storage_id,
                                    run_id=mat.event_log_entry.run_id,
                                    timestamp=mat.event_log_entry.timestamp,
                                ),
                            ),
                        ),
                        run_id=ctx.run_id,
                    )

    run_reporting(instance, seed_checks)
    storage = instance.event_log_storage
    connect, statements = storage.index_connection, []

    @contextmanager
    def counted():
        with connect() as connection:

            class Proxy:
                def execute(self, statement):
                    statements.append(statement)
                    return connection.execute(statement)

            yield Proxy()

    monkeypatch.setattr(storage, "index_connection", counted)
    began = time.perf_counter()
    for freq, keys in periods.items():
        before = len(statements)
        evidence = batch_event_evidence(instance, freq, keys)
        assert len(statements) - before == 2
        assert len(evidence) == 2 * len(keys)
        assert sum(len(item["checks"]) for item in evidence.values()) == 6 * len(keys)
        for (name, _), item in evidence.items():
            require_checks(item, freq, raw=name.startswith("raw_"))
    record_property("metadata_810_periods_seconds", time.perf_counter() - began)
