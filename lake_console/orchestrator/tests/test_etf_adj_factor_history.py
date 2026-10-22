"""Literal fixtures from the approved Sep15 contract; isolated real Dagster storage.

The historic row (512390.SH, 1.3094, NULL), one-row Raw and original six checks
model the observed 18-day acceptance contract. No production data is read/written.
"""

import os
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import dagster as dg
import pytest
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation,
    AssetCheckEvaluationTargetMaterializationData,
)
from dagster._core.events import DagsterEvent, DagsterEventType
from sqlalchemy import event

from orchestrator.defs.asset_guards.etf_adj_factor_history import (
    FactorMaterializationEvidence,
    audit_factor_history,
    load_factor_history_evidence,
)
from orchestrator.defs.asset_guards.etf_daily_lake_readiness import (
    batch_etf_adj_factor_silver_lake_readiness,
)
from orchestrator.defs.checks.etf_daily_checks import (
    _silver_failed_rules,
    audit_etf_daily_silver_partition,
    evaluate_etf_daily_silver_check,
)
from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.io.etf_daily_raw_writer import (
    FUND_ADJ_RAW_SPEC,
    audit_etf_daily_raw_relation,
)
from orchestrator.defs.io.etf_daily_silver_writer import (
    FUND_ADJ_SILVER_SPEC,
    EtfDailySilverValidationError,
    audit_etf_daily_silver_relation,
    write_etf_adj_factor_silver_partition,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.etf_daily import (
    SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS,
)
from orchestrator.defs.run_contracts.metadata import build_materialization_metadata
from tests.etf_daily_test_support import (
    basic_row,
    make_roots,
    write_basic_reference,
    write_raw_fixture,
)

DAY = "2026-09-15"
ASSET = "silver_etf_adj_factor"
KINDS = (
    "contract",
    "source_filter",
    "source_parity",
    "key_integrity",
    "domain",
    "coverage",
)
APPROVAL = {
    "goldenshare/approved_exception_row_count": 1,
    "goldenshare/exception_sample_codes": ["512390.SH"],
    "goldenshare/exception_registry_hash": "a72b41d5bffd2f16062c102f1163bbcd14f08a3756ff7a944ce9143f948fb94f",
}


def row(code="510330.SH", day=DAY, factor=1.0):
    return {
        "ts_code": code,
        "trade_date": day.replace("-", ""),
        "adj_factor": factor,
        "discount_rate": None,
    }


def latest(instance, asset=ASSET, day=DAY):
    return instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=dg.AssetKey(asset),
            asset_partitions=[day],
        ),
        limit=1,
    ).records[0]


@pytest.fixture
def history_factory(tmp_path):
    instances = []

    def create(*, original_fault=None, days=(DAY,)):
        base = tmp_path / str(len(instances))
        base.mkdir()
        lake, staging = make_roots(base)
        reference = write_basic_reference(
            lake_root=lake,
            staging_root=staging,
            rows=[basic_row("510330.SH"), basic_row("512390.SH")],
            eligibility_as_of=date(2026, 9, 15),
        )
        instance = dg.DagsterInstance.ephemeral()
        instances.append(instance)
        metadata = {}
        files = [Path(reference.raw_uri), Path(reference.silver_uri)]
        for day in days:
            raw = write_raw_fixture(
                lake_root=lake,
                spec=FUND_ADJ_RAW_SPEC,
                partition_key=day,
                rows=[row(day=day)],
            )
            silver = FUND_ADJ_SILVER_SPEC.target_path_builder(lake, day)
            silver.parent.mkdir(parents=True, exist_ok=True)
            with DuckDBResource().connect() as connection:
                # Independent literal historical expected; never use the removed generator.
                connection.execute(f"""COPY (
                    SELECT * FROM (VALUES
                      ('510330.SH', DATE '{day}', 1.0::DOUBLE, NULL::DOUBLE),
                      ('512390.SH', DATE '{day}', 1.3094::DOUBLE, NULL::DOUBLE)
                    ) rows(ts_code, trade_date, adj_factor, discount_rate)
                ) TO {duckdb_string(silver)} (FORMAT PARQUET)""")
                assert connection.execute(
                    f"SELECT ts_code, adj_factor FROM {read_parquet(silver, hive_partitioning=False)} ORDER BY ts_code"
                ).fetchall() == [("510330.SH", 1.0), ("512390.SH", 1.3094)]
                ra = audit_etf_daily_raw_relation(
                    connection,
                    relation_sql=read_parquet(raw, hive_partitioning=False),
                    spec=FUND_ADJ_RAW_SPEC,
                    partition_key=day,
                )
                sa = audit_etf_daily_silver_relation(
                    connection,
                    relation_sql=read_parquet(silver, hive_partitioning=False),
                    spec=FUND_ADJ_SILVER_SPEC,
                    partition_key=day,
                )
            instance.report_runless_asset_event(
                dg.AssetMaterialization(
                    asset_key="raw_tushare_fund_adj",
                    partition=day,
                    metadata=build_materialization_metadata(
                        uri=raw,
                        row_count=1,
                        extra_metadata={"content_hash": ra.content_hash},
                    ),
                )
            )
            metadata[day] = build_materialization_metadata(
                uri=silver,
                row_count=2,
                extra_metadata={
                    "content_hash": sa.content_hash,
                    "raw_row_count": 1,
                    "selected_row_count": 1,
                    "rejected_row_count": 0,
                    "written_row_count": 2,
                    "basic_reference": reference.model_dump(mode="json"),
                    "basic_reference_fingerprint": reference.reference_fingerprint,
                    "basic_raw_snapshot_hash": reference.raw_snapshot_hash,
                    "basic_silver_content_hash": reference.silver_content_hash,
                    "basic_raw_uri": reference.raw_uri,
                    "basic_silver_uri": reference.silver_uri,
                    **APPROVAL,
                },
            )
            files.extend([raw, silver])
        partitions = dg.StaticPartitionsDefinition(list(days))

        @dg.asset(name=ASSET, partitions_def=partitions)
        def original_asset(context):
            return dg.MaterializeResult(metadata=metadata[context.partition_key])

        names = SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS
        if original_fault == "missing":
            names = names[:-1]

        @dg.multi_asset_check(
            specs=[
                dg.AssetCheckSpec(
                    name=name,
                    asset=original_asset,
                    blocking=True,
                    partitions_def=partitions,
                )
                for name in names
            ]
        )
        def original_checks():
            for name in names:
                yield dg.AssetCheckResult(
                    asset_key=ASSET,
                    check_name=name,
                    passed=not (original_fault == "failed" and name == names[-1]),
                    metadata=APPROVAL,
                )

        defs = dg.Definitions(assets=[original_asset], asset_checks=[original_checks])
        job = defs.resolve_implicit_global_asset_job_def()
        for day in days:
            result = job.execute_in_process(
                instance=instance, partition_key=day, raise_on_error=False
            )
            assert result.success == (original_fault != "failed")
        return SimpleNamespace(
            lake=lake,
            staging=staging,
            reference=reference,
            instance=instance,
            files=files,
            bytes={p: p.read_bytes() for p in files},
        )

    yield create
    for instance in instances:
        instance.dispose()


def audit(f, kind=None, day=DAY):
    return audit_etf_daily_silver_partition(
        instance=f.instance,
        lake_root_path=f.lake,
        duckdb_resource=DuckDBResource(),
        spec=FUND_ADJ_SILVER_SPEC,
        partition_key=day,
        check_kind=kind,
    )


def emit_check(
    f, *, passed=True, target_id=None, day=DAY, run_id="later-run", metadata=None
):
    target = latest(f.instance)
    ev = AssetCheckEvaluation(
        asset_key=dg.AssetKey(ASSET),
        check_name=SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS[0],
        partition=day,
        passed=passed,
        blocking=True,
        metadata=metadata,
        target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
            storage_id=target.storage_id if target_id is None else target_id,
            run_id=target.event_log_entry.run_id,
            timestamp=target.event_log_entry.timestamp,
        ),
    )
    f.instance.report_dagster_event(
        DagsterEvent(
            event_type_value=DagsterEventType.ASSET_CHECK_EVALUATION.value,
            job_name="history-test",
            event_specific_data=ev,
        ),
        run_id=run_id,
    )


def test_approved_history_checks_and_readiness_agree_without_writes(history_factory):
    f = history_factory()
    for kind in KINDS:
        result = audit(f, kind)
        assert (
            result.history is not None
            and _silver_failed_rules(result, check_kind=kind) == ()
        )
    with DuckDBResource().connect() as connection:
        ready = batch_etf_adj_factor_silver_lake_readiness(
            instance=f.instance,
            connection=connection,
            lake_root=f.lake,
            trade_dates=[DAY],
        )
    assert ready.statuses[0].ready
    assert {p: p.read_bytes() for p in f.files} == f.bytes
    assert not list(f.staging.rglob("*.parquet"))  # no new candidates


@pytest.mark.parametrize("fault", ["missing", "failed"])
def test_original_acceptance_is_required(history_factory, fault):
    f = history_factory(original_fault=fault)
    assert audit(f).history.errors
    # A later green record cannot turn itself into missing original proof.
    emit_check(f)
    assert audit(f).history.errors


@pytest.mark.parametrize(
    "fault", ["silver", "raw", "basic_raw", "basic_silver", "key", "date", "domain"]
)
def test_physical_drift_fails_and_never_rewrites(history_factory, fault):
    f = history_factory()
    path = {
        "silver": f.files[3],
        "raw": f.files[2],
        "basic_raw": f.files[0],
        "basic_silver": f.files[1],
    }.get(fault, f.files[3])
    if fault in {"key", "date", "domain"}:
        with DuckDBResource().connect() as connection:
            connection.execute(
                f"CREATE TEMP TABLE changed AS SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
            )
            statement = {
                "key": "UPDATE changed SET ts_code='510330.SH'",
                "date": "UPDATE changed SET trade_date=DATE '2026-09-16'",
                "domain": "UPDATE changed SET adj_factor=-1",
            }[fault]
            connection.execute(statement)
            connection.execute(
                f"COPY changed TO {duckdb_string(path)} (FORMAT PARQUET)"
            )
    else:
        path.write_bytes(b"deliberately invalid parquet")
    changed = {p: p.read_bytes() for p in f.files}
    assert audit(f).history.errors
    with DuckDBResource().connect() as connection:
        ready = batch_etf_adj_factor_silver_lake_readiness(
            instance=f.instance,
            connection=connection,
            lake_root=f.lake,
            trade_dates=[DAY],
        )
    assert not ready.statuses[0].ready
    assert {p: p.read_bytes() for p in f.files} == changed


def test_only_file_times_changed_is_allowed(history_factory):
    f = history_factory()
    for path in f.files:
        os.utime(path, (1_700_000_000, 1_700_000_000))
    assert not audit(f).history.errors


@pytest.mark.parametrize("fault", ["failed", "wrong_target"])
def test_later_failures_are_not_hidden_by_original_success(history_factory, fault):
    f = history_factory()
    emit_check(
        f, passed=fault != "failed", target_id=1 if fault == "wrong_target" else None
    )
    assert audit(f).history.errors


def test_recheck_excludes_only_its_own_run_and_does_not_change_original_proof(
    history_factory,
):
    f = history_factory()
    emit_check(f, passed=False, run_id="current-recheck")
    target = FactorMaterializationEvidence.from_record(latest(f.instance))
    evidence = load_factor_history_evidence(
        f.instance, {DAY: target}, current_run_id="current-recheck"
    )[DAY]
    assert not evidence.errors
    assert load_factor_history_evidence(f.instance, {DAY: target})[DAY].errors
    context = SimpleNamespace(
        instance=f.instance,
        partition_keys=(DAY,),
        run=SimpleNamespace(run_id="current-recheck"),
    )
    result = evaluate_etf_daily_silver_check(
        context=context,
        lake_root=LakeRootResource(root_path=str(f.lake)),
        duckdb_resource=DuckDBResource(),
        spec=FUND_ADJ_SILVER_SPEC,
        check_kind="source_parity",
    )
    assert result.passed
    assert result.metadata["goldenshare/historical_acceptance_verified"].value


@pytest.mark.parametrize(
    "field,value",
    [
        ("goldenshare/exception_sample_codes", ["510330.SH"]),
        ("goldenshare/approved_exception_row_count", 2),
        ("goldenshare/exception_registry_hash", "changed"),
    ],
)
def test_approval_identity_is_not_general_history_bypass(history_factory, field, value):
    f = history_factory()
    original = FactorMaterializationEvidence.from_record(latest(f.instance))
    changed = FactorMaterializationEvidence(
        original.storage_id, original.run_id, {**original.metadata, field: value}
    )
    assert load_factor_history_evidence(f.instance, {DAY: changed})[DAY].errors


def test_history_evidence_is_batched_for_ten_dates(history_factory):
    days = (
        "2026-09-15",
        "2026-09-16",
        "2026-09-17",
        "2026-09-18",
        "2026-09-21",
        "2026-09-22",
        "2026-09-23",
        "2026-09-24",
        "2026-09-28",
        "2026-09-29",
    )
    f = history_factory(days=days)
    targets = {
        day: FactorMaterializationEvidence.from_record(latest(f.instance, day=day))
        for day in days
    }
    engine = f.instance.event_log_storage._engine  # isolated SQL storage only
    statements = []

    def observe(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", observe)
    try:
        loaded = load_factor_history_evidence(f.instance, targets)
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert all(not item.errors for item in loaded.values())
    assert len([s for s in statements if s.lstrip().upper().startswith("SELECT")]) == 2
    with DuckDBResource().connect() as connection:
        validated = {}
        for day in days:
            assert not audit_factor_history(
                connection=connection,
                lake_root=f.lake,
                trade_date=day,
                evidence=loaded[day],
                validated_basic_references=validated,
            ).errors
        assert len(validated) == 1


@pytest.mark.parametrize("source_contains_delisted", [False, True])
def test_oct19_delisted_is_filtered_without_filling(tmp_path, source_contains_delisted):
    lake, staging = make_roots(tmp_path)
    reference = write_basic_reference(
        lake_root=lake,
        staging_root=staging,
        rows=[basic_row("510330.SH"), basic_row("512390.SH", list_status="D")],
        eligibility_as_of=date(2026, 10, 19),
    )
    rows = [row(day="2026-10-19")]
    if source_contains_delisted:
        rows.append(row("512390.SH", day="2026-10-19", factor=9.0))
    write_raw_fixture(
        lake_root=lake, spec=FUND_ADJ_RAW_SPEC, partition_key="2026-10-19", rows=rows
    )
    result = write_etf_adj_factor_silver_partition(
        lake_root_path=lake,
        staging_root_path=staging,
        duckdb_resource=DuckDBResource(),
        partition_key="2026-10-19",
        operation_id="normal",
        basic_reference=reference,
    )
    with DuckDBResource().connect() as connection:
        assert connection.execute(
            f"SELECT ts_code, adj_factor FROM {read_parquet(result.target_path, hive_partitioning=False)}"
        ).fetchall() == [("510330.SH", 1.0)]
    assert result.written_row_count == result.selected_row_count == 1
    assert not any("exception" in key for key in result.to_details())


def test_listed_missing_factor_still_blocks_and_source_changes_are_allowed(
    history_factory,
):
    f = history_factory()
    # Normal write on a separate date must not invent the still-L missing code.
    day = "2026-10-16"
    write_raw_fixture(
        lake_root=f.lake, spec=FUND_ADJ_RAW_SPEC, partition_key=day, rows=[row(day=day)]
    )
    result = write_etf_adj_factor_silver_partition(
        lake_root_path=f.lake,
        staging_root_path=f.staging,
        duckdb_resource=DuckDBResource(),
        partition_key=day,
        operation_id="missing",
        basic_reference=f.reference,
    )
    f.instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=ASSET,
            partition=day,
            metadata=build_materialization_metadata(
                uri=result.target_path, row_count=1, extra_metadata=result.to_details()
            ),
        )
    )
    assert "missing_expected_codes" in _silver_failed_rules(
        audit(f, "coverage", day), check_kind="coverage"
    )
    changed_day = "2026-10-15"
    write_raw_fixture(
        lake_root=f.lake,
        spec=FUND_ADJ_RAW_SPEC,
        partition_key=changed_day,
        rows=[row(day=changed_day), row("512390.SH", day=changed_day, factor=2.0)],
    )
    changed = write_etf_adj_factor_silver_partition(
        lake_root_path=f.lake,
        staging_root_path=f.staging,
        duckdb_resource=DuckDBResource(),
        partition_key=changed_day,
        operation_id="source",
        basic_reference=f.reference,
    )
    with DuckDBResource().connect() as connection:
        assert connection.execute(
            f"SELECT adj_factor FROM {read_parquet(changed.target_path, hive_partitioning=False)} WHERE ts_code='512390.SH'"
        ).fetchone() == (2.0,)
    # Existing historic artificial row is preserved; no special overwrite path remains.
    before = f.files[3].read_bytes()
    with pytest.raises(EtfDailySilverValidationError, match="refusing overwrite"):
        write_etf_adj_factor_silver_partition(
            lake_root_path=f.lake,
            staging_root_path=f.staging,
            duckdb_resource=DuckDBResource(),
            partition_key=DAY,
            operation_id="conflict",
            basic_reference=f.reference,
        )
    assert f.files[3].read_bytes() == before


def test_generator_and_registry_are_removed():
    root = Path(__file__).resolve().parents[1] / "src/orchestrator/defs"
    assert not (root / "corrections/etf_adj_factor_terminal_exceptions.py").exists()
    assert not (root / "corrections/etf_adj_factor_terminal_exceptions.yaml").exists()
    for file in [
        root / "io/etf_daily_silver_writer.py",
        root / "checks/etf_daily_checks.py",
        root / "asset_guards/etf_daily_lake_readiness.py",
    ]:
        assert "resolve_etf_adj_factor_terminal_exceptions" not in file.read_text()


def test_new_basic_does_not_redefine_approved_old_file(history_factory):
    f = history_factory()
    write_basic_reference(
        lake_root=f.lake,
        staging_root=f.staging,
        rows=[basic_row("510330.SH"), basic_row("512390.SH", list_status="D")],
        eligibility_as_of=date(2026, 10, 19),
    )
    assert not audit(f).history.errors
    assert {p: p.read_bytes() for p in f.files} == f.bytes


def test_mixed_old_and_current_window_remains_ready(history_factory):
    f = history_factory()
    day = "2026-10-19"
    reference = write_basic_reference(
        lake_root=f.lake,
        staging_root=f.staging,
        rows=[basic_row("510330.SH"), basic_row("512390.SH", list_status="D")],
        eligibility_as_of=date(2026, 10, 19),
    )
    write_raw_fixture(
        lake_root=f.lake, spec=FUND_ADJ_RAW_SPEC, partition_key=day, rows=[row(day=day)]
    )
    result = write_etf_adj_factor_silver_partition(
        lake_root_path=f.lake,
        staging_root_path=f.staging,
        duckdb_resource=DuckDBResource(),
        partition_key=day,
        operation_id="current",
        basic_reference=reference,
    )
    f.instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=ASSET,
            partition=day,
            metadata=build_materialization_metadata(
                uri=result.target_path, row_count=1, extra_metadata=result.to_details()
            ),
        )
    )
    for kind in KINDS:
        assert not _silver_failed_rules(audit(f, kind, day), check_kind=kind)
    with DuckDBResource().connect() as connection:
        ready = batch_etf_adj_factor_silver_lake_readiness(
            instance=f.instance,
            connection=connection,
            lake_root=f.lake,
            trade_dates=[DAY, day],
        )
    assert [item.ready for item in ready.statuses] == [True, True]
    assert {p: p.read_bytes() for p in f.files} == f.bytes


def test_unapproved_old_extra_row_does_not_get_history_acceptance(history_factory):
    f = history_factory()
    md = dict(FactorMaterializationEvidence.from_record(latest(f.instance)).metadata)
    for key in APPROVAL:
        md.pop(key)
    f.instance.report_runless_asset_event(
        dg.AssetMaterialization(asset_key=ASSET, partition=DAY, metadata=md)
    )
    result = audit(f, "source_parity")
    assert result.history is None
    assert "unexpected_silver_rows" in _silver_failed_rules(
        result, check_kind="source_parity"
    )


def test_post_oct19_extra_row_cannot_claim_approved_history(history_factory):
    f = history_factory(days=("2026-10-19",))
    assert (
        "factor_history_approval_identity_invalid"
        in audit(f, day="2026-10-19").history.errors
    )


def test_later_unfinished_check_does_not_fall_back_to_original_success(history_factory):
    from dagster._core.definitions.asset_checks.asset_check_evaluation import (
        AssetCheckEvaluationPlanned,
    )

    f = history_factory()
    f.instance.report_dagster_event(
        DagsterEvent(
            event_type_value=DagsterEventType.ASSET_CHECK_EVALUATION_PLANNED.value,
            job_name="pending-test",
            event_specific_data=AssetCheckEvaluationPlanned(
                asset_key=dg.AssetKey(ASSET),
                check_name=SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS[0],
                partitions_subset=dg.StaticPartitionsDefinition(
                    [DAY]
                ).subset_with_partition_keys([DAY]),
            ),
        ),
        run_id="unfinished",
    )
    assert "factor_history_check_not_passed" in audit(f).history.errors


def test_real_checks_only_job_accepts_old_file_and_binds_all_six_to_original(
    history_factory,
):
    from orchestrator.defs.checks import etf_daily_checks as checks
    from orchestrator.defs.partitions import cn_a_etf_mins_trade_days

    f = history_factory()
    original = latest(f.instance)
    selected = [checks.silver_etf_adj_factor_checks]

    # Installed Dagster validates partition_key through selected materializable assets.
    # A no-I/O test asset supplies that execution context; the six real checks still
    # target the original external factor file and must never rematerialize it.
    @dg.asset(partitions_def=cn_a_etf_mins_trade_days)
    def isolated_partition_context():
        return None

    job = dg.define_asset_job(
        "isolated_history_recheck",
        selection=(
            dg.AssetSelection.assets(isolated_partition_context)
            | dg.AssetSelection.checks_for_assets(ASSET)
        ),
        partitions_def=cn_a_etf_mins_trade_days,
        executor_def=dg.in_process_executor,
    )
    definitions = dg.Definitions(
        assets=[
            isolated_partition_context,
            dg.AssetSpec(ASSET, partitions_def=cn_a_etf_mins_trade_days),
        ],
        asset_checks=selected,
        jobs=[job],
        resources={
            "lake_root": LakeRootResource(root_path=str(f.lake)),
            "duckdb": DuckDBResource(),
        },
    )
    f.instance.add_dynamic_partitions(cn_a_etf_mins_trade_days.name, [DAY])
    result = definitions.resolve_job_def("isolated_history_recheck").execute_in_process(
        instance=f.instance, partition_key=DAY
    )
    assert result.success
    evaluations = result.get_asset_check_evaluations()
    assert len(evaluations) == 6
    assert all(
        ev.passed
        and ev.blocking
        and ev.partition == DAY
        and ev.target_materialization_data.storage_id == original.storage_id
        and ev.metadata["goldenshare/historical_acceptance_verified"].value
        for ev in evaluations
    )
    assert latest(f.instance).storage_id == original.storage_id
    with DuckDBResource().connect() as connection:
        ready = batch_etf_adj_factor_silver_lake_readiness(
            instance=f.instance,
            connection=connection,
            lake_root=f.lake,
            trade_dates=[DAY],
        )
    assert ready.statuses[0].ready
    assert {p: p.read_bytes() for p in f.files} == f.bytes


def test_unknown_later_run_is_not_excluded_with_current_recheck(history_factory):
    from dagster._core.storage.event_log.schema import AssetCheckExecutionsTable

    f = history_factory()
    target = FactorMaterializationEvidence.from_record(latest(f.instance))
    # Deliberately malformed input in the isolated event DB: NULL run identity.
    # It must remain visible instead of SQL NULL != current_run silently hiding it.
    with f.instance.event_log_storage.index_connection() as connection:
        connection.execute(
            AssetCheckExecutionsTable.insert().values(
                asset_key=dg.AssetKey(ASSET).to_string(),
                partition=DAY,
                check_name=SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS[0],
                run_id=None,
                execution_status="PLANNED",
                materialization_event_storage_id=target.storage_id,
            )
        )
    evidence = load_factor_history_evidence(
        f.instance, {DAY: target}, current_run_id="current-recheck"
    )
    assert "factor_history_check_not_passed" in evidence[DAY].errors
