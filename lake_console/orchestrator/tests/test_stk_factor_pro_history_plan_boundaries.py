"""Independent LLD 5.1/16 planning boundaries; no network or formal resources."""

from dataclasses import replace
from datetime import date

import pytest

from orchestrator.defs.checks.stk_factor_pro import factor_file_sha
from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.io import stk_factor_pro_history as history
from orchestrator.defs.paths import (
    silver_stock_lifecycle_path,
    stk_factor_pro_run_staging_root,
)
from orchestrator.defs.run_contracts.stk_factor_pro import (
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
A, B, C = "000001.SZ", "600000.SH", "000002.SZ"


def prior():
    return StkFactorProRecordedResults(
        T, None, None, None, None, None, None, (), (), None, None
    )


def start(code=A, day=EARLY):
    return StkFactorProHistoryStart(code, day, None if day is None else 1, day)


def build(conn, lake, staging, *, values_t, values_p, starts, run="run-a", old=None):
    factor_t = write_factor_file(conn, lake, T, values_t)
    factor_p = write_factor_file(conn, lake, P, values_p)
    return history.build_stk_factor_pro_history_plan(
        conn,
        identity=identity(run),
        contract=contract(),
        lake_root=lake,
        staging_root=staging,
        factor_t=factor_t,
        factor_p=factor_p,
        prior_results=prior() if old is None else old,
        history_starts=starts,
        check_cancel=lambda: None,
    )


def read_ranges(conn, staging, plan):
    root = stk_factor_pro_run_staging_root(
        staging, plan.identity.creator_run_id, T.isoformat()
    )
    return history.read_stk_factor_pro_history_ranges(conn, root=root, plan=plan)


def write_lifecycle(conn, lake, *, code, list_day):
    # Literal current producer schema from asset_column_schemas.py:480-490.
    path = silver_stock_lifecycle_path(lake)
    path.parent.mkdir(parents=True, exist_ok=True)
    query = (
        f"SELECT '{code}'::VARCHAR AS ts_code, '000001'::VARCHAR AS symbol, "
        "'test stock'::VARCHAR AS name, 'SZSE'::VARCHAR AS exchange, "
        "'主板'::VARCHAR AS market, 'CNY'::VARCHAR AS curr_type, "
        "true::BOOLEAN AS is_cny_stock, 'L'::VARCHAR AS list_status, "
        f"DATE '{list_day.isoformat()}' AS list_date, NULL::DATE AS delist_date"
    )
    conn.execute(copy_query_to_parquet(query, path))


def test_trusted_earliest_date_is_not_cropped_by_newer_approved_window(tmp_path):
    lake, _ = roots(tmp_path)
    with connection(tmp_path) as conn:
        # No Raw file exists: a trustworthy recorded boundary takes priority and
        # must not be recomputed from an unrelated recent date window.
        result = history.resolve_stk_factor_pro_history_starts(
            conn,
            lake_root=lake,
            target_trade_date=T,
            codes=(A,),
            known_starts=(start(),),
            approved_raw_dates=(P,),
            check_cancel=lambda: None,
        )
        assert result == (StkFactorProHistoryStart(A, EARLY, 1, EARLY),)


def test_full_plan_keeps_unknown_beside_known_changed_stock(tmp_path):
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        plan = build(
            conn,
            lake,
            staging,
            values_t=((A, 2.0), (B, 4.0)),
            values_p=((A, 1.0), (B, 3.0)),
            starts=(start(A), start(B, None)),
        )
        actual = {item.ts_code: item for item in read_ranges(conn, staging, plan)}
        assert plan.full_code_count == 2 and set(actual) == {A, B}
        assert actual[A].start_date == EARLY and actual[A].end_date == T
        assert actual[B].start_date is None and actual[B].end_date is None
        assert actual[B].t_value == 4.0 and actual[B].p_value == 3.0
        assert 1 in actual[B].plan_reasons and 6 not in actual[B].plan_reasons


def test_full_outer_factor_comparison_keeps_each_missing_side(tmp_path):
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        plan = build(
            conn,
            lake,
            staging,
            values_t=((A, 2.0), (C, 7.0)),
            values_p=((A, 1.0), (B, 5.0)),
            starts=(start(A), start(B), start(C)),
        )
        actual = {item.ts_code: item for item in read_ranges(conn, staging, plan)}
        assert plan.full_code_count == 3 and set(actual) == {A, B, C}
        assert (actual[B].t_present, actual[B].t_value) == (False, None)
        assert (actual[B].p_present, actual[B].p_value) == (True, 5.0)
        assert 4 in actual[B].plan_reasons
        assert (actual[C].t_present, actual[C].t_value) == (True, 7.0)
        assert (actual[C].p_present, actual[C].p_value) == (False, None)
        assert 3 in actual[C].plan_reasons


def test_pending_survives_equal_factors_and_preserves_original_earlier_start(tmp_path):
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        build(
            conn,
            lake,
            staging,
            values_t=((A, 2.0),),
            values_p=((A, 1.0),),
            starts=(start(),),
            run="run-old",
        )
        old_root = stk_factor_pro_run_staging_root(staging, "run-old", T.isoformat())
        old_ref = RecordRef(
            "run-old",
            "history-plan.json",
            factor_file_sha(old_root / "history-plan.json"),
        )
        current = build(
            conn,
            lake,
            staging,
            values_t=((A, 1.0),),
            values_p=((A, 1.0),),
            starts=(start(A, date(2020, 1, 2)),),
            old=replace(prior(), pending_plan_refs=(old_ref,)),
        )
        actual = read_ranges(conn, staging, current)
        assert current.full_code_count == 1 and len(actual) == 1
        assert actual[0].ts_code == A and actual[0].start_date == EARLY
        assert actual[0].t_value == actual[0].p_value == 1.0
        assert 2 in actual[0].plan_reasons
        assert any(ref.run == "run-old" for ref in actual[0].origin_record_refs)


@pytest.mark.parametrize(
    ("listed", "known_start", "no_history"),
    [
        (T, None, True),
        (date(2020, 1, 2), None, False),
        (T, T, True),
        (T, EARLY, False),
    ],
)
def test_missing_previous_factor_is_no_history_only_for_proven_new_stock(
    tmp_path, listed, known_start, no_history
):
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        write_lifecycle(conn, lake, code=A, list_day=listed)
        plan = build(
            conn,
            lake,
            staging,
            # The real Raw-factor blocking contract requires both whole files
            # to be nonempty.  A is missing from P; unchanged B keeps P ready.
            values_t=((A, 1.0), (B, 2.0)),
            values_p=((B, 2.0),),
            starts=(start(A, known_start),),
        )
        actual = read_ranges(conn, staging, plan)
        assert len(actual) == 1 and actual[0].ts_code == A
        assert actual[0].start_date == known_start
        assert actual[0].end_date == (None if known_start is None else T)
        assert (6 in actual[0].plan_reasons) is no_history
        if not no_history:
            assert 3 in actual[0].plan_reasons


def test_missing_pending_reference_is_not_treated_as_no_previous_work(tmp_path):
    lake, staging = roots(tmp_path)
    bad_ref = RecordRef("run-missing", "history-plan.json", "a" * 64)
    with (
        connection(tmp_path) as conn,
        pytest.raises((ValueError, FileNotFoundError)),
    ):
        build(
            conn,
            lake,
            staging,
            values_t=((A, 1.0),),
            values_p=((A, 1.0),),
            starts=(start(),),
            old=replace(prior(), pending_plan_refs=(bad_ref,)),
        )
    root = stk_factor_pro_run_staging_root(staging, "run-a", T.isoformat())
    assert not (root / "history-plan.json").exists()
