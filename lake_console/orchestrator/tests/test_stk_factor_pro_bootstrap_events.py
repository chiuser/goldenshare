"""LLD 22.6: actual bootstrap producer + native temporary event store.

Coverage JSON/CSV follows the accepted 2026-11-15 report producer (run.py,
merge); publication records come from publish_bootstrap_date, not the tool.
Business expected values below are literal and never built by its metadata helper.
"""

import csv
import io
import json
from collections import Counter
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path

import dagster as dg
import pytest
import sqlalchemy as sa
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation,
    AssetCheckEvaluationPlanned,
    AssetCheckEvaluationTargetMaterializationData,
)
from dagster._core.events import DagsterEvent, DagsterEventType

from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_events as E
from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_publication as P
from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_records as R
from orchestrator.defs.checks import stk_factor_pro as checks
from orchestrator.defs.io import stk_factor_pro_candidates as candidates
from orchestrator.defs.paths import (
    raw_stk_factor_pro_path,
    silver_stock_factor_pro_path,
    stk_factor_pro_bootstrap_operation_root,
)
from orchestrator.defs.run_contracts import stk_factor_pro as C
from tests.stk_factor_pro_bootstrap_test_support import (
    approval_fixture,
    bootstrap_date_results,
    check_test_space,
    native_row,
    source_fixture,
)
from tests.stk_factor_pro_test_support import connection
from tests.test_stk_factor_pro_bootstrap_publication import release_date_work
from tests.test_stk_factor_pro_dagster_events import _isolated_instance

DAY = date(2019, 10, 16)
LAYERS = (
    ("raw", C.STK_FACTOR_PRO_RAW_ASSET_KEY, C.STK_FACTOR_PRO_RAW_CHECK_NAME),
    ("silver", C.STK_FACTOR_PRO_SILVER_ASSET_KEY, C.STK_FACTOR_PRO_SILVER_CHECK_NAME),
)


def _coverage(root, approval, known, days, **changes):
    # Exact column names/types from the real saved daily.csv, with hand-counted rows.
    stream = io.StringIO()
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(
        (
            "trade_date",
            "physical_rows",
            "physical_codes",
            "expected_count",
            "matched_count",
            "missing_count",
            "reused_matched_count",
            "needs_check_count",
            "status",
            "reason",
        )
    )
    for day in days:
        writer.writerow((str(day), 1, 1, 1, 1, 0, 1, 0, "complete", ""))
    daily = stream.getvalue().encode()
    summary = {
        "operation_id": approval.operation_id,
        "approval_digest": known[root / "approval.json"][1],
        "rule_version": "stock_daily.v1",
        "date_count": len(days),
        "physical_factor_rows": len(days),
        "expected_count": len(days),
        "matched_count": len(days),
        "missing_count": 0,
        "complete_dates": len(days),
        "incomplete_dates": 0,
        "unknown_dates": 0,
        "passed": True,
        "previous_missing_keys": 0,
        "previous_missing_still_expected": 0,
        "quote_files_read": len(days),
        "suspend_files_read": len(days),
        "factor_files_read": 0,
        "new_expected_keys_checked": 0,
        "reports": {"daily.csv": sha256(daily).hexdigest()},
        "formal_business_writes": 0,
        "prod_requests": 0,
        "bootstrap_runs": 0,
    }
    summary.update(changes)
    payload = json.dumps(summary, sort_keys=True).encode()
    digest = sha256(payload).hexdigest()
    folder = root / "coverage" / "audits" / digest
    folder.mkdir(parents=True)
    (folder / "daily.csv").write_bytes(daily)
    (folder / "summary.json").write_bytes(payload)
    return (folder / "summary.json").relative_to(root).as_posix(), digest


def prepare(tmp_path, days=(DAY,)):
    known = {}
    with connection(tmp_path) as conn:
        all_days = tuple(
            days[0] + timedelta(days=i) for i in range((days[-1] - days[0]).days + 1)
        )
        lake, staging, approval, _ = approval_fixture(
            conn,
            tmp_path,
            counts=tuple((day, int(day in days)) for day in all_days),
            known_records=known,
        )
        for day in days:
            release_date_work(conn, include_source=True)
            source = source_fixture(
                conn,
                staging_root=staging,
                approval=approval,
                rows=(native_row(day=day),),
                day=day,
                attempt=sha256(str(day).encode()).hexdigest()[:32],
                known_records=known,
            )
            relative = f"source/dates/{day}/source-complete.json"
            P.publish_bootstrap_date(
                conn,
                lake_root=lake,
                staging_root=staging,
                approval=approval,
                source_complete=source,
                source_record_sha256=known[
                    R.operation_path(staging, approval, relative)
                ][1],
                source_relation=candidates.BOOTSTRAP_DAY_SOURCE,
                before_publish=lambda: None,
                check_space=check_test_space,
                known_records=known,
                date_results=bootstrap_date_results({}, source),
            )
    root = R.operation_root(staging, approval)
    reference = _coverage(root, approval, known, days)
    return {
        "lake_root": lake,
        "staging_root": staging,
        "operation_id": approval.operation_id,
        "historical_coverage_ref": reference,
        "trade_dates": days,
        "code_revision": "fixture-v1",
    }, root


def apply(instance, args, digest, days=None):
    return E.apply_stk_factor_pro_bootstrap_events(
        instance=instance,
        **{key: args[key] for key in ("lake_root", "staging_root", "operation_id")},
        expected_plan_digest=digest,
        trade_dates=days if days is not None else args["trade_dates"],
    )


def expected_metadata(args, day, layer):
    path = (
        raw_stk_factor_pro_path if layer == "raw" else silver_stock_factor_pro_path
    )(args["lake_root"], str(day))
    root = stk_factor_pro_bootstrap_operation_root(
        args["staging_root"], args["operation_id"]
    )
    complete = json.loads(
        (root / f"publication/{day}/{layer}/complete.json").read_bytes()
    )
    # Values are independent literal projections of the producer's original audit.
    result = {
        "goldenshare/file_path": str(path),
        "goldenshare/file_sha256": complete["actual_file_sha256"],
        "goldenshare/contract_content_digest": C.STK_FACTOR_PRO_CONTRACT_CONTENT_DIGEST,
        "goldenshare/processing_version": "1",
        "dagster/row_count": 1,
        "goldenshare/comparison": {
            "expected_rows": 1,
            "actual_rows": 1,
            "missing_key_count": 0,
            "unexpected_key_count": 0,
            "changed_row_count": 0,
            "changed_field_counts": [
                [name, 0] for name in C.STK_FACTOR_PRO_SOURCE_COLUMNS[2:]
            ],
        },
    }
    if layer == "silver":
        raw = json.loads((root / f"publication/{day}/raw/complete.json").read_bytes())
        result["goldenshare/raw_sha256"] = raw["actual_file_sha256"]
    return result


def report_check(instance, evaluation, *, planned=False):
    # Native storage permits one check per asset/check/run/partition. Distinct
    # historical attempts must have distinct real runs, as production jobs do.
    run = instance.create_run_for_job(
        dg.GraphDefinition(name="fixture_event_history").to_job()
    )
    instance.report_dagster_event(
        DagsterEvent(
            event_type_value=(
                DagsterEventType.ASSET_CHECK_EVALUATION_PLANNED
                if planned
                else DagsterEventType.ASSET_CHECK_EVALUATION
            ).value,
            job_name="fixture_event_history",
            event_specific_data=evaluation,
        ),
        run_id=run.run_id,
    )


def seed(
    instance,
    args,
    day=DAY,
    layer="raw",
    *,
    check=True,
    passed=True,
    wrong_target=False,
    metadata=None,
):
    _, asset, name = next(item for item in LAYERS if item[0] == layer)
    metadata = expected_metadata(args, day, layer) if metadata is None else metadata
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset_key=dg.AssetKey(asset),
            partition=str(day),
            metadata=metadata,
        )
    )
    material = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=dg.AssetKey(asset), asset_partitions=[str(day)]
        ),
        limit=1,
    ).records[0]
    if check:
        report_check(
            instance,
            AssetCheckEvaluation(
                asset_key=dg.AssetKey(asset),
                check_name=name,
                partition=str(day),
                passed=passed,
                blocking=True,
                severity=dg.AssetCheckSeverity.ERROR,
                metadata=metadata,
                target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                    storage_id=material.storage_id + int(wrong_target),
                    run_id=material.event_log_entry.run_id,
                    timestamp=material.timestamp,
                ),
            ),
        )
    return material


def no_business_io(monkeypatch, args):
    import duckdb

    from orchestrator.defs.resources import TushareResource

    def forbidden(*_a, **_k):
        pytest.fail(
            "event tool must not re-read, hash, recover or download business data"
        )

    original = Path.open

    def opened(path, *a, **k):
        if path.suffix == ".parquet":
            forbidden()
        return original(path, *a, **k)

    monkeypatch.setattr(Path, "open", opened)
    monkeypatch.setattr(duckdb, "connect", forbidden)
    monkeypatch.setattr(TushareResource, "call", forbidden)
    monkeypatch.setattr(dg.DagsterInstance, "get", forbidden)
    for module, names in (
        (
            P,
            (
                "_verify_target_identity",
                "_current_file_sha",
                "factor_file_sha",
                "audit_stk_factor_pro_file",
            ),
        ),
        (checks, ("factor_file_sha", "audit_stk_factor_pro_file")),
        (R, ("load_complete_source", "load_approved_counts")),
    ):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)
    monkeypatch.setattr(dg.DagsterInstance, "add_dynamic_partitions", forbidden)
    # A Raw completion intentionally has no file-system identity field, like real Prod import records.
    root = stk_factor_pro_bootstrap_operation_root(
        args["staging_root"], args["operation_id"]
    )
    raw = json.loads(
        (root / f"publication/{args['trade_dates'][0]}/raw/complete.json").read_bytes()
    )
    assert "identity" not in raw and "file_identity" not in raw["audit"]


def test_real_producer_to_events_binding_and_zero_business_io(tmp_path, monkeypatch):
    args, root = prepare(tmp_path)
    expected = {layer: expected_metadata(args, DAY, layer) for layer, _, _ in LAYERS}
    before = {p: p.stat() for p in args["lake_root"].rglob("*.parquet")}
    no_business_io(monkeypatch, args)
    with _isolated_instance(tmp_path) as instance:
        plan, digest = E.plan_stk_factor_pro_bootstrap_events(instance=instance, **args)
        assert (plan.existing_count, plan.max_new_events, plan.conflicts) == (0, 4, ())
        assert len(list((root / "events").rglob("*.json"))) == 1
        assert not E._materials(instance, {(DAY, "raw"), (DAY, "silver")})
        result = apply(instance, args, digest)
        assert (
            result["new_materializations"],
            result["new_checks"],
            result["confirmed_events"],
        ) == (2, 2, 4)
        materials, checks_ = (
            E._materials(instance, {(DAY, "raw"), (DAY, "silver")}),
            E._checks(instance, (DAY,)),
        )
        for layer, asset, name in LAYERS:
            material = materials[DAY, layer]
            actual = {
                key: value.value
                for key, value in material.asset_materialization.metadata.items()
            }
            assert {key: actual[key] for key in expected[layer]} == expected[layer]
            assert "goldenshare/day_source_digest" not in actual
            assert "goldenshare/bootstrap_operation_id" in actual
            evaluation = checks_[DAY, layer].evaluation
            bound = evaluation.target_materialization_data
            assert evaluation.passed and evaluation.blocking
            assert (
                evaluation.asset_key == dg.AssetKey(asset)
                and evaluation.check_name == name
            )
            assert (bound.storage_id, bound.run_id, bound.timestamp) == (
                material.storage_id,
                material.event_log_entry.run_id,
                material.timestamp,
            )
        repeat = apply(instance, args, digest)
        assert (repeat["new_materializations"], repeat["new_checks"]) == (0, 0)
        assert {p: p.stat() for p in before} == before
        assert list((root / "events").rglob("*.json")) == [
            root / f"events/plans/{digest}.json"
        ]


@pytest.mark.parametrize(
    "checks_present,expected", [(True, (0, 0, 0)), (False, (0, 2, 2))]
)
def test_reuses_events_without_tool_tags_and_only_missing_checks(
    tmp_path, checks_present, expected
):
    args, _ = prepare(tmp_path)
    with _isolated_instance(tmp_path) as instance:
        for layer, _, _ in LAYERS:
            seed(instance, args, layer=layer, check=checks_present)
        plan, digest = E.plan_stk_factor_pro_bootstrap_events(instance=instance, **args)
        result = apply(instance, args, digest)
        assert (
            result["new_materializations"],
            result["new_checks"],
            plan.max_new_events,
        ) == expected


@pytest.mark.parametrize("kind", ["failed", "binding", "metadata", "latest_material"])
def test_latest_conflict_never_falls_back_to_old_green(tmp_path, kind):
    args, _ = prepare(tmp_path)
    with _isolated_instance(tmp_path) as instance:
        seed(instance, args)
        if kind == "metadata":
            data = expected_metadata(args, DAY, "raw")
            data["goldenshare/file_sha256"] = "f" * 64
            seed(instance, args, metadata=data)
        elif kind == "latest_material":
            seed(instance, args, check=False)
        else:
            seed(
                instance, args, passed=kind != "failed", wrong_target=kind == "binding"
            )
        plan, digest = E.plan_stk_factor_pro_bootstrap_events(instance=instance, **args)
        assert plan.conflicts and plan.existing_count >= 1
        with pytest.raises(ValueError, match="冲突"):
            apply(instance, args, digest)


@pytest.mark.parametrize("stop_after", ["materialization", "check"])
def test_exit_after_native_write_reopens_same_plan_without_duplicates(
    tmp_path, monkeypatch, stop_after
):
    args, root = prepare(tmp_path)
    no_business_io(monkeypatch, args)
    with _isolated_instance(tmp_path) as instance:
        _, digest = E.plan_stk_factor_pro_bootstrap_events(instance=instance, **args)
        original = instance.report_runless_asset_event

        def interrupted(event):
            original(event)
            if isinstance(
                event,
                dg.AssetMaterialization
                if stop_after == "materialization"
                else AssetCheckEvaluation,
            ):
                raise RuntimeError("simulated exit after successful native write")  # noqa: TRY004 - fault injection after persistence

        monkeypatch.setattr(instance, "report_runless_asset_event", interrupted)
        with pytest.raises(RuntimeError, match="simulated exit"):
            apply(instance, args, digest)
    with _isolated_instance(tmp_path) as instance:
        result = apply(instance, args, digest)
        expected = (1, 2) if stop_after == "materialization" else (0, 1)
        assert (result["new_materializations"], result["new_checks"]) == expected
        assert len(list((root / "events").rglob("*.json"))) == 1
        assert apply(instance, args, digest)["new_checks"] == 0


def test_subset_first_then_remaining_month_reuses_same_approval(tmp_path, monkeypatch):
    days = (DAY, date(2019, 10, 17), date(2019, 11, 1))
    args, _ = prepare(tmp_path, days)
    with _isolated_instance(tmp_path) as instance:
        _, digest = E.plan_stk_factor_pro_bootstrap_events(instance=instance, **args)
        reads = []
        reader = E.read_stk_factor_pro_bootstrap_publication

        def selected(**kwargs):
            reads.append(kwargs["trade_date"])
            return reader(**kwargs)

        monkeypatch.setattr(E, "read_stk_factor_pro_bootstrap_publication", selected)
        first = apply(instance, args, digest, (DAY,))
        assert (first["new_materializations"], first["new_checks"]) == (2, 2)
        assert set(reads) == {DAY}
        reads.clear()
        rest = apply(instance, args, digest, days[1:])
        assert (rest["new_materializations"], rest["new_checks"]) == (4, 4)
        assert set(reads) == set(days[1:])


def test_latest_planned_and_cross_pairs_use_real_partitioned_storage(tmp_path):
    args, _ = prepare(tmp_path)
    with _isolated_instance(tmp_path) as instance:
        for layer, _, _ in LAYERS:
            seed(instance, args, layer=layer)
        # These are deliberately wrong pairs and outside the selected date.
        report_check(
            instance,
            AssetCheckEvaluation(
                asset_key=dg.AssetKey(C.STK_FACTOR_PRO_RAW_ASSET_KEY),
                check_name=C.STK_FACTOR_PRO_SILVER_CHECK_NAME,
                partition=str(DAY),
                passed=False,
            ),
        )
        report_check(
            instance,
            AssetCheckEvaluation(
                asset_key=dg.AssetKey(C.STK_FACTOR_PRO_RAW_ASSET_KEY),
                check_name=C.STK_FACTOR_PRO_RAW_CHECK_NAME,
                partition="2019-10-15",
                passed=False,
            ),
        )
        assert set(E._checks(instance, (DAY,))) == {(DAY, "raw"), (DAY, "silver")}
        assert not E.plan_stk_factor_pro_bootstrap_events(instance=instance, **args)[
            0
        ].conflicts
        report_check(
            instance,
            AssetCheckEvaluationPlanned(
                asset_key=dg.AssetKey(C.STK_FACTOR_PRO_RAW_ASSET_KEY),
                check_name=C.STK_FACTOR_PRO_RAW_CHECK_NAME,
                partitions_subset=dg.DynamicPartitionsDefinition(
                    name=C.STK_FACTOR_PRO_PARTITIONS
                ).subset_with_partition_keys([str(DAY)]),
            ),
            planned=True,
        )
        latest = E._checks(instance, (DAY,))
        assert latest[DAY, "raw"].status.value == "PLANNED"
        plan, digest = E.plan_stk_factor_pro_bootstrap_events(instance=instance, **args)
        assert plan.conflicts == ((DAY, "raw", "最新check失败、等待或绑定不符"),)
        with pytest.raises(ValueError, match="冲突"):
            apply(instance, args, digest)


@pytest.mark.parametrize("wrong", ["run_id", "timestamp", "orphan"])
def test_bad_target_identity_and_orphan_check_are_conflicts(tmp_path, wrong):
    args, _ = prepare(tmp_path)
    with _isolated_instance(tmp_path) as instance:
        material = None if wrong == "orphan" else seed(instance, args, check=False)
        target = (
            None
            if material is None
            else AssetCheckEvaluationTargetMaterializationData(
                storage_id=material.storage_id,
                run_id="wrong-run"
                if wrong == "run_id"
                else material.event_log_entry.run_id,
                timestamp=material.timestamp + int(wrong == "timestamp"),
            )
        )
        report_check(
            instance,
            AssetCheckEvaluation(
                asset_key=dg.AssetKey(C.STK_FACTOR_PRO_RAW_ASSET_KEY),
                check_name=C.STK_FACTOR_PRO_RAW_CHECK_NAME,
                partition=str(DAY),
                passed=True,
                blocking=True,
                metadata=expected_metadata(args, DAY, "raw"),
                target_materialization_data=target,
            ),
        )
        plan, digest = E.plan_stk_factor_pro_bootstrap_events(instance=instance, **args)
        assert plan.conflicts
        with pytest.raises(ValueError, match="冲突"):
            apply(instance, args, digest)


@pytest.mark.parametrize(
    "changes",
    [
        {"passed": False},
        {"unknown_dates": 1},
        {"missing_count": 1},
        {"rule_version": "old"},
    ],
)
def test_failed_or_wrong_coverage_never_queries_native_history(
    tmp_path, monkeypatch, changes
):
    args, root = prepare(tmp_path)
    known = {}
    approval = R.read_json(
        root / "approval.json", C.StkFactorProBootstrapApproval, known_records=known
    )
    args["historical_coverage_ref"] = _coverage(
        root, approval, known, (DAY,), **changes
    )
    with _isolated_instance(tmp_path) as instance:
        monkeypatch.setattr(
            E, "_materials", lambda *_a, **_k: pytest.fail("coverage must stop first")
        )
        with pytest.raises(ValueError, match="覆盖验收"):
            E.plan_stk_factor_pro_bootstrap_events(instance=instance, **args)


def test_repeated_plan_is_one_record_and_approved_date_subset_is_enforced(tmp_path):
    days = (DAY, date(2019, 10, 17))
    args, root = prepare(tmp_path, days)
    with _isolated_instance(tmp_path) as instance:
        selected = {**args, "trade_dates": (DAY,)}
        first = E.plan_stk_factor_pro_bootstrap_events(instance=instance, **selected)
        assert (
            E.plan_stk_factor_pro_bootstrap_events(instance=instance, **selected)
            == first
        )
        assert len(list((root / "events").rglob("*.json"))) == 1
        with pytest.raises(ValueError, match="超出批准计划"):
            apply(instance, args, first[1], days[1:])


def test_active_dataset_job_prevents_writes_but_other_jobs_do_not(tmp_path):
    args, _ = prepare(tmp_path)
    with _isolated_instance(tmp_path) as instance:
        _, digest = E.plan_stk_factor_pro_bootstrap_events(instance=instance, **args)
        instance.create_run_for_job(
            dg.GraphDefinition(name=C.STK_FACTOR_PRO_UPDATE_JOB_NAME).to_job()
        )
        with pytest.raises(dg.Failure):
            apply(instance, args, digest)
        assert not E._materials(instance, {(DAY, "raw"), (DAY, "silver")})


def test_native_check_batch_is_one_sql_and_publication_records_read_once(
    tmp_path, monkeypatch
):
    args, _ = prepare(tmp_path)
    reads, statements = Counter(), []
    original_read = Path.read_bytes

    def read(path):
        if "publication" in path.parts:
            reads[path] += 1
        return original_read(path)

    monkeypatch.setattr(Path, "read_bytes", read)
    with _isolated_instance(tmp_path) as instance:
        original_connection = instance.event_log_storage.index_connection

        def observed(_conn, _cursor, statement, _parameters, _context, _many):
            if (
                statement.lstrip().startswith("SELECT")
                and "asset_check_executions" in statement
            ):
                statements.append(statement)

        @contextmanager
        def connected():
            with original_connection() as conn:
                sa.event.listen(conn, "before_cursor_execute", observed)
                try:
                    yield conn
                finally:
                    sa.event.remove(conn, "before_cursor_execute", observed)

        monkeypatch.setattr(instance.event_log_storage, "index_connection", connected)
        _, digest = E.plan_stk_factor_pro_bootstrap_events(instance=instance, **args)
        assert len(statements) == 1
        assert len(reads) == 4 and set(reads.values()) == {1}
        reads.clear()
        statements.clear()
        apply(instance, args, digest)
        assert len(statements) == 2  # current latest checks, then written checks
        assert len(reads) == 4 and set(reads.values()) == {1}
        assert all("GROUP BY" in sql and "max(" in sql for sql in statements)


@pytest.mark.parametrize(
    "source",
    [
        {
            "goldenshare/day_source_digest": "a" * 64,
            "goldenshare/scope_digest": "b" * 64,
            "goldenshare/source_manifest_digest": None,
        },
        {"goldenshare/source_manifest_digest": "c" * 64},
    ],
)
def test_extracted_metadata_keeps_day_and_history_literal_contract(tmp_path, source):
    args, root = prepare(tmp_path)
    for layer, _, _ in LAYERS:
        value = json.loads(
            (root / f"publication/{DAY}/{layer}/complete.json").read_bytes()
        )
        audit = C.parse_stk_factor_pro_record(C.StkFactorProFileAudit, value["audit"])
        expected = {**expected_metadata(args, DAY, layer), **source}
        actual = C.build_stk_factor_pro_publication_metadata(
            audit,
            raw_file_sha256=expected.get("goldenshare/raw_sha256"),
            source_metadata=source,
        )
        assert {
            key: getattr(value, "value", value) for key, value in actual.items()
        } == expected


@pytest.mark.parametrize(
    "problem",
    [
        "unaccepted",
        "empty",
        "missing_file",
        "missing_record",
        "plan_sha",
        "changed_approval",
    ],
)
def test_invalid_input_does_not_start_event_writes(tmp_path, problem):
    args, root = prepare(tmp_path)
    with _isolated_instance(tmp_path) as instance:
        _, digest = E.plan_stk_factor_pro_bootstrap_events(instance=instance, **args)
        if problem == "missing_file":
            raw_stk_factor_pro_path(args["lake_root"], str(DAY)).unlink()
        elif problem == "missing_record":
            (root / f"publication/{DAY}/raw/complete.json").unlink()
        elif problem == "plan_sha":
            path = root / f"events/plans/{digest}.json"
            path.write_bytes(path.read_bytes() + b" ")
        elif problem == "changed_approval":
            path = root / "approval.json"
            known = {}
            value = R.read_json(
                path, C.StkFactorProBootstrapApproval, known_records=known
            )
            R.write_json(
                path,
                replace(value, source_statement_timeout_ms=15000),
                known_records=known,
                mutable=True,
            )
        days = (
            ()
            if problem == "empty"
            else (date(2019, 10, 18),)
            if problem == "unaccepted"
            else None
        )
        with pytest.raises(ValueError):
            apply(instance, args, digest, days)
        assert not E._materials(instance, {(DAY, "raw"), (DAY, "silver")})


def test_empty_month_no_queries_and_query_counts_reuse_held_materializations(
    tmp_path, monkeypatch
):
    args, _ = prepare(tmp_path)
    with _isolated_instance(tmp_path) as instance:
        storage = instance.event_log_storage
        counts = Counter()
        for obj, name in (
            (storage, "get_latest_storage_id_by_partition"),
            (instance, "fetch_materializations"),
            (E, "_checks"),
        ):
            original = getattr(obj, name)

            def counted(*a, _name=name, _original=original, **k):
                counts[_name] += 1
                return _original(*a, **k)

            monkeypatch.setattr(obj, name, counted)
        assert E._materials(instance, ()) == {} and E._checks(instance, ()) == {}
        assert counts == {"_checks": 1}  # Internal check helper returns before SQL.
        counts.clear()
        _, digest = E.plan_stk_factor_pro_bootstrap_events(instance=instance, **args)
        assert counts == {"get_latest_storage_id_by_partition": 2, "_checks": 1}
        counts.clear()
        apply(instance, args, digest)
        assert counts == {
            "get_latest_storage_id_by_partition": 4,
            "fetch_materializations": 2,
            "_checks": 2,
        }
        counts.clear()
        apply(instance, args, digest)
        assert counts == {
            "get_latest_storage_id_by_partition": 2,
            "fetch_materializations": 2,
            "_checks": 1,
        }
