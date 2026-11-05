"""Historical request and eligibility boundaries from LLD 5.1/5.2/16.

Upstream frozen Raw/Silver facts are intentionally isolated from Dagster/PG;
T/P files retain the literal real three-column Raw factor contract.
"""

from dataclasses import replace
from datetime import date

import pytest

from orchestrator.defs.io import stk_factor_pro_history as history
from orchestrator.defs.paths import stk_factor_pro_run_staging_root
from orchestrator.defs.run_contracts.stk_factor_pro import (
    HistoryRange,
    RecordRef,
    StkFactorProHistoryStart,
    StkFactorProRecordedResults,
    UnitProjection,
    stk_factor_pro_history_plan_digest,
    stk_factor_pro_history_ranges_digest,
)
from tests.stk_factor_pro_history_test_support import (
    connection,
    contract,
    eligibility,
    identity,
    roots,
    write_factor_file,
)

T, P = date(2026, 10, 16), date(2026, 10, 15)
START = date(2015, 1, 5)
A, B = "000001.SZ", "600000.SH"


def prior():
    return StkFactorProRecordedResults(
        T, None, None, None, None, None, None, (), (), None, None
    )


def prepared(conn, lake, staging, *, starts=None, values_t=None, known_records):
    ft = write_factor_file(
        conn, lake, T, ((A, 2.0), (B, 1.0)) if values_t is None else values_t
    )
    fp = write_factor_file(conn, lake, P, ((A, 1.0), (B, 1.0)))
    factor_relations, lifecycle_relation = (
        history.prepare_stk_factor_pro_history_inputs(
            conn,
            identity=identity(),
            lake_root=lake,
            factor_t=ft,
            factor_p=fp,
            known_records=known_records,
            check_cancel=lambda: None,
        )
    )
    plan, ranges, _ = history.build_stk_factor_pro_history_plan(
        conn,
        identity=identity(),
        contract=contract(),
        lake_root=lake,
        staging_root=staging,
        factor_t=ft,
        factor_p=fp,
        prior_results=prior(),
        prior_history=history.read_stk_factor_pro_prior_history(
            conn,
            staging_root=staging,
            target=(identity()).target_trade_date,
            contract=contract(),
            prior=prior(),
            known_records=known_records,
        ),
        history_starts=(StkFactorProHistoryStart(A, START, 1, START),)
        if starts is None
        else starts,
        check_cancel=lambda: None,
        known_records=known_records,
        factor_relations=factor_relations,
        factor_comparison=history.compare_stk_factor_pro_history_factors(
            conn, factor_relations=factor_relations
        ),
        lifecycle_relation=lifecycle_relation,
    )
    return plan, ranges, ft, fp


def resolve(conn, staging, plan, ranges, *, known_records):
    return history.resolve_stk_factor_pro_history_units(
        conn,
        plan=plan,
        ranges=ranges,
        prior_results=prior(),
        staging_root=staging,
        known_records=known_records,
    )


def test_normal_range_is_one_whole_stock_unit(tmp_path):
    known_records = {}
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        plan, ranges, _, _ = prepared(conn, lake, staging, known_records=known_records)
        units = resolve(conn, staging, plan, ranges, known_records=known_records)
        assert units == (UnitProjection(5, A, None, START, T),)


def test_verified_no_work_has_no_download_units(tmp_path):
    known_records = {}
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        plan, ranges, _, _ = prepared(
            conn,
            lake,
            staging,
            values_t=((A, 1.0), (B, 1.0)),
            known_records=known_records,
        )
        assert plan.full_code_count == 0
        assert resolve(conn, staging, plan, ranges, known_records=known_records) == ()


def test_unknown_member_does_not_allow_known_subset(tmp_path):
    known_records = {}
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        plan, ranges, _, _ = prepared(
            conn,
            lake,
            staging,
            starts=(
                StkFactorProHistoryStart(A, START, 1, START),
                StkFactorProHistoryStart(B, None, None, None),
            ),
            values_t=((A, 2.0), (B, 2.0)),
            known_records=known_records,
        )
        assert len(ranges) == 2 and ranges[1].start_date is None
        with pytest.raises(ValueError, match="尚未判明"):
            resolve(conn, staging, plan, ranges, known_records=known_records)


def test_plan_or_ranges_not_equal_to_saved_current_run_are_rejected(tmp_path):
    known_records = {}
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        plan, ranges, _, _ = prepared(conn, lake, staging, known_records=known_records)
        with pytest.raises(ValueError, match="保存读回"):
            resolve(
                conn,
                staging,
                replace(plan, revision=2),
                ranges,
                known_records=known_records,
            )
        wrong_ranges = (replace(ranges[0], t_value=3.0),)
        with pytest.raises(ValueError, match="保存读回"):
            resolve(conn, staging, plan, wrong_ranges, known_records=known_records)


def test_no_history_reason_skips_only_consistent_stock(tmp_path):
    known_records = {}
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        template, _, _, _ = prepared(conn, lake, staging, known_records=known_records)
        run = identity("run-new")
        root = stk_factor_pro_run_staging_root(staging, "run-new", T.isoformat())
        new_stock = HistoryRange(
            B, True, False, 1.0, None, None, None, (3, 6), (T,), (), None, None
        )
        ranges = (new_stock,)
        ranges_digest = stk_factor_pro_history_ranges_digest(ranges)
        plan = replace(
            template,
            identity=run,
            full_code_count=1,
            ranges_ref=RecordRef("run-new", "history-ranges.parquet", "0" * 64),
            history_plan_digest=stk_factor_pro_history_plan_digest(
                run, contract(), ranges, ranges_digest=ranges_digest
            ),
            history_ranges_digest=ranges_digest,
        )
        plan, _ = history.write_stk_factor_pro_history_plan(
            root,
            plan,
            ranges,
            connection=conn,
            known_records=known_records,
        )
        assert resolve(conn, staging, plan, ranges, known_records=known_records) == ()


def test_bad_no_history_reason_cannot_hide_existing_history(tmp_path):
    known_records = {}
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        template, _, _, _ = prepared(conn, lake, staging, known_records=known_records)
        run = identity("run-bad-new")
        root = stk_factor_pro_run_staging_root(staging, "run-bad-new", T.isoformat())
        ranges = (
            HistoryRange(
                B, True, False, 1.0, None, START, T, (3, 6), (T,), (), 1, START
            ),
        )
        ranges_digest = stk_factor_pro_history_ranges_digest(ranges)
        plan = replace(
            template,
            identity=run,
            full_code_count=1,
            ranges_ref=RecordRef(
                run.creator_run_id, "history-ranges.parquet", "0" * 64
            ),
            history_plan_digest=stk_factor_pro_history_plan_digest(
                run, contract(), ranges, ranges_digest=ranges_digest
            ),
            history_ranges_digest=ranges_digest,
        )
        plan, _ = history.write_stk_factor_pro_history_plan(
            root,
            plan,
            ranges,
            connection=conn,
            known_records=known_records,
        )
        with pytest.raises(ValueError, match="无原历史"):
            resolve(conn, staging, plan, ranges, known_records=known_records)


def test_eligibility_accepts_actual_frozen_facts_without_target_reads(tmp_path):
    known_records = {}
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        plan, _, _, _ = prepared(conn, lake, staging, known_records=known_records)
        history.require_stk_factor_pro_history_eligibility(
            plan, eligibility(plan.identity, plan)
        )


@pytest.mark.parametrize(
    "fault",
    [
        "run",
        "plan",
        "ranges",
        "raw-incomplete",
        "raw-check",
        "silver-missing",
        "silver-not-ready",
    ],
)
def test_eligibility_rejects_missing_or_wrong_bound_facts(tmp_path, fault):
    known_records = {}
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        plan, _, _, _ = prepared(conn, lake, staging, known_records=known_records)
        good = eligibility(plan.identity, plan)
        if fault == "run":
            bad = replace(good, identity=identity("other-run"))
        elif fault == "plan":
            bad = replace(good, history_plan_digest="1" * 64)
        elif fault == "ranges":
            bad = replace(good, history_ranges_digest="2" * 64)
        elif fault == "raw-incomplete":
            bad = replace(good, raw_coverage=replace(good.raw_coverage, complete=False))
        elif fault == "raw-check":
            bad = replace(
                good,
                raw_coverage=replace(
                    good.raw_coverage,
                    complete=False,
                    raw_check_passed=False,
                    raw_materialization_storage_id=None,
                    raw_check_storage_id=None,
                ),
            )
        elif fault == "silver-missing":
            bad = replace(good, target_silver=None)
        else:
            bad = replace(good, target_silver=replace(good.target_silver, ready=False))
        with pytest.raises(ValueError):
            history.require_stk_factor_pro_history_eligibility(plan, bad)


def recheck(conn, lake, plan, ranges, units, callback, *, known_records):
    return history.recheck_stk_factor_pro_history_inputs(
        conn,
        plan=plan,
        ranges=ranges,
        expected_units=units,
        lake_root=lake,
        recheck_inputs=callback,
        known_records=known_records,
    )


def test_recheck_unchanged_inputs_returns_exact_four_facts(tmp_path):
    known_records = {}
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        plan, ranges, ft, fp = prepared(
            conn, lake, staging, known_records=known_records
        )
        good = eligibility(plan.identity, plan)
        facts = (ft, fp, good.raw_coverage, good.target_silver)
        assert (
            recheck(
                conn,
                lake,
                plan,
                ranges,
                resolve(conn, staging, plan, ranges, known_records=known_records),
                lambda: facts,
                known_records=known_records,
            )
            is facts
        )


def test_recheck_changed_factor_outside_requested_scope_stops_current_task(tmp_path):
    known_records = {}
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        plan, ranges, _, fp = prepared(conn, lake, staging, known_records=known_records)
        units = resolve(conn, staging, plan, ranges, known_records=known_records)
        current_t = write_factor_file(conn, lake, T, ((A, 2.0), (B, 9.0)))
        good = eligibility(plan.identity, plan)
        facts = (current_t, fp, good.raw_coverage, good.target_silver)
        with pytest.raises(ValueError, match="改变|变化|不符"):
            recheck(
                conn,
                lake,
                plan,
                ranges,
                units,
                lambda: facts,
                known_records=known_records,
            )
        assert (
            conn.execute(
                "SELECT count(*) FROM duckdb_tables() WHERE table_name LIKE 'stk_factor_pro_history_recheck_%'"
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize("changed", ["t-value", "p-value", "t-missing", "actual-sha"])
def test_recheck_requested_factor_change_or_false_file_ref_is_rejected(
    tmp_path, changed
):
    known_records = {}
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        plan, ranges, ft, fp = prepared(
            conn, lake, staging, known_records=known_records
        )
        units = resolve(conn, staging, plan, ranges, known_records=known_records)
        if changed == "t-value":
            ft = write_factor_file(conn, lake, T, ((A, 3.0), (B, 1.0)))
        elif changed == "p-value":
            fp = write_factor_file(conn, lake, P, ((A, 3.0), (B, 1.0)))
        elif changed == "t-missing":
            ft = write_factor_file(conn, lake, T, ((B, 1.0),))
        else:
            ft = replace(ft, file_sha256="9" * 64)
        good = eligibility(plan.identity, plan)
        with pytest.raises(ValueError):
            recheck(
                conn,
                lake,
                plan,
                ranges,
                units,
                lambda: (ft, fp, good.raw_coverage, good.target_silver),
                known_records=known_records,
            )
        assert (
            conn.execute(
                "SELECT count(*) FROM duckdb_tables() WHERE table_name LIKE 'stk_factor_pro_history_recheck_%'"
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize(
    "bad", [True, (), (True, True, True, True), [True, True, True, True]]
)
def test_recheck_callback_must_supply_exact_frozen_tuple(tmp_path, bad):
    known_records = {}
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        plan, ranges, _, _ = prepared(conn, lake, staging, known_records=known_records)
        with pytest.raises(TypeError, match="四项冻结"):
            recheck(
                conn,
                lake,
                plan,
                ranges,
                resolve(conn, staging, plan, ranges, known_records=known_records),
                lambda: bad,
                known_records=known_records,
            )


def test_recheck_does_not_swallow_callback_exception(tmp_path):
    known_records = {}
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        plan, ranges, _, _ = prepared(conn, lake, staging, known_records=known_records)

        def unavailable():
            raise RuntimeError("已核事实读取失败")

        with pytest.raises(RuntimeError, match="读取失败"):
            recheck(
                conn,
                lake,
                plan,
                ranges,
                resolve(conn, staging, plan, ranges, known_records=known_records),
                unavailable,
                known_records=known_records,
            )


def test_empty_scope_recheck_refused_before_callback(tmp_path):
    known_records = {}
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        plan, ranges, _, _ = prepared(conn, lake, staging, known_records=known_records)

        def forbidden():
            pytest.fail("零工作不应进入重查回调")

        with pytest.raises(ValueError, match="无实际历史"):
            recheck(
                conn, lake, plan, ranges, (), forbidden, known_records=known_records
            )


def test_recheck_requires_silver_corresponding_to_current_raw(tmp_path):
    known_records = {}
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        plan, ranges, ft, fp = prepared(
            conn, lake, staging, known_records=known_records
        )
        good = eligibility(plan.identity, plan)
        different_raw = replace(good.raw_coverage, raw_file_sha256="f" * 64)
        with pytest.raises(ValueError, match="对应"):
            recheck(
                conn,
                lake,
                plan,
                ranges,
                resolve(conn, staging, plan, ranges, known_records=known_records),
                lambda: (ft, fp, different_raw, good.target_silver),
                known_records=known_records,
            )


@pytest.mark.parametrize(
    "reference",
    [
        RecordRef("run-missing", "history-plan.json", "a" * 64),
        RecordRef(
            "run-missing", "publication/history/publication-complete.json", "a" * 64
        ),
    ],
)
def test_old_success_reference_is_not_silently_ignored_when_unreadable(
    tmp_path, reference
):
    known_records = {}
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        plan, ranges, _, _ = prepared(conn, lake, staging, known_records=known_records)
        with pytest.raises(ValueError):
            history.resolve_stk_factor_pro_history_units(
                conn,
                plan=plan,
                ranges=ranges,
                prior_results=replace(
                    prior(), successful_publication_refs=(reference,)
                ),
                staging_root=staging,
                known_records=known_records,
            )


@pytest.mark.parametrize(
    "fault", ["date", "same-bytes-wrong-count", "raw-incomplete", "source-identity"]
)
def test_recheck_rejects_wrong_dates_or_facts_bound_to_other_input(tmp_path, fault):
    known_records = {}
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        plan, ranges, ft, fp = prepared(
            conn, lake, staging, known_records=known_records
        )
        good = eligibility(plan.identity, plan)
        if fault == "date":
            facts = (fp, fp, good.raw_coverage, good.target_silver)
            with pytest.raises(ValueError, match="原T/P"):
                recheck(
                    conn,
                    lake,
                    plan,
                    ranges,
                    resolve(conn, staging, plan, ranges, known_records=known_records),
                    lambda: facts,
                    known_records=known_records,
                )
        elif fault == "same-bytes-wrong-count":
            facts = (replace(ft, rows=99), fp, good.raw_coverage, good.target_silver)
            with pytest.raises(ValueError, match="输入身份已改变"):
                recheck(
                    conn,
                    lake,
                    plan,
                    ranges,
                    resolve(conn, staging, plan, ranges, known_records=known_records),
                    lambda: facts,
                    known_records=known_records,
                )
        elif fault == "raw-incomplete":
            facts = (
                ft,
                fp,
                replace(good.raw_coverage, complete=False),
                good.target_silver,
            )
            with pytest.raises(ValueError, match="Raw未齐备"):
                recheck(
                    conn,
                    lake,
                    plan,
                    ranges,
                    resolve(conn, staging, plan, ranges, known_records=known_records),
                    lambda: facts,
                    known_records=known_records,
                )
        else:
            other_source = replace(
                good, identity=replace(plan.identity, source_run_id="different-source")
            )
            with pytest.raises(ValueError, match="当前run"):
                history.require_stk_factor_pro_history_eligibility(plan, other_source)


def test_recheck_unchanged_inputs_uses_no_sql_or_full_file_sha(tmp_path, monkeypatch):
    from orchestrator.defs.checks import stk_factor_pro as checks

    records = {}
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        plan, ranges, ft, fp = prepared(conn, lake, staging, known_records=records)
        units = resolve(conn, staging, plan, ranges, known_records=records)
        good = eligibility(plan.identity, plan)
        facts = (ft, fp, good.raw_coverage, good.target_silver)

        def forbidden(*args, **kwargs):
            raise AssertionError(
                "unchanged prepared inputs must not be read or hashed again"
            )

        class NoSQL:
            def __getattr__(self, name):
                return getattr(conn, name)

            execute = staticmethod(forbidden)

        monkeypatch.setattr(checks, "factor_file_sha", forbidden)
        if hasattr(history, "factor_file_sha"):
            monkeypatch.setattr(history, "factor_file_sha", forbidden)
        assert (
            recheck(
                NoSQL(), lake, plan, ranges, units, lambda: facts, known_records=records
            )
            is facts
        )
        history.release_stk_factor_pro_history_inputs(conn)


def test_lifecycle_changed_after_preparation_stops_without_reauditing_it(
    tmp_path, monkeypatch
):
    from orchestrator.defs.checks import stk_factor_pro as checks
    from tests.test_stk_factor_pro_history_plan_boundaries import write_lifecycle

    records = {}
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        write_lifecycle(conn, lake, code=A, list_day=date(2010, 1, 4))
        plan, ranges, ft, fp = prepared(conn, lake, staging, known_records=records)
        units = resolve(conn, staging, plan, ranges, known_records=records)
        good = eligibility(plan.identity, plan)
        # An upstream lifecycle producer can update its own file while this
        # dataset is running. The original task must stop on changed identity.
        write_lifecycle(conn, lake, code=A, list_day=date(2011, 1, 4))

        def forbidden(*args, **kwargs):
            raise AssertionError(
                "changed input must stop, not be parsed or hashed again"
            )

        class NoSQL:
            def __getattr__(self, name):
                return getattr(conn, name)

            execute = staticmethod(forbidden)

        monkeypatch.setattr(checks, "factor_file_sha", forbidden)
        if hasattr(history, "factor_file_sha"):
            monkeypatch.setattr(history, "factor_file_sha", forbidden)
        with pytest.raises(ValueError, match="改变|变化"):
            recheck(
                NoSQL(),
                lake,
                plan,
                ranges,
                units,
                lambda: (ft, fp, good.raw_coverage, good.target_silver),
                known_records=records,
            )
        history.release_stk_factor_pro_history_inputs(conn)
