"""LLD 5.1 planning on isolated files; actual factor schema has three columns.

The factor contract comes from RAW_TUSHARE_ADJ_FACTOR_SCHEMA/adj_factor_checks,
not from the planner. Expected ranges/revisions below are literal small cases.
"""

from dataclasses import replace
from datetime import date

import pytest

from orchestrator.defs.checks.stk_factor_pro import factor_file_sha
from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.io import stk_factor_pro_history as history
from orchestrator.defs.paths import raw_adj_factor_path, stk_factor_pro_run_staging_root
from orchestrator.defs.run_contracts.stk_factor_pro import (
    FactorFileRef,
    RecordRef,
    StkFactorProHistoryStart,
    StkFactorProRecordedResults,
)
from tests.stk_factor_pro_history_test_support import (
    connection,
    contract,
    identity,
    roots,
    write_factor_file,
)

T, P, EARLY = date(2026, 10, 16), date(2026, 10, 15), date(2015, 1, 5)
A, B = "000001.SZ", "600000.SH"


def prior(**changes):
    return replace(
        StkFactorProRecordedResults(
            T, None, None, None, None, None, None, (), (), None, None
        ),
        **changes,
    )


def start(code=A, day=EARLY):
    return StkFactorProHistoryStart(code, day, 1 if day else None, day)


def inputs(conn, lake, *, t=((A, 2.0),), p=((A, 1.0),)):
    return (
        write_factor_file(conn, lake, T, t),
        write_factor_file(conn, lake, P, p),
    )


def build(
    conn,
    lake,
    staging,
    refs,
    *,
    run="run-a",
    old=None,
    starts=None,
    run_identity=None,
    cancel=lambda: None,
):
    return history.build_stk_factor_pro_history_plan(
        conn,
        identity=identity(run) if run_identity is None else run_identity,
        contract=contract(),
        lake_root=lake,
        staging_root=staging,
        factor_t=refs[0],
        factor_p=refs[1],
        prior_results=prior() if old is None else old,
        history_starts=(start(),) if starts is None else starts,
        check_cancel=cancel,
    )


def run_root(staging, run):
    return stk_factor_pro_run_staging_root(staging, run, T.isoformat())


def plan_ref(staging, plan):
    path = run_root(staging, plan.identity.creator_run_id) / "history-plan.json"
    return RecordRef(
        plan.identity.creator_run_id, "history-plan.json", factor_file_sha(path)
    )


def rows(conn, staging, plan):
    return history.read_stk_factor_pro_history_ranges(
        conn, root=run_root(staging, plan.identity.creator_run_id), plan=plan
    )


def assert_clean(conn):
    assert (
        conn.execute(
            "SELECT count(*) FROM duckdb_tables() WHERE table_name IN "
            "('stk_factor_pro_history_factor_t','stk_factor_pro_history_factor_p')"
        ).fetchone()[0]
        == 0
    )


def test_no_change_saves_empty_verified_plan_without_source(tmp_path):
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        plan = build(conn, lake, staging, inputs(conn, lake, t=((A, 1.0),)))
        assert plan.full_code_count == 0 and plan.revision == 1
        assert rows(conn, staging, plan) == ()
        assert not (run_root(staging, "run-a") / "source").exists()
        assert_clean(conn)


def test_change_saves_whole_trusted_range_and_real_factor_refs(tmp_path):
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        refs = inputs(conn, lake)
        plan = build(conn, lake, staging, refs)
        actual = rows(conn, staging, plan)
        assert len(actual) == 1
        value = actual[0]
        assert (value.ts_code, value.start_date, value.end_date) == (A, EARLY, T)
        assert (value.t_present, value.p_present, value.t_value, value.p_value) == (
            True,
            True,
            2.0,
            1.0,
        )
        assert value.plan_reasons == (1,) and value.origin_target_dates == (T,)
        assert (plan.factor_t_ref, plan.factor_p_ref) == refs
        assert plan.ranges_ref.file_sha256 == factor_file_sha(
            run_root(staging, "run-a") / "history-ranges.parquet"
        )
        assert_clean(conn)


def test_missing_both_factors_for_known_prior_object_stays_unknown(tmp_path):
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        plan = build(
            conn,
            lake,
            staging,
            inputs(conn, lake, t=((B, 1.0),), p=((B, 1.0),)),
            starts=(start(A, None),),
        )
        actual = rows(conn, staging, plan)
        assert len(actual) == 1 and actual[0].ts_code == A
        assert actual[0].plan_reasons == (5,)
        assert (actual[0].t_present, actual[0].p_present) == (False, False)
        assert actual[0].start_date is actual[0].end_date is None
        assert actual[0].t_value is actual[0].p_value is None


def test_same_business_input_keeps_revision_and_factor_revision_increments(tmp_path):
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        refs = inputs(conn, lake)
        first = build(conn, lake, staging, refs, run="run-first")
        old = prior(
            history_plan_ref=plan_ref(staging, first),
            history_ranges_ref=first.ranges_ref,
        )
        same = build(conn, lake, staging, refs, run="run-same", old=old)
        assert same.history_plan_digest == first.history_plan_digest
        assert same.history_ranges_digest == first.history_ranges_digest
        assert same.revision == first.revision == 1 and same.revision_of is None
        changed_refs = inputs(conn, lake, t=((A, 3.0),))
        second = build(
            conn,
            lake,
            staging,
            changed_refs,
            run="run-changed",
            old=prior(
                history_plan_ref=plan_ref(staging, same),
                history_ranges_ref=same.ranges_ref,
            ),
        )
        assert (
            second.revision == 2
            and second.history_plan_digest != same.history_plan_digest
        )
        assert second.revision_of == plan_ref(staging, same)


def test_repair_preserves_original_authorized_codes_and_start(tmp_path):
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        first = build(
            conn,
            lake,
            staging,
            inputs(conn, lake, t=((A, 2.0), (B, 1.0)), p=((A, 1.0), (B, 1.0))),
            run="run-origin",
        )
        repair_id = replace(
            identity("run-repair"),
            source_run_id="run-origin",
            purpose="manual_repair",
            scheduled_slot=None,
        )
        current = build(
            conn,
            lake,
            staging,
            inputs(conn, lake, t=((A, 3.0), (B, 3.0)), p=((A, 1.0), (B, 1.0))),
            old=prior(
                history_plan_ref=plan_ref(staging, first),
                history_ranges_ref=first.ranges_ref,
                pending_plan_refs=(plan_ref(staging, first),),
            ),
            starts=(start(A, date(2010, 1, 4)), start(B, date(2000, 1, 4))),
            run_identity=repair_id,
        )
        actual = rows(conn, staging, current)
        assert [(r.ts_code, r.start_date, r.end_date) for r in actual] == [
            (A, EARLY, T)
        ]
        assert current.origin_plan_ref == plan_ref(staging, first)
        assert current.origin_history_plan_digest == first.history_plan_digest
        assert current.origin_history_ranges_digest == first.history_ranges_digest
        assert 2 in actual[0].plan_reasons
        assert_clean(conn)


@pytest.mark.parametrize("invalid", [0.0, -1.0, float("nan"), float("inf"), None])
def test_factor_must_be_present_positive_finite(tmp_path, invalid):
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        refs = inputs(conn, lake, t=((A, invalid),))
        with pytest.raises(ValueError, match="正值"):
            build(conn, lake, staging, refs)
        assert not (run_root(staging, "run-a") / "history-plan.json").exists()
        assert_clean(conn)


@pytest.mark.parametrize("which", [0, 1])
def test_entire_empty_factor_file_cannot_be_ready(tmp_path, which):
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        refs = list(inputs(conn, lake))
        refs[which] = write_factor_file(conn, lake, (T, P)[which], ())
        with pytest.raises(ValueError, match="非空"):
            build(conn, lake, staging, tuple(refs))
        assert_clean(conn)


@pytest.mark.parametrize(
    "violation", ["sha", "count", "wrong-reference-date", "duplicate"]
)
def test_factor_reference_and_actual_file_must_match(tmp_path, violation):
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        refs = list(inputs(conn, lake))
        if violation == "sha":
            refs[0] = replace(refs[0], file_sha256="a" * 64)
        elif violation == "count":
            refs[0] = replace(refs[0], rows=9)
        elif violation == "wrong-reference-date":
            refs[0] = refs[1]
        else:
            refs[0] = write_factor_file(conn, lake, T, ((A, 2.0), (A, 3.0)))
        with pytest.raises(ValueError):
            build(conn, lake, staging, tuple(refs))
        assert_clean(conn)


@pytest.mark.parametrize(
    "query",
    [
        "SELECT '000001.SZ'::VARCHAR AS ts_code, DATE '2026-10-16' AS trade_date, 2.0::DOUBLE AS adj_factor",
        "SELECT '000001.SZ'::VARCHAR AS ts_code, '20261015'::VARCHAR AS trade_date, 2.0::DOUBLE AS adj_factor",
        "SELECT '000001.SZ'::VARCHAR AS ts_code, '20261016'::VARCHAR AS trade_date, 2.0::DOUBLE AS adj_factor, 1 AS unexpected",
        "SELECT 'bad-code'::VARCHAR AS ts_code, '20261016'::VARCHAR AS trade_date, 2.0::DOUBLE AS adj_factor",
    ],
)
def test_factor_literal_wrong_schema_date_or_code_rejected(tmp_path, query):
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        refs = list(inputs(conn, lake))
        path = raw_adj_factor_path(lake, T.isoformat())
        conn.execute(copy_query_to_parquet(query, path))
        refs[0] = FactorFileRef(T, "raw_tushare_adj_factor", factor_file_sha(path), 1)
        with pytest.raises(ValueError):
            build(conn, lake, staging, tuple(refs))
        assert_clean(conn)


def test_cancel_before_save_leaves_no_plan_or_temp_factor_tables(tmp_path):
    lake, staging = roots(tmp_path)
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("cancel")

    with connection(tmp_path) as conn:
        with pytest.raises(RuntimeError, match="cancel"):
            build(conn, lake, staging, inputs(conn, lake), cancel=cancel)
        assert not (run_root(staging, "run-a") / "history-plan.json").exists()
        assert_clean(conn)


@pytest.mark.parametrize("which", [0, 1])
def test_factor_reference_type_is_checked_before_attribute_access(tmp_path, which):
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        refs = list(inputs(conn, lake))
        refs[which] = {"trade_date": (T, P)[which]}
        with pytest.raises(TypeError, match="冻结文件引用"):
            build(conn, lake, staging, tuple(refs))
        assert not (run_root(staging, "run-a") / "history-plan.json").exists()


def test_factor_change_during_planning_stops_before_saving_plan(tmp_path, monkeypatch):
    lake, staging = roots(tmp_path)
    original = history._history_lifecycle
    with connection(tmp_path) as conn:
        refs = inputs(conn, lake)

        def changed_input(connection, **kwargs):
            write_factor_file(connection, lake, T, ((A, 3.0),))
            return original(connection, **kwargs)

        monkeypatch.setattr(history, "_history_lifecycle", changed_input)
        with pytest.raises(ValueError, match="保存前改变"):
            build(conn, lake, staging, refs)
        assert not (run_root(staging, "run-a") / "history-plan.json").exists()
        assert_clean(conn)
