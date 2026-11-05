"""LLD 5.4 literal Parquet/JSON producers; all files are temporary and offline."""

import json
import os
from collections import Counter
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from orchestrator.defs.checks.stk_factor_pro import (
    factor_file_identity,
    factor_file_sha,
    require_factor_history_relation,
)
from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.io import stk_factor_pro_history as records
from orchestrator.defs.io.stk_factor_pro_candidates import HISTORY_SOURCE
from orchestrator.defs.io.stk_factor_pro_download import (
    release_stk_factor_pro_history_source,
)
from orchestrator.defs.run_contracts import stk_factor_pro as models
from tests.stk_factor_pro_history_test_support import (
    check_test_space,
    roots,
    write_factor_file,
)
from tests.stk_factor_pro_test_support import NAMES, connection, contract, identity

T, P, START = date(2026, 10, 16), date(2026, 10, 15), date(2026, 10, 14)
NOW = datetime(2026, 10, 16, 19, 0, tzinfo=timezone(timedelta(hours=8)))
SHA = "a" * 64


def test_builder_passes_first_business_digests_to_record_writer(tmp_path, monkeypatch):
    """A calculated plan is saved by the same body without validating it twice."""
    known_records, calls = {}, Counter()
    lake, staging = roots(tmp_path)
    original_ranges = records.stk_factor_pro_history_ranges_digest
    original_plan = records.stk_factor_pro_history_plan_digest

    def range_digest(rows):
        calls["ranges"] += 1
        return original_ranges(rows)

    def plan_digest(*args, **kwargs):
        calls["plan"] += 1
        return original_plan(*args, **kwargs)

    monkeypatch.setattr(records, "stk_factor_pro_history_ranges_digest", range_digest)
    monkeypatch.setattr(records, "stk_factor_pro_history_plan_digest", plan_digest)
    with connection(tmp_path) as conn:
        factor_t = write_factor_file(conn, lake, T, (("000001.SZ", 2.0),))
        factor_p = write_factor_file(conn, lake, P, (("000001.SZ", 1.0),))
        factor_relations, lifecycle_relation = (
            records.prepare_stk_factor_pro_history_inputs(
                conn,
                identity=identity(),
                lake_root=lake,
                factor_t=factor_t,
                factor_p=factor_p,
                known_records=known_records,
                check_cancel=lambda: None,
            )
        )
        plan, planned_ranges, reference = records.build_stk_factor_pro_history_plan(
            conn,
            identity=identity(),
            contract=contract(),
            lake_root=lake,
            staging_root=staging,
            factor_t=factor_t,
            factor_p=factor_p,
            factor_relations=factor_relations,
            factor_comparison=records.compare_stk_factor_pro_history_factors(
                conn, factor_relations=factor_relations
            ),
            lifecycle_relation=lifecycle_relation,
            prior_results=models.StkFactorProRecordedResults(
                T, None, None, None, None, None, None, (), (), None, None
            ),
            prior_history=records.read_stk_factor_pro_prior_history(
                conn,
                staging_root=staging,
                target=(identity()).target_trade_date,
                contract=contract(),
                prior=models.StkFactorProRecordedResults(
                    T, None, None, None, None, None, None, (), (), None, None
                ),
                known_records=known_records,
            ),
            history_starts=(
                models.StkFactorProHistoryStart("000001.SZ", START, 1, START),
            ),
            check_cancel=lambda: None,
            known_records=known_records,
        )
        assert [
            (item.ts_code, item.start_date, item.end_date) for item in planned_ranges
        ] == [("000001.SZ", START, T)]
        root = root_for(tmp_path)
        assert (
            records.read_stk_factor_pro_history_plan(
                root,
                expected_target=T,
                expected_run_id="run-a",
                known_records=known_records,
            )
            is plan
        )
        assert (
            records.read_stk_factor_pro_history_ranges(
                conn, root=root, plan=plan, known_records=known_records
            )
            is planned_ranges
        )
        assert reference.file_sha256 == known_records[root / "history-plan.json"][1]

        def no_reader(*args, **kwargs):
            pytest.fail("unit resolver reopened an already handed-off plan or range")

        monkeypatch.setattr(records, "read_stk_factor_pro_history_plan", no_reader)
        monkeypatch.setattr(records, "read_stk_factor_pro_history_ranges", no_reader)
        units = records.resolve_stk_factor_pro_history_units(
            conn,
            plan=plan,
            ranges=planned_ranges,
            prior_results=models.StkFactorProRecordedResults(
                T, None, None, None, None, None, None, (), (), None, None
            ),
            staging_root=staging,
            known_records=known_records,
        )
        assert [
            (item.object_code, item.start_date, item.end_date) for item in units
        ] == [("000001.SZ", START, T)]
        assert records.plan_stk_factor_pro_history_publication_dates(
            identity=identity(),
            expected_units=units,
            calendar=(START, P, T),
            registered_dates=(START, P, T),
        ) == (START, P)
        records.release_stk_factor_pro_history_inputs(conn)
    assert calls == {"ranges": 1, "plan": 1}


def test_written_records_keep_first_payload_and_parquet_facts(tmp_path, monkeypatch):
    """LLD18: a writer hands its actual persisted facts to same-task consumers."""
    known_records, hashes, json_reads = {}, Counter(), []
    original_hash, original_read = records.factor_file_sha, Path.read_bytes

    def count_hash(path):
        hashes[Path(path)] += 1
        return original_hash(path)

    def read_bytes(path):
        if path.suffix == ".json":
            json_reads.append(path)
        return original_read(path)

    monkeypatch.setattr(records, "factor_file_sha", count_hash)
    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    root = root_for(tmp_path)
    with connection(tmp_path) as conn:
        plan, source, _, _ = save_source(conn, root, known_records=known_records)
        assert (
            records.read_stk_factor_pro_history_plan(
                root,
                expected_target=T,
                expected_run_id="run-a",
                known_records=known_records,
            )
            is plan
        )
        assert (
            records.read_stk_factor_pro_history_ranges(
                conn, root=root, plan=plan, known_records=known_records
            )
            == ranges()
        )
        manifest = records.read_stk_factor_pro_source_files(
            root,
            source.files_manifest_ref,
            connection=conn,
            identity=identity(),
            contract=contract(),
            known_records=known_records,
        )
        assert len(manifest) == 1
        assert (
            records._json_read(
                root / "source/history/source-complete.json",
                models.SourceCompleteRecord,
                known_records=known_records,
            )
            is source
        )
    assert json_reads == []
    assert hashes == {
        root / "history-ranges.parquet.tmp": 1,
        root / "source/history/source-files.parquet.tmp": 1,
    }


def test_fresh_record_reader_reads_bytes_and_parquet_only_once(tmp_path, monkeypatch):
    """New execution reads an old record once; later consumers receive that object."""
    root, written = root_for(tmp_path), {}
    with connection(tmp_path) as conn:
        plan, _ = records.write_stk_factor_pro_history_plan(
            root, new_plan(), ranges(), connection=conn, known_records=written
        )
        known_records, reads, hashes, parses = {}, Counter(), Counter(), Counter()
        original_read, original_hash = Path.read_bytes, records.factor_file_sha
        original_parse = records.parse_stk_factor_pro_record

        def read_bytes(path):
            reads[path] += 1
            return original_read(path)

        def hash_file(path):
            hashes[path] += 1
            return original_hash(path)

        def parse(kind, value):
            parses[kind] += 1
            return original_parse(kind, value)

        monkeypatch.setattr(Path, "read_bytes", read_bytes)
        monkeypatch.setattr(records, "factor_file_sha", hash_file)
        monkeypatch.setattr(records, "parse_stk_factor_pro_record", parse)
        first = records.read_stk_factor_pro_history_plan(
            root,
            expected_target=T,
            expected_run_id="run-a",
            known_records=known_records,
        )
        second = records.read_stk_factor_pro_history_plan(
            root,
            expected_target=T,
            expected_run_id="run-a",
            known_records=known_records,
        )
        assert first is second and first == plan
        first_ranges = records.read_stk_factor_pro_history_ranges(
            conn, root=root, plan=first, known_records=known_records
        )
        assert (
            records.read_stk_factor_pro_history_ranges(
                conn, root=root, plan=second, known_records=known_records
            )
            is first_ranges
        )
        assert first_ranges == ranges()
        assert reads == {root / "history-plan.json": 1}
        assert hashes == {root / "history-ranges.parquet": 1}
        assert parses[models.HistoryPlanRecord] == 1


def root_for(tmp_path):
    return tmp_path / "staging" / "stk_factor_pro" / f"trade_date={T}" / "run_id=run-a"


def source_fact_arguments(root, source, known_records):
    files = known_records[root / source.files_manifest_ref.relative_path][0]
    return {
        "source_relation": HISTORY_SOURCE,
        "verified_files": files,
        "file_identities": tuple(
            (file.file_relative_path, known_records[root / file.file_relative_path][2])
            for file in files
        ),
    }


def ranges():
    return (
        models.HistoryRange(
            "000001.SZ", True, True, 2.0, 1.0, START, T, (1,), (T,), (), 1, START
        ),
    )


def new_plan():
    rows = ranges()
    return models.HistoryPlanRecord(
        1,
        identity(),
        contract(),
        1,
        NOW,
        models.stk_factor_pro_history_plan_digest(
            identity(),
            contract(),
            rows,
            ranges_digest=models.stk_factor_pro_history_ranges_digest(rows),
        ),
        models.stk_factor_pro_history_ranges_digest(rows),
        models.RecordRef("run-a", "history-ranges.parquet", "0" * 64),
        1,
        models.FactorFileRef(T, "raw_tushare_adj_factor", SHA, 1),
        models.FactorFileRef(P, "raw_tushare_adj_factor", SHA, 1),
        None,
        None,
        None,
        None,
    )


def save_source(conn, root, *, kind="normal", source_contract=None, known_records):
    source_contract = contract() if source_contract is None else source_contract
    initial_plan = replace(
        new_plan(),
        contract=source_contract,
        history_plan_digest=models.stk_factor_pro_history_plan_digest(
            identity(),
            source_contract,
            ranges(),
            ranges_digest=models.stk_factor_pro_history_ranges_digest(ranges()),
        ),
    )
    plan, plan_sha = records.write_stk_factor_pro_history_plan(
        root, initial_plan, ranges(), connection=conn, known_records=known_records
    )
    unit = models.UnitProjection(5, "000001.SZ", None, START, T)
    key = models.stk_factor_pro_unit_key(unit)
    path = root / "source" / "history" / "units" / f"{key}.parquet"
    path.parent.mkdir(parents=True)
    code = "600000.SH" if kind == "wrong_code" else "000001.SZ"
    day = "20261013" if kind == "wrong_date" else "20261014"
    values = []
    for name in NAMES:
        if name == "ts_code":
            value = f"'{code}'::VARCHAR"
        elif name == "trade_date":
            value = "DATE '2026-10-14'" if kind == "wrong_type" else f"'{day}'::VARCHAR"
        elif name == "close":
            value = "CAST('NaN' AS DOUBLE)" if kind == "nonfinite" else "10.0::DOUBLE"
        elif name == "pe":
            value = "NULL::DOUBLE"
        else:
            value = "-1.25::DOUBLE"
        if kind != "missing_column" or name != NAMES[-1]:
            values.append(f'{value} AS "{name}"')
    query = "SELECT " + ",".join(values)
    if kind == "duplicate":
        query = f"({query}) UNION ALL ({query})"
    if kind == "empty":
        query += " WHERE false"
    conn.execute(copy_query_to_parquet(query, path))
    count = 0 if kind == "empty" else 2 if kind in ("duplicate", "wrong_count") else 1
    conn.execute(
        f"CREATE TEMP TABLE {HISTORY_SOURCE} AS SELECT * FROM read_parquet(?,hive_partitioning=false)",
        [str(path)],
    )
    try:
        actual_count, _ = require_factor_history_relation(
            conn, HISTORY_SOURCE, object_code="000001.SZ", start_date=START, end_date=T
        )
        if actual_count != count:
            raise ValueError("首次历史源实际行数与规划统计不符")
    except BaseException:
        conn.execute(f"DROP TABLE {HISTORY_SOURCE}")
        raise
    file = models.SourceFileRecord(
        "history",
        key,
        "native-unit-id",
        0,
        5,
        "000001.SZ",
        None,
        START,
        T,
        count,
        count,
        f"source/history/units/{key}.parquet",
        factor_file_sha(path),
        count,
        models.stk_factor_pro_schema_digest("raw"),
        source_contract.contract_content_digest,
        NOW,
    )
    known_records[path] = (file, file.file_sha256, factor_file_identity(path))
    manifest_ref = records.write_stk_factor_pro_source_files(
        root,
        connection=conn,
        identity=identity(),
        contract=source_contract,
        files=(file,),
        known_records=known_records,
        check_space=check_test_space,
    )
    scope = models.stk_factor_pro_scope_digest("history", T, (unit,))
    source = models.SourceCompleteRecord(
        1,
        identity(),
        "history",
        source_contract,
        models.RecordRef("run-a", "history-plan.json", plan_sha),
        plan.history_plan_digest,
        1,
        None,
        None,
        models.stk_factor_pro_history_input_digest(
            identity(), source_contract, (unit,), ranges()
        ),
        scope,
        (unit,),
        manifest_ref,
        models.stk_factor_pro_files_manifest_digest(scope, (file,)),
        1,
        NOW,
    )
    records.write_stk_factor_pro_source_complete(
        root, source, known_records=known_records, check_space=check_test_space
    )
    return plan, source, unit, path


def test_plan_returns_actual_ranges_reference_and_complete_roundtrip(tmp_path):
    known_records = {}
    root = root_for(tmp_path)
    before = new_plan()
    with connection(tmp_path) as conn:
        saved, _ = records.write_stk_factor_pro_history_plan(
            root, before, ranges(), connection=conn, known_records=known_records
        )
        assert before.ranges_ref.file_sha256 == "0" * 64
        assert saved.ranges_ref.file_sha256 == factor_file_sha(
            root / "history-ranges.parquet"
        )
        assert saved.ranges_ref != before.ranges_ref
        assert (
            records.read_stk_factor_pro_history_ranges(
                conn, root=root, plan=saved, known_records=known_records
            )
            == ranges()
        )
        assert (
            records.read_stk_factor_pro_history_plan(
                root,
                expected_target=T,
                expected_run_id="run-a",
                known_records=known_records,
            )
            == saved
        )
        assert conn.execute("SHOW TABLES").fetchall() == []
        with pytest.raises(ValueError, match="已存在"):
            records.write_stk_factor_pro_history_plan(
                root, before, ranges(), connection=conn, known_records=known_records
            )
        assert (
            factor_file_sha(root / "history-ranges.parquet")
            == saved.ranges_ref.file_sha256
        )


def test_ranges_schema_is_independent_twelve_column_contract_and_empty_supported(
    tmp_path,
):
    # Literal expected schema comes from LLD 5.4.3, not HISTORY_RANGE_SCHEMA.
    known_records = {}
    expected = (
        ("ts_code", "VARCHAR"),
        ("t_present", "BOOLEAN"),
        ("p_present", "BOOLEAN"),
        ("t_value", "DOUBLE"),
        ("p_value", "DOUBLE"),
        ("start_date", "DATE"),
        ("end_date", "DATE"),
        ("plan_reasons", "INTEGER[]"),
        ("origin_target_dates", "DATE[]"),
        ("origin_record_refs", "VARCHAR"),
        ("earliest_basis_kind", "INTEGER"),
        ("earliest_basis_date", "DATE"),
    )
    plan = replace(
        new_plan(),
        full_code_count=0,
        history_ranges_digest=models.stk_factor_pro_history_ranges_digest(()),
        history_plan_digest=models.stk_factor_pro_history_plan_digest(
            identity(),
            contract(),
            (),
            ranges_digest=models.stk_factor_pro_history_ranges_digest(()),
        ),
    )
    with connection(tmp_path) as conn:
        saved, _ = records.write_stk_factor_pro_history_plan(
            root_for(tmp_path), plan, (), connection=conn, known_records=known_records
        )
        path = root_for(tmp_path) / "history-ranges.parquet"
        assert (
            tuple(
                (r[0], r[1])
                for r in conn.execute(
                    "DESCRIBE SELECT * FROM read_parquet(?,hive_partitioning=false)",
                    [str(path)],
                ).fetchall()
            )
            == expected
        )
        assert (
            records.read_stk_factor_pro_history_ranges(
                conn, root=root_for(tmp_path), plan=saved, known_records=known_records
            )
            == ()
        )
        assert conn.execute("SHOW TABLES").fetchall() == []


@pytest.mark.parametrize("kind", ["normal", "empty"])
def test_verify_current_source_real_rows_or_complete_empty_schema(tmp_path, kind):
    known_records = {}
    with connection(tmp_path) as conn:
        _, source, unit, _ = save_source(
            conn, root_for(tmp_path), kind=kind, known_records=known_records
        )
        verified = records.verify_stk_factor_pro_current_source(
            root_for(tmp_path),
            source,
            connection=conn,
            current_run_id="run-a",
            expected_units=(unit,),
            known_records=known_records,
            **source_fact_arguments(root_for(tmp_path), source, known_records),
            source_complete_ref=models.RecordRef(
                "run-a",
                "source/history/source-complete.json",
                known_records[
                    root_for(tmp_path) / "source/history/source-complete.json"
                ][1],
            ),
        )
        assert verified.source_complete == source
        assert verified.source_complete_ref.file_sha256 == factor_file_sha(
            root_for(tmp_path) / "source/history/source-complete.json"
        )
        assert conn.execute(f"SELECT count(*) FROM {HISTORY_SOURCE}").fetchone()[0] == (
            0 if kind == "empty" else 1
        )
        release_stk_factor_pro_history_source(conn)
        assert conn.execute("SHOW TABLES").fetchall() == []


@pytest.mark.parametrize(
    "kind",
    [
        "wrong_code",
        "wrong_date",
        "wrong_type",
        "missing_column",
        "nonfinite",
        "duplicate",
        "wrong_count",
    ],
)
def test_first_source_audit_rejects_invalid_actual_contract_before_complete(
    tmp_path, kind
):
    known_records = {}
    with connection(tmp_path) as conn:
        with pytest.raises(ValueError):
            save_source(
                conn, root_for(tmp_path), kind=kind, known_records=known_records
            )
        assert not (root_for(tmp_path) / "source/history/source-complete.json").exists()
        assert conn.execute("SHOW TABLES").fetchall() == []


def test_plan_business_digest_tampering_rejected_before_writes(tmp_path):
    known_records = {}
    with connection(tmp_path) as conn, pytest.raises(ValueError, match="业务摘要"):
        records.write_stk_factor_pro_history_plan(
            root_for(tmp_path),
            replace(new_plan(), history_plan_digest=SHA),
            ranges(),
            connection=conn,
            known_records=known_records,
        )
    assert not root_for(tmp_path).exists()


def test_complete_source_cross_identity_rejected_even_same_run_and_t(tmp_path):
    known_records = {}
    with connection(tmp_path) as conn:
        _, source, unit, _ = save_source(
            conn, root_for(tmp_path), known_records=known_records
        )
        changed = replace(
            source, identity=replace(source.identity, source_run_id="other-intent")
        )
        path = root_for(tmp_path) / "source/history/source-complete.json"
        path.write_text(json.dumps(models.stk_factor_pro_record_to_dict(changed)))
        known_records.pop(path, None)
        records._json_read(
            path, models.SourceCompleteRecord, known_records=known_records
        )
        with pytest.raises(ValueError, match="计划"):
            records.verify_stk_factor_pro_current_source(
                root_for(tmp_path),
                changed,
                connection=conn,
                current_run_id="run-a",
                expected_units=(unit,),
                known_records=known_records,
                **source_fact_arguments(root_for(tmp_path), source, known_records),
                source_complete_ref=models.RecordRef(
                    "run-a",
                    "source/history/source-complete.json",
                    known_records[
                        root_for(tmp_path) / "source/history/source-complete.json"
                    ][1],
                ),
            )


def test_wrong_run_and_unplanned_units_rejected(tmp_path):
    known_records = {}
    with connection(tmp_path) as conn:
        _, source, unit, _ = save_source(
            conn, root_for(tmp_path), known_records=known_records
        )
        for run_id, units in (("another-run", (unit,)), ("run-a", ())):
            with pytest.raises(ValueError, match="当前run"):
                records.verify_stk_factor_pro_current_source(
                    root_for(tmp_path),
                    source,
                    connection=conn,
                    current_run_id=run_id,
                    expected_units=units,
                    known_records=known_records,
                    **source_fact_arguments(root_for(tmp_path), source, known_records),
                    source_complete_ref=models.RecordRef(
                        "run-a",
                        "source/history/source-complete.json",
                        known_records[
                            root_for(tmp_path) / "source/history/source-complete.json"
                        ][1],
                    ),
                )


def test_json_unknown_field_and_bad_ranges_sha_rejected(tmp_path):
    known_records = {}
    with connection(tmp_path) as conn:
        saved, _ = records.write_stk_factor_pro_history_plan(
            root_for(tmp_path),
            new_plan(),
            ranges(),
            connection=conn,
            known_records=known_records,
        )
        with pytest.raises(ValueError, match="SHA"):
            records.read_stk_factor_pro_history_ranges(
                conn,
                root=root_for(tmp_path),
                plan=replace(
                    saved, ranges_ref=replace(saved.ranges_ref, file_sha256="0" * 64)
                ),
                known_records=known_records,
            )
        path = root_for(tmp_path) / "history-plan.json"
        value = json.loads(path.read_text())
        value["unexpected"] = 1
        path.write_text(json.dumps(value))
        known_records.pop(path, None)
        with pytest.raises(ValueError, match="未知"):
            records.read_stk_factor_pro_history_plan(
                root_for(tmp_path),
                expected_target=T,
                expected_run_id="run-a",
                known_records=known_records,
            )


@pytest.mark.parametrize("dangling", [False, True])
def test_ranges_symlink_rejected_before_any_external_write(tmp_path, dangling):
    known_records = {}
    root, outside = root_for(tmp_path), tmp_path / "outside.parquet"
    root.mkdir(parents=True)
    if not dangling:
        outside.write_bytes(b"external file must survive")
    (root / "history-ranges.parquet").symlink_to(outside)
    with connection(tmp_path) as conn, pytest.raises(ValueError, match="路径"):
        records.write_stk_factor_pro_history_plan(
            root, new_plan(), ranges(), connection=conn, known_records=known_records
        )
    assert outside.exists() is (not dangling)
    if not dangling:
        assert outside.read_bytes() == b"external file must survive"
    assert not (root / "history-plan.json").exists()


def test_ranges_updated_sha_does_not_hide_extra_schema_column(tmp_path):
    known_records = {}
    with connection(tmp_path) as conn:
        plan, _ = records.write_stk_factor_pro_history_plan(
            root_for(tmp_path),
            new_plan(),
            ranges(),
            connection=conn,
            known_records=known_records,
        )
        path = root_for(tmp_path) / "history-ranges.parquet"
        changed = path.with_suffix(".bad.parquet")
        conn.execute(
            copy_query_to_parquet(
                f"SELECT *,1 AS unexpected FROM read_parquet('{path}',hive_partitioning=false)",
                changed,
            )
        )
        os.replace(changed, path)
        known_records.pop(path, None)
        plan = replace(
            plan, ranges_ref=replace(plan.ranges_ref, file_sha256=factor_file_sha(path))
        )
        with pytest.raises(ValueError, match="列名"):
            records.read_stk_factor_pro_history_ranges(
                conn, root=root_for(tmp_path), plan=plan, known_records=known_records
            )


def test_manifest_wrong_integer_type_rejected_even_with_actual_new_sha(tmp_path):
    known_records = {}
    with connection(tmp_path) as conn:
        _, source, _, _ = save_source(
            conn, root_for(tmp_path), known_records=known_records
        )
        path = root_for(tmp_path) / source.files_manifest_ref.relative_path
        changed = path.with_suffix(".bad.parquet")
        conn.execute(
            copy_query_to_parquet(
                f"SELECT * REPLACE (CAST(mode AS DOUBLE) AS mode) FROM read_parquet('{path}',hive_partitioning=false)",
                changed,
            )
        )
        os.replace(changed, path)
        known_records.pop(path, None)
        ref = replace(source.files_manifest_ref, file_sha256=factor_file_sha(path))
        with pytest.raises(ValueError, match="类型"):
            records.read_stk_factor_pro_source_files(
                root_for(tmp_path),
                ref,
                connection=conn,
                identity=identity(),
                contract=contract(),
                known_records=known_records,
            )


def test_current_source_symlink_and_changed_unit_bytes_rejected(tmp_path):
    known_records = {}
    with connection(tmp_path) as conn:
        _, source, unit, path = save_source(
            conn, root_for(tmp_path), known_records=known_records
        )
        outside = tmp_path / "external-source.parquet"
        os.replace(path, outside)
        path.symlink_to(outside)
        with pytest.raises(ValueError, match="路径"):
            records.verify_stk_factor_pro_current_source(
                root_for(tmp_path),
                source,
                connection=conn,
                current_run_id="run-a",
                expected_units=(unit,),
                known_records=known_records,
                **source_fact_arguments(root_for(tmp_path), source, known_records),
                source_complete_ref=models.RecordRef(
                    "run-a",
                    "source/history/source-complete.json",
                    known_records[
                        root_for(tmp_path) / "source/history/source-complete.json"
                    ][1],
                ),
            )
        path.unlink()
        os.replace(outside, path)
        with path.open("ab") as stream:
            stream.write(b"changed after manifest")
        with pytest.raises(ValueError, match="identity"):
            records.verify_stk_factor_pro_current_source(
                root_for(tmp_path),
                source,
                connection=conn,
                current_run_id="run-a",
                expected_units=(unit,),
                known_records=known_records,
                **source_fact_arguments(root_for(tmp_path), source, known_records),
                source_complete_ref=models.RecordRef(
                    "run-a",
                    "source/history/source-complete.json",
                    known_records[
                        root_for(tmp_path) / "source/history/source-complete.json"
                    ][1],
                ),
            )


def test_duplicate_json_field_is_not_silently_replaced(tmp_path):
    known_records = {}
    with connection(tmp_path) as conn:
        records.write_stk_factor_pro_history_plan(
            root_for(tmp_path),
            new_plan(),
            ranges(),
            connection=conn,
            known_records=known_records,
        )
        path = root_for(tmp_path) / "history-plan.json"
        path.write_text(path.read_text()[:-1] + ',"record_version":1}')
        known_records.pop(path, None)
        with pytest.raises(ValueError, match="重复"):
            records.read_stk_factor_pro_history_plan(
                root_for(tmp_path),
                expected_target=T,
                expected_run_id="run-a",
                known_records=known_records,
            )


def test_failed_parquet_copy_cleans_only_own_temporary_relations(tmp_path):
    known_records = {}

    class CopyFailure:
        def __init__(self, conn):
            self.conn = conn

        def execute(self, sql, *args):
            if sql.startswith("COPY"):
                raise OSError("controlled COPY failure")
            return self.conn.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self.conn, name)

    with connection(tmp_path) as conn:
        conn.execute("CREATE TEMP TABLE unrelated AS SELECT 1 AS value")
        with pytest.raises(OSError, match="controlled COPY"):
            records.write_stk_factor_pro_history_plan(
                root_for(tmp_path),
                new_plan(),
                ranges(),
                connection=CopyFailure(conn),
                known_records=known_records,
            )
        assert conn.execute("SHOW TABLES").fetchall() == [("unrelated",)]
        assert not (root_for(tmp_path) / "history-plan.json").exists()
        assert not (root_for(tmp_path) / "history-ranges.parquet").exists()


def test_all_metadata_agree_but_not_current_contract_is_rejected(tmp_path):
    known_records = {}
    wrong = replace(contract(), contract_content_digest="f" * 64)
    with connection(tmp_path) as conn:
        _, source, unit, _ = save_source(
            conn, root_for(tmp_path), source_contract=wrong, known_records=known_records
        )
        assert source.contract == wrong
        with pytest.raises(ValueError, match="当前登记契约"):
            records.verify_stk_factor_pro_current_source(
                root_for(tmp_path),
                source,
                connection=conn,
                current_run_id="run-a",
                expected_units=(unit,),
                known_records=known_records,
                **source_fact_arguments(root_for(tmp_path), source, known_records),
                source_complete_ref=models.RecordRef(
                    "run-a",
                    "source/history/source-complete.json",
                    known_records[
                        root_for(tmp_path) / "source/history/source-complete.json"
                    ][1],
                ),
            )


def test_multirow_ranges_read_order_is_explicit_not_physical(tmp_path):
    known_records = {}
    rows = (ranges()[0], replace(ranges()[0], ts_code="600000.SH"))
    plan = replace(
        new_plan(),
        full_code_count=2,
        history_ranges_digest=models.stk_factor_pro_history_ranges_digest(rows),
        history_plan_digest=models.stk_factor_pro_history_plan_digest(
            identity(),
            contract(),
            rows,
            ranges_digest=models.stk_factor_pro_history_ranges_digest(rows),
        ),
    )
    with connection(tmp_path) as conn:
        saved, _ = records.write_stk_factor_pro_history_plan(
            root_for(tmp_path), plan, rows, connection=conn, known_records=known_records
        )
        path = root_for(tmp_path) / "history-ranges.parquet"
        changed = path.with_suffix(".reordered.parquet")
        conn.execute(
            copy_query_to_parquet(
                f"SELECT * FROM read_parquet('{path}',hive_partitioning=false) ORDER BY ts_code DESC",
                changed,
            )
        )
        os.replace(changed, path)
        known_records.pop(path, None)
        saved = replace(
            saved,
            ranges_ref=replace(saved.ranges_ref, file_sha256=factor_file_sha(path)),
        )
        assert (
            records.read_stk_factor_pro_history_ranges(
                conn, root=root_for(tmp_path), plan=saved, known_records=known_records
            )
            == rows
        )
        changed = path.with_suffix(".duplicate.parquet")
        conn.execute(
            copy_query_to_parquet(
                f"(SELECT * FROM read_parquet('{path}',hive_partitioning=false)) UNION ALL (SELECT * FROM read_parquet('{path}',hive_partitioning=false) WHERE ts_code='000001.SZ')",
                changed,
            )
        )
        os.replace(changed, path)
        known_records.pop(path, None)
        saved = replace(
            saved,
            ranges_ref=replace(saved.ranges_ref, file_sha256=factor_file_sha(path)),
        )
        with pytest.raises(ValueError, match="唯一代码"):
            records.read_stk_factor_pro_history_ranges(
                conn, root=root_for(tmp_path), plan=saved, known_records=known_records
            )


def test_multiunit_manifest_read_order_and_uniqueness(tmp_path):
    known_records = {}
    with connection(tmp_path) as conn:
        _, source, _, _ = save_source(
            conn, root_for(tmp_path), known_records=known_records
        )
        original = records.read_stk_factor_pro_source_files(
            root_for(tmp_path),
            source.files_manifest_ref,
            connection=conn,
            identity=identity(),
            contract=contract(),
            known_records=known_records,
        )[0]
        second_unit = models.UnitProjection(5, "600000.SH", None, START, T)
        key = models.stk_factor_pro_unit_key(second_unit)
        other = replace(
            original,
            unit_key=key,
            component_unit_id="second-unit",
            ordinal=1,
            object_code="600000.SH",
            file_relative_path=f"source/history/units/{key}.parquet",
        )
        entries = tuple(sorted((original, other), key=lambda row: row.unit_key))
        # A separate run demonstrates the writer as well as the read-side order.
        other_root = root_for(tmp_path).with_name("run_id=run-b")
        reference = records.write_stk_factor_pro_source_files(
            other_root,
            connection=conn,
            identity=identity("run-b"),
            contract=contract(),
            files=entries,
            known_records=known_records,
            check_space=check_test_space,
        )
        path = other_root / reference.relative_path
        changed = path.with_suffix(".reordered.parquet")
        conn.execute(
            copy_query_to_parquet(
                f"SELECT * FROM read_parquet('{path}',hive_partitioning=false) ORDER BY unit_key DESC",
                changed,
            )
        )
        os.replace(changed, path)
        known_records.pop(path, None)
        reference = replace(reference, file_sha256=factor_file_sha(path))
        assert (
            records.read_stk_factor_pro_source_files(
                other_root,
                reference,
                connection=conn,
                identity=identity("run-b"),
                contract=contract(),
                known_records=known_records,
            )
            == entries
        )
        with pytest.raises(ValueError, match="唯一unit_key"):
            records.write_stk_factor_pro_source_files(
                other_root.with_name("run_id=run-c"),
                connection=conn,
                identity=identity("run-c"),
                contract=contract(),
                files=(original, original),
                known_records=known_records,
                check_space=check_test_space,
            )
