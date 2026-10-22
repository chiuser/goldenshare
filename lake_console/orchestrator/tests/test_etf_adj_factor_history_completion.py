"""Independent literals from LLD11.9; all files and event storage are isolated.

The reviewed 56-code scope is literal test data, not obtained from the new code.
A 2026-09-15 example preserves (510330,2.0) and approved (512390,1.3094),
then adds exactly the 14 source keys named in the reviewed table.
"""

import copy
import json
from dataclasses import replace
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
)
from orchestrator.defs.asset_guards.etf_adj_factor_history_completion import (
    CompletionBasicCache,
    audit_completion_file,
    load_completion_evidence,
)
from orchestrator.defs.asset_guards.etf_daily_lake_readiness import (
    batch_etf_adj_factor_silver_lake_readiness,
)
from orchestrator.defs.checks.etf_daily_checks import (
    _silver_failed_rules,
    audit_etf_daily_silver_partition,
    build_etf_daily_silver_check_result,
)
from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.io.etf_daily_raw_writer import (
    FUND_ADJ_RAW_SPEC,
    audit_etf_daily_raw_relation,
)
from orchestrator.defs.io.etf_daily_silver_writer import (
    FUND_ADJ_SILVER_SPEC,
    audit_etf_daily_silver_relation,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.etf_basic import SILVER_ETF_BASIC_CHECKS
from orchestrator.defs.run_contracts.etf_daily import (
    SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS,
    EtfFactorCompletionFile,
    EtfFactorCompletionPlan,
    validate_etf_factor_completion_scope,
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
SCOPE = json.loads(
    (
        Path(__file__).parent / "fixtures/etf_adj_factor_history_completion_scope.json"
    ).read_text()
)
APPROVAL = {
    "goldenshare/approved_exception_row_count": 1,
    "goldenshare/exception_sample_codes": ["512390.SH"],
    "goldenshare/exception_registry_hash": "a72b41d5bffd2f16062c102f1163bbcd14f08a3756ff7a944ce9143f948fb94f",
}


def latest(instance, asset=ASSET, day=DAY):
    return instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=dg.AssetKey(asset), asset_partitions=[day] if day else None
        ),
        limit=1,
    ).records[0]


def emit_check(instance, target, name, *, passed=True, target_id=None, run_id=None):
    ev = AssetCheckEvaluation(
        asset_key=target.asset_materialization.asset_key,
        check_name=name,
        partition=target.asset_materialization.partition,
        passed=passed,
        blocking=True,
        metadata=APPROVAL if name in SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS else {},
        target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
            storage_id=target.storage_id if target_id is None else target_id,
            run_id=target.event_log_entry.run_id,
            timestamp=target.event_log_entry.timestamp,
        ),
    )
    instance.report_dagster_event(
        DagsterEvent(
            event_type_value=DagsterEventType.ASSET_CHECK_EVALUATION.value,
            job_name="isolated-completion",
            event_specific_data=ev,
        ),
        run_id=target.event_log_entry.run_id if run_id is None else run_id,
    )


def check_ids(instance, asset, day, names):
    import sqlalchemy as sa
    from dagster._core.storage.event_log.schema import AssetCheckExecutionsTable as C

    with instance.event_log_storage.index_connection() as c:
        rows = c.execute(
            sa.select(C.c.id, C.c.check_name).where(
                C.c.asset_key == dg.AssetKey(asset).to_string(),
                C.c.partition == day if day else C.c.partition.is_(None),
                C.c.check_name.in_(names),
            )
        ).fetchall()
    return {name: eid for eid, name in rows}


@pytest.fixture
def completion(tmp_path):
    lake, staging = make_roots(tmp_path)
    old = write_basic_reference(
        lake_root=lake,
        staging_root=staging,
        rows=[basic_row("510330.SH"), basic_row("512390.SH")],
        eligibility_as_of=date(2026, 9, 15),
    )
    new = write_basic_reference(
        lake_root=lake,
        staging_root=staging,
        rows=[basic_row("510330.SH"), basic_row("512390.SH", list_status="D")]
        + [
            basic_row(code, list_date=d.replace("-", ""))
            for code, d in SCOPE["listing_dates"].items()
        ],
        eligibility_as_of=date(2026, 10, 21),
    )
    rows = [
        {
            "ts_code": "510330.SH",
            "trade_date": "20260915",
            "adj_factor": 2.0,
            "discount_rate": None,
        }
    ]
    rows += [
        {
            "ts_code": c,
            "trade_date": "20260915",
            "adj_factor": 1.0,
            "discount_rate": None,
        }
        for c in SCOPE["additions"][DAY]
    ]
    # An actual Raw row outside the reviewed scope must remain excluded.
    rows += [
        {
            "ts_code": "599999.SH",
            "trade_date": "20260915",
            "adj_factor": 9.0,
            "discount_rate": None,
        }
    ]
    raw = write_raw_fixture(
        lake_root=lake, spec=FUND_ADJ_RAW_SPEC, partition_key=DAY, rows=rows
    )
    silver = FUND_ADJ_SILVER_SPEC.target_path_builder(lake, DAY)
    silver.parent.mkdir(parents=True, exist_ok=True)
    candidate = staging / "candidate.parquet"
    with DuckDBResource().connect() as c:
        c.execute(
            f"COPY (SELECT * FROM (VALUES ('510330.SH',DATE '2026-09-15',2.0::DOUBLE,NULL::DOUBLE),('512390.SH',DATE '2026-09-15',1.3094::DOUBLE,NULL::DOUBLE)) t(ts_code,trade_date,adj_factor,discount_rate)) TO {duckdb_string(silver)} (FORMAT PARQUET)"
        )
        # Independently specified desired business rows, not the completion helper.
        codes = ",".join(duckdb_string(x) for x in SCOPE["additions"][DAY])
        c.execute(
            f"COPY (SELECT * FROM {read_parquet(silver, hive_partitioning=False)} UNION ALL SELECT ts_code,DATE '2026-09-15',adj_factor,discount_rate FROM {read_parquet(raw, hive_partitioning=False)} WHERE ts_code IN ({codes})) TO {duckdb_string(candidate)} (FORMAT PARQUET)"
        )
        ra = audit_etf_daily_raw_relation(
            c,
            relation_sql=read_parquet(raw, hive_partitioning=False),
            spec=FUND_ADJ_RAW_SPEC,
            partition_key=DAY,
        )
        old_audit = audit_etf_daily_silver_relation(
            c,
            relation_sql=read_parquet(silver, hive_partitioning=False),
            spec=FUND_ADJ_SILVER_SPEC,
            partition_key=DAY,
        )
        ca = audit_etf_daily_silver_relation(
            c,
            relation_sql=read_parquet(candidate, hive_partitioning=False),
            spec=FUND_ADJ_SILVER_SPEC,
            partition_key=DAY,
        )
    instance = dg.DagsterInstance.ephemeral()
    raw_md = build_materialization_metadata(
        uri=raw, row_count=len(rows), extra_metadata={"content_hash": ra.content_hash}
    )
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key="raw_tushare_fund_adj", partition=DAY, metadata=raw_md
        )
    )
    raw_rec = latest(instance, "raw_tushare_fund_adj")
    old_md = build_materialization_metadata(
        uri=silver,
        row_count=2,
        extra_metadata={
            "content_hash": old_audit.content_hash,
            "written_row_count": 2,
            "basic_reference": old.model_dump(mode="json"),
            "basic_raw_snapshot_hash": old.raw_snapshot_hash,
            "basic_silver_content_hash": old.silver_content_hash,
            **APPROVAL,
        },
    )
    # A real materialization record with original check target identity.
    instance.report_dagster_event(
        DagsterEvent(
            event_type_value=DagsterEventType.ASSET_MATERIALIZATION.value,
            job_name="isolated-original",
            event_specific_data=__import__(
                "dagster._core.events", fromlist=["StepMaterializationData"]
            ).StepMaterializationData(
                materialization=dg.AssetMaterialization(
                    asset_key=ASSET, partition=DAY, metadata=old_md
                )
            ),
        ),
        run_id="original-completion",
    )
    parent = latest(instance)
    for name in SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS:
        emit_check(instance, parent, name)
    basic_md = build_materialization_metadata(
        uri=new.silver_uri,
        row_count=58,
        extra_metadata={
            "raw_snapshot_hash": new.raw_snapshot_hash,
            "silver_content_hash": new.silver_content_hash,
        },
    )
    instance.report_runless_asset_event(
        dg.AssetMaterialization(asset_key="silver_etf_basic", metadata=basic_md)
    )
    br = latest(instance, "silver_etf_basic", None)
    for name in SILVER_ETF_BASIC_CHECKS:
        emit_check(instance, br, name)
    parent = FactorMaterializationEvidence.from_record(parent)
    raw_rec = FactorMaterializationEvidence.from_record(raw_rec)
    basic = FactorMaterializationEvidence.from_record(br)
    ids = check_ids(instance, ASSET, DAY, SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS)
    files = tuple(
        EtfFactorCompletionFile(
            d,
            parent.storage_id,
            parent.run_id,
            parent.metadata,
            ids,
            raw_rec.storage_id,
            raw_rec.metadata,
            2 + len(cs),
            ca.content_hash if d == DAY else "1" * 64,
        )
        for d, cs in sorted(SCOPE["additions"].items())
    )
    # Other 25 days are shape-only unit inputs. No claim of a full-26-day integration.
    plan = EtfFactorCompletionPlan(
        copy.deepcopy(SCOPE),
        new.model_dump(mode="json"),
        {
            "storage_id": basic.storage_id,
            "metadata": basic.metadata,
            "check_ids": check_ids(
                instance, "silver_etf_basic", None, SILVER_ETF_BASIC_CHECKS
            ),
        },
        files,
    ).validate()
    f = SimpleNamespace(
        lake=lake,
        staging=staging,
        instance=instance,
        plan=plan,
        new=new,
        old=old,
        raw=raw,
        silver=silver,
        candidate=candidate,
        parent=parent,
    )
    yield f
    instance.dispose()


def audit(f, path=None):
    with DuckDBResource().connect() as c:
        evidence = load_completion_evidence(
            storage=f.instance.event_log_storage, plan=f.plan, days=[DAY]
        )
        return audit_completion_file(
            connection=c,
            lake_root=f.lake,
            plan=f.plan,
            trade_date=DAY,
            basic_cache=CompletionBasicCache(c, f.lake),
            evidence_errors=evidence.errors[DAY],
            relation_sql=f"SELECT * FROM {read_parquet(path or f.candidate, hive_partitioning=False)}",
        )


def test_scope_and_literal_expected(completion):
    f = completion
    assert (
        len(SCOPE["listing_dates"]) == 56
        and sum(map(len, SCOPE["additions"].values())) == 701
    )
    assert len(SCOPE["additions"][DAY]) == 14
    result = audit(f)
    assert (
        not result.errors
        and result.relation.row_count == 16
        and result.added_row_count == 14
    )
    with DuckDBResource().connect() as c:
        rows = c.execute(
            f"SELECT ts_code,adj_factor,discount_rate FROM {read_parquet(f.candidate, hive_partitioning=False)} ORDER BY ts_code"
        ).fetchall()
    expected = [("510330.SH", 2.0, None), ("512390.SH", 1.3094, None)] + [
        (x, 1.0, None) for x in SCOPE["additions"][DAY]
    ]
    assert rows == sorted(expected)
    assert "599999.SH" not in {r[0] for r in rows}


@pytest.mark.parametrize(
    "fault",
    [
        "delete_old",
        "change_old",
        "extra_code",
        "missing_added",
        "change_added",
        "duplicate",
        "null_factor",
    ],
)
def test_any_unapproved_difference_blocks(completion, fault):
    f = completion
    changed = f.staging / "bad.parquet"
    source = read_parquet(f.candidate, hive_partitioning=False)
    code = SCOPE["additions"][DAY][0]
    sql = {
        "delete_old": f"SELECT * FROM {source} WHERE ts_code!='512390.SH'",
        "change_old": f"SELECT ts_code,trade_date,CASE WHEN ts_code='512390.SH' THEN 9.0 ELSE adj_factor END AS adj_factor,discount_rate FROM {source}",
        "extra_code": f"SELECT * FROM {source} UNION ALL SELECT '599999.SH',DATE '2026-09-15',9.0::DOUBLE,NULL::DOUBLE",
        "missing_added": f"SELECT * FROM {source} WHERE ts_code!='{code}'",
        "change_added": f"SELECT ts_code,trade_date,CASE WHEN ts_code='{code}' THEN 3.0 ELSE adj_factor END AS adj_factor,discount_rate FROM {source}",
        "duplicate": f"SELECT * FROM {source} UNION ALL SELECT * FROM {source} WHERE ts_code='{code}'",
        "null_factor": f"SELECT ts_code,trade_date,CASE WHEN ts_code='{code}' THEN NULL::DOUBLE ELSE adj_factor END AS adj_factor,discount_rate FROM {source}",
    }[fault]
    with DuckDBResource().connect() as c:
        c.execute(f"COPY ({sql}) TO {duckdb_string(changed)} (FORMAT PARQUET)")
    assert audit(f, changed).errors


def test_unapproved_scope_and_tampered_hash_block(completion):
    f = completion
    changed = copy.deepcopy(SCOPE)
    changed["additions"][DAY][0] = "599999.SH"
    with pytest.raises(ValueError):
        validate_etf_factor_completion_scope(changed)
    payload = f.plan.to_dict()
    payload["plan_hash"] = "0" * 64
    with pytest.raises(ValueError):
        EtfFactorCompletionPlan.from_dict(payload)
    assert (
        EtfFactorCompletionPlan.from_dict(f.plan.to_dict()).plan_hash
        == f.plan.plan_hash
    )


def test_original_checks_and_bound_targets_are_required(completion):
    f = completion
    item = f.plan.file(DAY)
    changed = replace(
        item,
        original_check_ids={
            **item.original_check_ids,
            SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS[0]: item.original_check_ids[
                SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS[1]
            ],
        },
    )
    plan = replace(
        f.plan, files=tuple(changed if x.trade_date == DAY else x for x in f.plan.files)
    )
    assert load_completion_evidence(
        storage=f.instance.event_log_storage, plan=plan, days=[DAY]
    ).errors[DAY]


def test_source_changed_blocks_and_mtime_only_is_allowed(completion):
    import os

    f = completion
    for p in [f.raw, f.silver, f.candidate]:
        os.utime(p, (1700000000, 1700000000))
    assert not audit(f).errors
    f.raw.write_bytes(b"bad")
    assert audit(f).errors


def test_checks_then_readiness_require_new_bound_success(completion):
    f = completion
    f.silver.write_bytes(f.candidate.read_bytes())
    item = f.plan.file(DAY)
    md = build_materialization_metadata(
        uri=f.silver,
        row_count=16,
        extra_metadata={
            "written_row_count": 16,
            "content_hash": item.expected_content_hash,
            "basic_reference": f.old.model_dump(mode="json"),
            "history_completion": f.plan.to_dict(),
        },
    )
    f.instance.report_runless_asset_event(
        dg.AssetMaterialization(asset_key=ASSET, partition=DAY, metadata=md)
    )
    current = latest(f.instance)

    def ready():
        with DuckDBResource().connect() as c:
            return batch_etf_adj_factor_silver_lake_readiness(
                instance=f.instance, connection=c, lake_root=f.lake, trade_dates=[DAY]
            ).statuses[0]

    assert not ready().ready
    for kind in [
        "contract",
        "source_filter",
        "source_parity",
        "key_integrity",
        "domain",
        "coverage",
    ]:
        checked = audit_etf_daily_silver_partition(
            instance=f.instance,
            lake_root_path=f.lake,
            duckdb_resource=DuckDBResource(),
            spec=FUND_ADJ_SILVER_SPEC,
            partition_key=DAY,
            check_kind=kind,
        )
        assert not _silver_failed_rules(checked, check_kind=kind)
        result = build_etf_daily_silver_check_result(checked, check_kind=kind)
        assert result.passed
        # Independent fixture: two original rows plus fourteen approved additions.
        assert result.metadata["goldenshare/historical_added_row_count"].value == 14
        assert result.metadata["goldenshare/failed_row_count"].value == 0
    for name in SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS:
        emit_check(f.instance, current, name)
    assert ready().ready
    emit_check(
        f.instance,
        current,
        SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS[0],
        passed=False,
        run_id="isolated-later-check",
    )
    assert not ready().ready


def test_evidence_is_one_bounded_query_and_no_writes(completion):
    f = completion
    statements = []
    engine = f.instance.event_log_storage._engine

    def observe(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", observe)
    try:
        e = load_completion_evidence(
            storage=f.instance.event_log_storage, plan=f.plan, days=[DAY]
        )
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    # SQLite initializes a new isolated connection with these two PRAGMAs.
    # Count the event evidence SELECT, and independently reject every DML statement.
    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    assert not e.errors[DAY] and len(selects) == 1
    assert all(
        s in selects or s in {"PRAGMA journal_mode=WAL;", "PRAGMA foreign_keys=ON;"}
        for s in statements
    )


def test_platform_rejects_repeated_runless_check_for_new_materialization():
    """Installed SDK and actual PostgreSQL index agree; this is a design gate.

    This uses the real runless API in an isolated SQLite instance, with literal
    asset/date/name identity. It must not be worked around by fake run ids.
    """
    from sqlalchemy.exc import IntegrityError

    with dg.DagsterInstance.ephemeral() as instance:

        def emit_one(target):
            instance.report_runless_asset_event(
                AssetCheckEvaluation(
                    asset_key=dg.AssetKey(ASSET),
                    check_name=SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS[0],
                    partition=DAY,
                    passed=True,
                    blocking=True,
                    target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                        storage_id=target.storage_id,
                        run_id=target.event_log_entry.run_id,
                        timestamp=target.event_log_entry.timestamp,
                    ),
                )
            )

        instance.report_runless_asset_event(
            dg.AssetMaterialization(asset_key=ASSET, partition=DAY)
        )
        emit_one(latest(instance))
        instance.report_runless_asset_event(
            dg.AssetMaterialization(asset_key=ASSET, partition=DAY)
        )
        with pytest.raises(IntegrityError, match="UNIQUE constraint failed"):
            emit_one(latest(instance))
