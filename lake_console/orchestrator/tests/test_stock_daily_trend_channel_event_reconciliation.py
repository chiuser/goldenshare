from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass
from pathlib import Path

import dagster as dg
import duckdb
import pytest
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)
from dagster._core.event_api import PartitionKeyFilter

import orchestrator.defs.bootstrap.stock_daily_trend_channel_event_reconciliation as reconciliation
import orchestrator.defs.bootstrap.stock_daily_trend_channel_event_reconciliation_cli as reconciliation_cli
from orchestrator.defs.asset_guards.stock_daily_trend_channel_repair import (
    RESULT_REPAIR_COMPLETION_CHECK_NAME,
    STATE_REPAIR_COMPLETION_CHECK_NAME,
)
from orchestrator.defs.checks.stock_daily_trend_channel_checks import (
    gold_stock_daily_trend_channel_contract_check,
    gold_stock_daily_trend_channel_input_coverage_check,
    gold_stock_daily_trend_channel_state_contract_check,
)
from orchestrator.defs.paths import (
    gold_stock_daily_qfq_path,
    gold_stock_daily_trend_channel_path,
    gold_stock_daily_trend_channel_staging_path,
    gold_stock_daily_trend_channel_state_path,
    gold_stock_daily_trend_channel_state_staging_path,
    silver_stock_basic_path,
    silver_stock_lifecycle_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.stock_daily_qfq import (
    gold_stock_daily_qfq_factor_repair_codes_hash,
)
from orchestrator.defs.stock_daily_trend_channel import (
    FORMULA_VERSION,
    write_stock_daily_trend_channel_daily_partition,
)

PREVIOUS_DATE = "2026-09-01"
TARGET_DATE = "2026-09-02"
QFQ_FACTOR_DATE = "2026-09-03"
NEIGHBOR_DATES = ("2026-09-03", "2026-09-04")
STOCK_CODE = "000001.SZ"


@dataclass(frozen=True)
class _Fixture:
    root: Path
    staging: Path
    lake_root: LakeRootResource
    duckdb_resource: DuckDBResource
    incident_run_id: str
    producer_run_id: str


def _write_parquet(connection, path: Path, select_sql: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection.execute(f"COPY ({select_sql}) TO '{path}' (FORMAT PARQUET)")


def _write_qfq(connection, root: Path, trade_date: str, close: float) -> None:
    path = gold_stock_daily_qfq_path(root, trade_date)
    _write_parquet(
        connection,
        path,
        f"""
        SELECT
          '{STOCK_CODE}'::VARCHAR AS ts_code,
          DATE '{trade_date}' AS trade_date,
          {close - 0.5}::DOUBLE AS open,
          {close + 0.5}::DOUBLE AS high,
          {close - 1.0}::DOUBLE AS low,
          {close}::DOUBLE AS close
        """,
    )


def _write_static_inputs(connection, root: Path) -> None:
    _write_parquet(
        connection,
        silver_stock_basic_path(root),
        f"SELECT '{STOCK_CODE}'::VARCHAR AS ts_code",
    )
    _write_parquet(
        connection,
        silver_stock_lifecycle_path(root),
        f"""
        SELECT
          '{STOCK_CODE}'::VARCHAR AS ts_code,
          true::BOOLEAN AS is_cny_stock,
          DATE '1991-01-01' AS list_date,
          NULL::DATE AS delist_date
        """,
    )
    dates_sql = ",".join(
        f"(DATE '{trade_date}')"
        for trade_date in (PREVIOUS_DATE, TARGET_DATE, *NEIGHBOR_DATES)
    )
    _write_parquet(
        connection,
        silver_trade_calendar_path(root),
        f"""
        SELECT
          'SSE'::VARCHAR AS exchange,
          trade_date,
          true::BOOLEAN AS is_open,
          NULL::DATE AS pretrade_date
        FROM (VALUES {dates_sql}) AS dates(trade_date)
        ORDER BY trade_date
        """,
    )


def _write_trend_day(
    connection,
    *,
    root: Path,
    staging: Path,
    trade_date: str,
    previous_trade_date: str | None,
    close: float,
) -> None:
    _write_qfq(connection, root, trade_date, close)
    write_stock_daily_trend_channel_daily_partition(
        connection=connection,
        trade_date=trade_date,
        qfq_source_path=gold_stock_daily_qfq_path(root, trade_date),
        stock_basic_path=silver_stock_basic_path(root),
        stock_lifecycle_path=silver_stock_lifecycle_path(root),
        previous_trade_date=previous_trade_date,
        previous_state_path=(
            gold_stock_daily_trend_channel_state_path(root, previous_trade_date)
            if previous_trade_date is not None
            else None
        ),
        result_candidate_path=gold_stock_daily_trend_channel_staging_path(
            staging, f"fixture-{trade_date}", trade_date
        ),
        state_candidate_path=gold_stock_daily_trend_channel_state_staging_path(
            staging, f"fixture-{trade_date}", trade_date
        ),
        result_target_path=gold_stock_daily_trend_channel_path(root, trade_date),
        state_target_path=gold_stock_daily_trend_channel_state_path(
            root, trade_date
        ),
    )


def _record_run(
    instance: dg.DagsterInstance,
    *,
    job_name: str,
    status: dg.DagsterRunStatus,
    tags: dict[str, str] | None = None,
    run_config: dict[str, object] | None = None,
    message: str | None = None,
) -> dg.DagsterRun:
    run = dg.DagsterRun(
        job_name=job_name,
        tags=tags or {},
        run_config=run_config or {},
    )
    instance.run_storage.add_run(run)
    event_type = {
        dg.DagsterRunStatus.FAILURE: dg.DagsterEventType.RUN_FAILURE,
        dg.DagsterRunStatus.SUCCESS: dg.DagsterEventType.RUN_SUCCESS,
        dg.DagsterRunStatus.STARTED: dg.DagsterEventType.RUN_START,
    }[status]
    instance.report_dagster_event(
        dg.DagsterEvent(
            event_type.value,
            job_name=job_name,
            message=message,
        ),
        run.run_id,
    )
    return run


def _completion_metadata(*, producer_run_id: str) -> dict[str, object]:
    codes_hash = gold_stock_daily_qfq_factor_repair_codes_hash((STOCK_CODE,))
    return {
        "qfq_factor_repair_trade_date": QFQ_FACTOR_DATE,
        "repair_start_trade_date": PREVIOUS_DATE,
        "repair_end_trade_date": TARGET_DATE,
        "covered_start_trade_date": PREVIOUS_DATE,
        "covered_end_trade_date": TARGET_DATE,
        "selected_partition_count": 2,
        "repair_required_code_count": 1,
        "repair_required_codes_hash": codes_hash,
        "source_upstream_batch_id": "qfq-repair-batch",
        "formula_version": FORMULA_VERSION,
        "rewritten_partition_count": 2,
        "rewritten_indicator_partition_count": 2,
        "rewritten_result_partition_count": 2,
        "rewritten_state_partition_count": 2,
        "rewritten_indicator_row_count": 2,
        "rewritten_result_row_count": 2,
        "rewritten_state_row_count": 2,
        "producer_run_id": producer_run_id,
    }


def _record_repair_completion(
    instance: dg.DagsterInstance, *, producer_run_id: str
) -> None:
    for asset_key, check_name in (
        (reconciliation.RESULT_ASSET_KEY, RESULT_REPAIR_COMPLETION_CHECK_NAME),
        (reconciliation.STATE_ASSET_KEY, STATE_REPAIR_COMPLETION_CHECK_NAME),
    ):
        instance.report_runless_asset_event(
            dg.AssetCheckEvaluation(
                asset_key=dg.AssetKey(asset_key),
                check_name=check_name,
                passed=True,
                blocking=True,
                partition=QFQ_FACTOR_DATE,
                metadata=_completion_metadata(producer_run_id=producer_run_id),
            )
        )


def _record_green_neighbor_events(instance: dg.DagsterInstance) -> None:
    check_specs = (
        (
            reconciliation.STATE_ASSET_KEY,
            reconciliation.STATE_CONTRACT_CHECK,
        ),
        (
            reconciliation.RESULT_ASSET_KEY,
            reconciliation.RESULT_CONTRACT_CHECK,
        ),
        (
            reconciliation.RESULT_ASSET_KEY,
            reconciliation.INPUT_COVERAGE_CHECK,
        ),
    )
    for partition_date in NEIGHBOR_DATES:
        materializations: dict[str, object] = {}
        for asset_key in (
            reconciliation.STATE_ASSET_KEY,
            reconciliation.RESULT_ASSET_KEY,
        ):
            instance.report_runless_asset_event(
                dg.AssetMaterialization(
                    asset_key=dg.AssetKey(asset_key),
                    partition=partition_date,
                    metadata={"fixture": "neighbor"},
                )
            )
            materializations[asset_key] = instance.fetch_materializations(
                dg.AssetRecordsFilter(
                    asset_key=dg.AssetKey(asset_key),
                    asset_partitions=[partition_date],
                ),
                limit=1,
            ).records[0]
        for asset_key, check_name in check_specs:
            record = materializations[asset_key]
            instance.report_runless_asset_event(
                dg.AssetCheckEvaluation(
                    asset_key=dg.AssetKey(asset_key),
                    check_name=check_name,
                    passed=True,
                    blocking=True,
                    partition=partition_date,
                    target_materialization_data=(
                        AssetCheckEvaluationTargetMaterializationData(
                            storage_id=int(record.storage_id),
                            run_id=str(record.run_id),
                            timestamp=float(record.timestamp),
                        )
                    ),
                    metadata={"fixture": "neighbor"},
                )
            )


def _prepare_fixture(
    tmp_path: Path, instance: dg.DagsterInstance
) -> _Fixture:
    root = tmp_path / "lake"
    staging = tmp_path / "staging"
    with duckdb.connect() as connection:
        _write_static_inputs(connection, root)
        _write_trend_day(
            connection,
            root=root,
            staging=staging,
            trade_date=PREVIOUS_DATE,
            previous_trade_date=None,
            close=10.0,
        )
        _write_trend_day(
            connection,
            root=root,
            staging=staging,
            trade_date=TARGET_DATE,
            previous_trade_date=PREVIOUS_DATE,
            close=10.5,
        )
    incident = _record_run(
        instance,
        job_name=reconciliation.INCIDENT_JOB_NAME,
        status=dg.DagsterRunStatus.FAILURE,
        tags={"dagster/partition": TARGET_DATE},
        message=(
            "materialization metadata failed because stock_basic_path is a legacy "
            "metadata key"
        ),
    )
    codes_hash = gold_stock_daily_qfq_factor_repair_codes_hash((STOCK_CODE,))
    producer = _record_run(
        instance,
        job_name=reconciliation.GOLD_STOCK_DAILY_TREND_CHANNEL_REPAIR_JOB_NAME,
        status=dg.DagsterRunStatus.SUCCESS,
        run_config={
            "ops": {
                "gold_stock_daily_trend_channel_repair_op": {
                    "config": {
                        "qfq_factor_repair_trade_date": QFQ_FACTOR_DATE,
                        "repair_start_trade_date": PREVIOUS_DATE,
                        "repair_end_trade_date": TARGET_DATE,
                        "stock_codes": [STOCK_CODE],
                        "repair_required_codes_hash": codes_hash,
                        "source_upstream_batch_id": "qfq-repair-batch",
                    }
                }
            }
        },
    )
    _record_repair_completion(instance, producer_run_id=producer.run_id)
    _record_green_neighbor_events(instance)
    instance.add_dynamic_partitions(
        reconciliation.cn_a_stock_daily_trend_channel_trade_days.name,
        [TARGET_DATE],
    )
    return _Fixture(
        root=root,
        staging=staging,
        lake_root=LakeRootResource(root_path=str(root)),
        duckdb_resource=DuckDBResource(),
        incident_run_id=incident.run_id,
        producer_run_id=producer.run_id,
    )


def _build_plan(
    instance: dg.DagsterInstance,
    fixture: _Fixture,
) -> reconciliation.StockDailyTrendChannelEventReconciliationPlan:
    return reconciliation.build_stock_daily_trend_channel_event_reconciliation_plan(
        instance=instance,
        partition_date=TARGET_DATE,
        incident_run_id=fixture.incident_run_id,
        current_file_producer_run_id=fixture.producer_run_id,
        lake_root=fixture.lake_root,
        duckdb=fixture.duckdb_resource,
    )


def _all_file_hashes(fixture: _Fixture) -> dict[Path, str]:
    paths = (
        gold_stock_daily_trend_channel_path(fixture.root, TARGET_DATE),
        gold_stock_daily_trend_channel_state_path(fixture.root, TARGET_DATE),
        gold_stock_daily_qfq_path(fixture.root, TARGET_DATE),
        gold_stock_daily_trend_channel_state_path(fixture.root, PREVIOUS_DATE),
        silver_stock_lifecycle_path(fixture.root),
        silver_trade_calendar_path(fixture.root),
    )
    return {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def _apply_kwargs(
    instance: dg.DagsterInstance,
    fixture: _Fixture,
    plan: reconciliation.StockDailyTrendChannelEventReconciliationPlan,
) -> dict[str, object]:
    return {
        "instance": instance,
        "plan": plan,
        "lake_root": fixture.lake_root,
        "duckdb": fixture.duckdb_resource,
    }


def test_plan_two_stage_apply_final_audit_and_idempotency(
    tmp_path: Path,
) -> None:
    with dg.DagsterInstance.ephemeral(tempdir=str(tmp_path / "instance")) as instance:
        fixture = _prepare_fixture(tmp_path, instance)
        before_hashes = _all_file_hashes(fixture)
        plan = _build_plan(instance, fixture)

        assert not plan.should_stop
        assert plan.expected_materialization_writes == 2
        assert plan.expected_check_writes == 3
        assert plan.maximum_event_writes == 5
        assert plan.incident_run.run_id != plan.current_file_producer_run.run_id
        assert plan.current_file_producer_run.run_id == fixture.producer_run_id
        assert len(plan.neighbor_event_guard) == 10

        report_path = tmp_path / "reports" / "plan.json"
        reconciliation.write_stock_daily_trend_channel_event_reconciliation_report(
            plan,
            report_path,
            report_root=tmp_path / "reports",
        )
        loaded = reconciliation.load_stock_daily_trend_channel_event_reconciliation_plan(
            report_path,
            expected_plan_id=plan.plan_id,
            expected_plan_hash=plan.plan_hash,
            report_root=tmp_path / "reports",
        )
        assert loaded == plan

        with pytest.raises(
            reconciliation.StockDailyTrendChannelEventReconciliationError,
            match="confirm_event_write",
        ):
            reconciliation.apply_stock_daily_trend_channel_materialization_reconciliation(
                **_apply_kwargs(instance, fixture, plan)
            )

        materializations = reconciliation.apply_stock_daily_trend_channel_materialization_reconciliation(
            **_apply_kwargs(instance, fixture, plan),
            confirm_event_write=True,
        )
        assert [item["event_key"] for item in materializations["written_events"]] == [
            f"{reconciliation.STATE_ASSET_KEY}|{TARGET_DATE}",
            f"{reconciliation.RESULT_ASSET_KEY}|{TARGET_DATE}",
        ]
        assert materializations["after_event_count"] == 2

        materialization_audit = reconciliation.audit_stock_daily_trend_channel_materialization_reconciliation(
            **_apply_kwargs(instance, fixture, plan)
        )
        assert materialization_audit["status"] == "passed"

        checks = reconciliation.apply_stock_daily_trend_channel_check_reconciliation(
            **_apply_kwargs(instance, fixture, plan),
            confirm_event_write=True,
        )
        assert [item["event_key"] for item in checks["written_events"]] == [
            f"{reconciliation.STATE_ASSET_KEY}|{reconciliation.STATE_CONTRACT_CHECK}|{TARGET_DATE}",
            f"{reconciliation.RESULT_ASSET_KEY}|{reconciliation.RESULT_CONTRACT_CHECK}|{TARGET_DATE}",
            f"{reconciliation.RESULT_ASSET_KEY}|{reconciliation.INPUT_COVERAGE_CHECK}|{TARGET_DATE}",
        ]
        final = reconciliation.audit_stock_daily_trend_channel_event_reconciliation(
            **_apply_kwargs(instance, fixture, plan)
        )
        assert final["event_count"] == 5

        materialization_retry = reconciliation.apply_stock_daily_trend_channel_materialization_reconciliation(
            **_apply_kwargs(instance, fixture, plan),
            confirm_event_write=True,
        )
        check_retry = reconciliation.apply_stock_daily_trend_channel_check_reconciliation(
            **_apply_kwargs(instance, fixture, plan),
            confirm_event_write=True,
        )
        assert materialization_retry["status"] == "already_reconciled"
        assert check_retry["status"] == "already_reconciled"
        assert not materialization_retry["written_events"]
        assert not check_retry["written_events"]
        assert _all_file_hashes(fixture) == before_hashes


class _FailSecondEventInstance:
    def __init__(self, instance: dg.DagsterInstance) -> None:
        self._instance = instance
        self._count = 0

    def __getattr__(self, name: str):
        return getattr(self._instance, name)

    def report_runless_asset_event(self, event: object) -> None:
        self._count += 1
        if self._count == 2:
            raise RuntimeError("simulated second event failure")
        self._instance.report_runless_asset_event(event)


def test_partial_materialization_apply_resumes_from_event_log(tmp_path: Path) -> None:
    with dg.DagsterInstance.ephemeral(tempdir=str(tmp_path / "instance")) as instance:
        fixture = _prepare_fixture(tmp_path, instance)
        plan = _build_plan(instance, fixture)
        failing = _FailSecondEventInstance(instance)

        with pytest.raises(RuntimeError, match="second event failure"):
            reconciliation.apply_stock_daily_trend_channel_materialization_reconciliation(
                **_apply_kwargs(failing, fixture, plan),
                confirm_event_write=True,
            )

        resumed = reconciliation.apply_stock_daily_trend_channel_materialization_reconciliation(
            **_apply_kwargs(instance, fixture, plan),
            confirm_event_write=True,
        )
        assert resumed["skipped_event_keys"] == [
            f"{reconciliation.STATE_ASSET_KEY}|{TARGET_DATE}"
        ]
        assert resumed["written_events"] == [
            {
                "event_key": f"{reconciliation.RESULT_ASSET_KEY}|{TARGET_DATE}",
                "storage_id": resumed["written_events"][0]["storage_id"],
            }
        ]


def test_partial_check_apply_resumes_from_event_log(tmp_path: Path) -> None:
    with dg.DagsterInstance.ephemeral(tempdir=str(tmp_path / "instance")) as instance:
        fixture = _prepare_fixture(tmp_path, instance)
        plan = _build_plan(instance, fixture)
        reconciliation.apply_stock_daily_trend_channel_materialization_reconciliation(
            **_apply_kwargs(instance, fixture, plan),
            confirm_event_write=True,
        )
        failing = _FailSecondEventInstance(instance)

        with pytest.raises(RuntimeError, match="second event failure"):
            reconciliation.apply_stock_daily_trend_channel_check_reconciliation(
                **_apply_kwargs(failing, fixture, plan),
                confirm_event_write=True,
            )

        resumed = reconciliation.apply_stock_daily_trend_channel_check_reconciliation(
            **_apply_kwargs(instance, fixture, plan),
            confirm_event_write=True,
        )
        assert resumed["skipped_event_keys"] == [
            f"{reconciliation.STATE_ASSET_KEY}|{reconciliation.STATE_CONTRACT_CHECK}|{TARGET_DATE}"
        ]
        assert len(resumed["written_events"]) == 2
        assert reconciliation.audit_stock_daily_trend_channel_event_reconciliation(
            **_apply_kwargs(instance, fixture, plan)
        )["status"] == "passed"


def test_unknown_event_file_change_and_active_run_fail_closed(tmp_path: Path) -> None:
    with dg.DagsterInstance.ephemeral(tempdir=str(tmp_path / "unknown")) as instance:
        fixture = _prepare_fixture(tmp_path / "unknown-fixture", instance)
        plan = _build_plan(instance, fixture)
        instance.report_runless_asset_event(
            dg.AssetMaterialization(
                asset_key=dg.AssetKey(reconciliation.RESULT_ASSET_KEY),
                partition=TARGET_DATE,
                metadata={"source_method": "unknown"},
            )
        )
        with pytest.raises(
            reconciliation.StockDailyTrendChannelEventReconciliationError,
            match="unknown materialization",
        ):
            reconciliation.apply_stock_daily_trend_channel_materialization_reconciliation(
                **_apply_kwargs(instance, fixture, plan),
                confirm_event_write=True,
            )

    with dg.DagsterInstance.ephemeral(tempdir=str(tmp_path / "check")) as instance:
        fixture = _prepare_fixture(tmp_path / "check-fixture", instance)
        plan = _build_plan(instance, fixture)
        instance.report_runless_asset_event(
            dg.AssetCheckEvaluation(
                asset_key=dg.AssetKey(reconciliation.RESULT_ASSET_KEY),
                check_name=reconciliation.RESULT_CONTRACT_CHECK,
                passed=True,
                blocking=True,
                partition=TARGET_DATE,
                metadata={"source_method": "unknown"},
            )
        )
        with pytest.raises(
            reconciliation.StockDailyTrendChannelEventReconciliationError,
            match="unknown successful check",
        ):
            reconciliation.apply_stock_daily_trend_channel_materialization_reconciliation(
                **_apply_kwargs(instance, fixture, plan),
                confirm_event_write=True,
            )

    with dg.DagsterInstance.ephemeral(tempdir=str(tmp_path / "neighbor")) as instance:
        fixture = _prepare_fixture(tmp_path / "neighbor-fixture", instance)
        plan = _build_plan(instance, fixture)
        instance.report_runless_asset_event(
            dg.AssetMaterialization(
                asset_key=dg.AssetKey(reconciliation.RESULT_ASSET_KEY),
                partition=NEIGHBOR_DATES[-1],
                metadata={"fixture": "changed-neighbor"},
            )
        )
        with pytest.raises(
            reconciliation.StockDailyTrendChannelEventReconciliationError,
            match="neighbor event guard",
        ):
            reconciliation.apply_stock_daily_trend_channel_materialization_reconciliation(
                **_apply_kwargs(instance, fixture, plan),
                confirm_event_write=True,
            )

    with dg.DagsterInstance.ephemeral(tempdir=str(tmp_path / "changed")) as instance:
        fixture = _prepare_fixture(tmp_path / "changed-fixture", instance)
        plan = _build_plan(instance, fixture)
        qfq_path = gold_stock_daily_qfq_path(fixture.root, TARGET_DATE)
        qfq_path.write_bytes(qfq_path.read_bytes() + b"changed")
        with pytest.raises(
            reconciliation.StockDailyTrendChannelEventReconciliationError,
            match="physical files",
        ):
            reconciliation.apply_stock_daily_trend_channel_materialization_reconciliation(
                **_apply_kwargs(instance, fixture, plan),
                confirm_event_write=True,
            )

    with dg.DagsterInstance.ephemeral(tempdir=str(tmp_path / "active")) as instance:
        fixture = _prepare_fixture(tmp_path / "active-fixture", instance)
        active = _record_run(
            instance,
            job_name=reconciliation.INCIDENT_JOB_NAME,
            status=dg.DagsterRunStatus.STARTED,
        )
        plan = _build_plan(instance, fixture)
        assert plan.should_stop
        assert str(active.run_id) in " ".join(plan.blockers)
        with pytest.raises(
            reconciliation.StockDailyTrendChannelEventReconciliationError,
            match="frozen plan is blocked",
        ):
            reconciliation.apply_stock_daily_trend_channel_materialization_reconciliation(
                **_apply_kwargs(instance, fixture, plan),
                confirm_event_write=True,
            )


def _metadata_plain(metadata: dict[str, object]) -> dict[str, object]:
    plain: dict[str, object] = {}
    for key, value in metadata.items():
        if hasattr(value, "value"):
            plain[key] = value.value
        elif hasattr(value, "data"):
            plain[key] = value.data
        elif hasattr(value, "text"):
            plain[key] = value.text
        else:
            plain[key] = value
    return plain


def test_reconciled_check_metadata_keeps_formal_check_parity(tmp_path: Path) -> None:
    with dg.DagsterInstance.ephemeral(tempdir=str(tmp_path / "instance")) as instance:
        fixture = _prepare_fixture(tmp_path, instance)
        plan = _build_plan(instance, fixture)
        kwargs = _apply_kwargs(instance, fixture, plan)
        reconciliation.apply_stock_daily_trend_channel_materialization_reconciliation(
            **kwargs,
            confirm_event_write=True,
        )
        reconciliation.apply_stock_daily_trend_channel_check_reconciliation(
            **kwargs,
            confirm_event_write=True,
        )

        context = dg.build_op_context(
            partition_key=TARGET_DATE,
            resources={
                "lake_root": fixture.lake_root,
                "duckdb": fixture.duckdb_resource,
            },
        )
        formal_results = {
            reconciliation.STATE_CONTRACT_CHECK: (
                gold_stock_daily_trend_channel_state_contract_check(context)
            ),
            reconciliation.RESULT_CONTRACT_CHECK: (
                gold_stock_daily_trend_channel_contract_check(context)
            ),
            reconciliation.INPUT_COVERAGE_CHECK: (
                gold_stock_daily_trend_channel_input_coverage_check(context)
            ),
        }
        for asset_key, check_name in (
            (reconciliation.STATE_ASSET_KEY, reconciliation.STATE_CONTRACT_CHECK),
            (reconciliation.RESULT_ASSET_KEY, reconciliation.RESULT_CONTRACT_CHECK),
            (reconciliation.RESULT_ASSET_KEY, reconciliation.INPUT_COVERAGE_CHECK),
        ):
            record = instance.event_log_storage.get_asset_check_execution_history(
                dg.AssetCheckKey(dg.AssetKey(asset_key), check_name),
                limit=1,
                partition_filter=PartitionKeyFilter(key=TARGET_DATE),
            )[0]
            evaluation = record.event.dagster_event.event_specific_data
            reconciled = _metadata_plain(dict(evaluation.metadata))
            formal = _metadata_plain(dict(formal_results[check_name].metadata))
            assert all(reconciled[key] == value for key, value in formal.items())
            assert reconciled["goldenshare/source_method"] == (
                reconciliation.RECONCILIATION_SOURCE_METHOD
            )
            assert "stock_basic_path" not in reconciled


def test_plan_identity_report_path_cli_and_static_boundaries(tmp_path: Path) -> None:
    with dg.DagsterInstance.ephemeral(tempdir=str(tmp_path / "instance")) as instance:
        fixture = _prepare_fixture(tmp_path, instance)
        plan = _build_plan(instance, fixture)
        report_root = tmp_path / "reports"
        report_path = report_root / "plan.json"
        reconciliation.write_stock_daily_trend_channel_event_reconciliation_report(
            plan,
            report_path,
            report_root=report_root,
        )
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        payload["partition_date"] = "2026-09-01"
        report_path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(
            reconciliation.StockDailyTrendChannelEventReconciliationError,
            match="identity",
        ):
            reconciliation.load_stock_daily_trend_channel_event_reconciliation_plan(
                report_path,
                expected_plan_id=plan.plan_id,
                expected_plan_hash=plan.plan_hash,
                report_root=report_root,
            )
        with pytest.raises(
            reconciliation.StockDailyTrendChannelEventReconciliationError,
            match="under",
        ):
            reconciliation.write_stock_daily_trend_channel_event_reconciliation_report(
                plan,
                fixture.root / "report.json",
                report_root=report_root,
            )

    parser = reconciliation_cli._parser()
    choices = parser._subparsers._group_actions[0].choices
    assert set(choices) == {
        "plan",
        "apply-materializations",
        "audit-materializations",
        "apply-checks",
        "final-audit",
    }
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "plan",
                "--partition-date",
                TARGET_DATE,
                "--incident-run-id",
                "incident",
                "--current-file-producer-run-id",
                "producer",
                "--output",
                "/private/tmp/plan.json",
                "--lake-root",
                "/tmp/lake",
            ]
        )
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "apply-materializations",
                "--plan-report",
                "/private/tmp/plan.json",
                "--plan-id",
                "plan",
                "--plan-hash",
                "hash",
                "--output",
                "/private/tmp/apply.json",
            ]
        )
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "audit-materializations",
                "--plan-report",
                "/private/tmp/plan.json",
                "--plan-id",
                "plan",
                "--plan-hash",
                "hash",
                "--output",
                "/private/tmp/audit.json",
                "--confirm-event-write",
            ]
        )

    business_source = inspect.getsource(reconciliation)
    cli_source = inspect.getsource(reconciliation_cli)
    assert "add_dynamic_partitions" not in business_source
    assert "gold_stock_daily_trend_channel_staging_path" not in business_source
    assert "import duckdb" not in business_source
    assert "kopia" not in business_source.lower()
    assert "--lake-root" not in cli_source
    assert "@dg.asset" not in business_source
    assert "@dg.asset_check" not in business_source
    assert "@dg.job" not in business_source
    assert "@dg.sensor" not in business_source
