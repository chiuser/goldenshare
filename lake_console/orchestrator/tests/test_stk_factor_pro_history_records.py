"""LLD 5.4 literal Parquet/JSON producers; all files are temporary and offline."""

import json
import os
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from orchestrator.defs.checks.stk_factor_pro import factor_file_sha
from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.io import stk_factor_pro_history as records
from orchestrator.defs.run_contracts import stk_factor_pro as models
from tests.stk_factor_pro_test_support import NAMES, connection, contract, identity

T, P, START = date(2026, 10, 16), date(2026, 10, 15), date(2026, 10, 14)
NOW = datetime(2026, 10, 16, 19, 0, tzinfo=timezone(timedelta(hours=8)))
SHA = "a" * 64


def root_for(tmp_path):
    return tmp_path / "staging" / "stk_factor_pro" / f"trade_date={T}" / "run_id=run-a"


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
        models.stk_factor_pro_history_plan_digest(identity(), contract(), rows),
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


def save_source(conn, root, *, kind="normal", source_contract=None):
    source_contract = contract() if source_contract is None else source_contract
    initial_plan = replace(
        new_plan(),
        contract=source_contract,
        history_plan_digest=models.stk_factor_pro_history_plan_digest(
            identity(), source_contract, ranges()
        ),
    )
    plan = records.write_stk_factor_pro_history_plan(
        root, initial_plan, ranges(), connection=conn
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
    manifest_ref = records.write_stk_factor_pro_source_files(
        root,
        connection=conn,
        identity=identity(),
        contract=source_contract,
        files=(file,),
    )
    scope = models.stk_factor_pro_scope_digest("history", T, (unit,))
    source = models.SourceCompleteRecord(
        1,
        identity(),
        "history",
        source_contract,
        models.RecordRef(
            "run-a", "history-plan.json", factor_file_sha(root / "history-plan.json")
        ),
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
    records.write_stk_factor_pro_source_complete(root, source)
    return plan, source, unit, path


def test_plan_returns_actual_ranges_reference_and_complete_roundtrip(tmp_path):
    root = root_for(tmp_path)
    before = new_plan()
    with connection(tmp_path) as conn:
        saved = records.write_stk_factor_pro_history_plan(
            root, before, ranges(), connection=conn
        )
        assert before.ranges_ref.file_sha256 == "0" * 64
        assert saved.ranges_ref.file_sha256 == factor_file_sha(
            root / "history-ranges.parquet"
        )
        assert saved.ranges_ref != before.ranges_ref
        assert (
            records.read_stk_factor_pro_history_ranges(conn, root=root, plan=saved)
            == ranges()
        )
        assert (
            records.read_stk_factor_pro_history_plan(
                root, expected_target=T, expected_run_id="run-a"
            )
            == saved
        )
        assert conn.execute("SHOW TABLES").fetchall() == []
        with pytest.raises(ValueError, match="已存在"):
            records.write_stk_factor_pro_history_plan(
                root, before, ranges(), connection=conn
            )
        assert (
            factor_file_sha(root / "history-ranges.parquet")
            == saved.ranges_ref.file_sha256
        )


def test_ranges_schema_is_independent_twelve_column_contract_and_empty_supported(
    tmp_path,
):
    # Literal expected schema comes from LLD 5.4.3, not HISTORY_RANGE_SCHEMA.
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
            identity(), contract(), ()
        ),
    )
    with connection(tmp_path) as conn:
        saved = records.write_stk_factor_pro_history_plan(
            root_for(tmp_path), plan, (), connection=conn
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
                conn, root=root_for(tmp_path), plan=saved
            )
            == ()
        )
        assert conn.execute("SHOW TABLES").fetchall() == []


@pytest.mark.parametrize("kind", ["normal", "empty"])
def test_verify_current_source_real_rows_or_complete_empty_schema(tmp_path, kind):
    with connection(tmp_path) as conn:
        _, source, unit, _ = save_source(conn, root_for(tmp_path), kind=kind)
        verified = records.verify_stk_factor_pro_current_source(
            root_for(tmp_path),
            source,
            connection=conn,
            current_run_id="run-a",
            expected_units=(unit,),
        )
        assert verified.source_complete == source
        assert verified.source_complete_ref.file_sha256 == factor_file_sha(
            root_for(tmp_path) / "source/history/source-complete.json"
        )
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
def test_source_with_matching_sha_but_invalid_actual_contract_rejected(tmp_path, kind):
    with connection(tmp_path) as conn:
        _, source, unit, _ = save_source(conn, root_for(tmp_path), kind=kind)
        with pytest.raises(ValueError):
            records.verify_stk_factor_pro_current_source(
                root_for(tmp_path),
                source,
                connection=conn,
                current_run_id="run-a",
                expected_units=(unit,),
            )
        assert conn.execute("SHOW TABLES").fetchall() == []


def test_plan_business_digest_tampering_rejected_before_writes(tmp_path):
    with connection(tmp_path) as conn, pytest.raises(ValueError, match="业务摘要"):
        records.write_stk_factor_pro_history_plan(
            root_for(tmp_path),
            replace(new_plan(), history_plan_digest=SHA),
            ranges(),
            connection=conn,
        )
    assert not root_for(tmp_path).exists()


def test_complete_source_cross_identity_rejected_even_same_run_and_t(tmp_path):
    with connection(tmp_path) as conn:
        _, source, unit, _ = save_source(conn, root_for(tmp_path))
        changed = replace(
            source, identity=replace(source.identity, source_run_id="other-intent")
        )
        path = root_for(tmp_path) / "source/history/source-complete.json"
        path.write_text(json.dumps(models.stk_factor_pro_record_to_dict(changed)))
        with pytest.raises(ValueError, match="计划"):
            records.verify_stk_factor_pro_current_source(
                root_for(tmp_path),
                changed,
                connection=conn,
                current_run_id="run-a",
                expected_units=(unit,),
            )


def test_wrong_run_and_unplanned_units_rejected(tmp_path):
    with connection(tmp_path) as conn:
        _, source, unit, _ = save_source(conn, root_for(tmp_path))
        for run_id, units in (("another-run", (unit,)), ("run-a", ())):
            with pytest.raises(ValueError, match="当前run"):
                records.verify_stk_factor_pro_current_source(
                    root_for(tmp_path),
                    source,
                    connection=conn,
                    current_run_id=run_id,
                    expected_units=units,
                )


def test_json_unknown_field_and_bad_ranges_sha_rejected(tmp_path):
    with connection(tmp_path) as conn:
        saved = records.write_stk_factor_pro_history_plan(
            root_for(tmp_path), new_plan(), ranges(), connection=conn
        )
        with pytest.raises(ValueError, match="SHA"):
            records.read_stk_factor_pro_history_ranges(
                conn,
                root=root_for(tmp_path),
                plan=replace(
                    saved, ranges_ref=replace(saved.ranges_ref, file_sha256="0" * 64)
                ),
            )
        path = root_for(tmp_path) / "history-plan.json"
        value = json.loads(path.read_text())
        value["unexpected"] = 1
        path.write_text(json.dumps(value))
        with pytest.raises(ValueError, match="未知"):
            records.read_stk_factor_pro_history_plan(
                root_for(tmp_path), expected_target=T, expected_run_id="run-a"
            )


@pytest.mark.parametrize("dangling", [False, True])
def test_ranges_symlink_rejected_before_any_external_write(tmp_path, dangling):
    root, outside = root_for(tmp_path), tmp_path / "outside.parquet"
    root.mkdir(parents=True)
    if not dangling:
        outside.write_bytes(b"external file must survive")
    (root / "history-ranges.parquet").symlink_to(outside)
    with connection(tmp_path) as conn, pytest.raises(ValueError, match="路径"):
        records.write_stk_factor_pro_history_plan(
            root, new_plan(), ranges(), connection=conn
        )
    assert outside.exists() is (not dangling)
    if not dangling:
        assert outside.read_bytes() == b"external file must survive"
    assert not (root / "history-plan.json").exists()


def test_ranges_updated_sha_does_not_hide_extra_schema_column(tmp_path):
    with connection(tmp_path) as conn:
        plan = records.write_stk_factor_pro_history_plan(
            root_for(tmp_path), new_plan(), ranges(), connection=conn
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
        plan = replace(
            plan, ranges_ref=replace(plan.ranges_ref, file_sha256=factor_file_sha(path))
        )
        with pytest.raises(ValueError, match="列名"):
            records.read_stk_factor_pro_history_ranges(
                conn, root=root_for(tmp_path), plan=plan
            )


def test_manifest_wrong_integer_type_rejected_even_with_actual_new_sha(tmp_path):
    with connection(tmp_path) as conn:
        _, source, _, _ = save_source(conn, root_for(tmp_path))
        path = root_for(tmp_path) / source.files_manifest_ref.relative_path
        changed = path.with_suffix(".bad.parquet")
        conn.execute(
            copy_query_to_parquet(
                f"SELECT * REPLACE (CAST(mode AS DOUBLE) AS mode) FROM read_parquet('{path}',hive_partitioning=false)",
                changed,
            )
        )
        os.replace(changed, path)
        ref = replace(source.files_manifest_ref, file_sha256=factor_file_sha(path))
        with pytest.raises(ValueError, match="类型"):
            records.read_stk_factor_pro_source_files(
                root_for(tmp_path),
                ref,
                connection=conn,
                identity=identity(),
                contract=contract(),
            )


def test_current_source_symlink_and_changed_unit_bytes_rejected(tmp_path):
    with connection(tmp_path) as conn:
        _, source, unit, path = save_source(conn, root_for(tmp_path))
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
            )
        path.unlink()
        os.replace(outside, path)
        with path.open("ab") as stream:
            stream.write(b"changed after manifest")
        with pytest.raises(ValueError, match="SHA"):
            records.verify_stk_factor_pro_current_source(
                root_for(tmp_path),
                source,
                connection=conn,
                current_run_id="run-a",
                expected_units=(unit,),
            )


def test_duplicate_json_field_is_not_silently_replaced(tmp_path):
    with connection(tmp_path) as conn:
        records.write_stk_factor_pro_history_plan(
            root_for(tmp_path), new_plan(), ranges(), connection=conn
        )
        path = root_for(tmp_path) / "history-plan.json"
        path.write_text(path.read_text()[:-1] + ',"record_version":1}')
        with pytest.raises(ValueError, match="重复"):
            records.read_stk_factor_pro_history_plan(
                root_for(tmp_path), expected_target=T, expected_run_id="run-a"
            )


def test_failed_parquet_copy_cleans_only_own_temporary_relations(tmp_path):
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
                root_for(tmp_path), new_plan(), ranges(), connection=CopyFailure(conn)
            )
        assert conn.execute("SHOW TABLES").fetchall() == [("unrelated",)]
        assert not (root_for(tmp_path) / "history-plan.json").exists()
        assert not (root_for(tmp_path) / "history-ranges.parquet").exists()


def test_all_metadata_agree_but_not_current_contract_is_rejected(tmp_path):
    wrong = replace(contract(), contract_content_digest="f" * 64)
    with connection(tmp_path) as conn:
        _, source, unit, _ = save_source(
            conn, root_for(tmp_path), source_contract=wrong
        )
        assert source.contract == wrong
        with pytest.raises(ValueError, match="当前登记契约"):
            records.verify_stk_factor_pro_current_source(
                root_for(tmp_path),
                source,
                connection=conn,
                current_run_id="run-a",
                expected_units=(unit,),
            )


def test_multirow_ranges_read_order_is_explicit_not_physical(tmp_path):
    rows = (ranges()[0], replace(ranges()[0], ts_code="600000.SH"))
    plan = replace(
        new_plan(),
        full_code_count=2,
        history_ranges_digest=models.stk_factor_pro_history_ranges_digest(rows),
        history_plan_digest=models.stk_factor_pro_history_plan_digest(
            identity(), contract(), rows
        ),
    )
    with connection(tmp_path) as conn:
        saved = records.write_stk_factor_pro_history_plan(
            root_for(tmp_path), plan, rows, connection=conn
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
        saved = replace(
            saved,
            ranges_ref=replace(saved.ranges_ref, file_sha256=factor_file_sha(path)),
        )
        assert (
            records.read_stk_factor_pro_history_ranges(
                conn, root=root_for(tmp_path), plan=saved
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
        saved = replace(
            saved,
            ranges_ref=replace(saved.ranges_ref, file_sha256=factor_file_sha(path)),
        )
        with pytest.raises(ValueError, match="唯一代码"):
            records.read_stk_factor_pro_history_ranges(
                conn, root=root_for(tmp_path), plan=saved
            )


def test_multiunit_manifest_read_order_and_uniqueness(tmp_path):
    with connection(tmp_path) as conn:
        _, source, _, _ = save_source(conn, root_for(tmp_path))
        original = records.read_stk_factor_pro_source_files(
            root_for(tmp_path),
            source.files_manifest_ref,
            connection=conn,
            identity=identity(),
            contract=contract(),
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
        reference = replace(reference, file_sha256=factor_file_sha(path))
        assert (
            records.read_stk_factor_pro_source_files(
                other_root,
                reference,
                connection=conn,
                identity=identity("run-b"),
                contract=contract(),
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
            )
