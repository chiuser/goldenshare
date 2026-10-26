"""LLD 5.1.2 independent whole-scope success and unknown-input boundaries."""

import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from orchestrator.defs.checks.stk_factor_pro import factor_file_sha
from orchestrator.defs.io import stk_factor_pro_history as history
from orchestrator.defs.paths import stk_factor_pro_run_staging_root
from orchestrator.defs.run_contracts import stk_factor_pro as models
from tests.stk_factor_pro_history_test_support import (
    connection,
    contract,
    eligibility,
    identity,
    roots,
    write_factor_file,
)

T, P = date(2026, 10, 16), date(2026, 10, 15)
A, B, C = "000001.SZ", "600000.SH", "000002.SZ"
SHA = "a" * 64
NOW = datetime(2026, 10, 16, 19, tzinfo=timezone(timedelta(hours=8)))


def prior(*, success=()):
    # The fifth-batch reader supplies successful_publication_refs only after
    # checking the producer's terminal SUCCESS. This fixture substitutes that
    # upstream boundary; existence of our files alone never proves run status.
    return models.StkFactorProRecordedResults(
        T, None, None, None, None, None, None, (), success, None, None
    )


def range_row(code, *, start=P, t_value=2.0, p_value=1.0, reasons=(1,)):
    return models.HistoryRange(
        code,
        t_value is not None,
        p_value is not None,
        t_value,
        p_value,
        start,
        T if start is not None else None,
        reasons,
        (T,),
        (),
        1 if start is not None else None,
        start,
    )


def save_plan(conn, staging, rows, *, run="run-a", source_contract=None, factors=None):
    rows = tuple(sorted(rows, key=lambda item: item.ts_code))
    run_identity = identity(run)
    source_contract = contract() if source_contract is None else source_contract
    factor_t, factor_p = factors or (
        models.FactorFileRef(T, "raw_tushare_adj_factor", SHA, len(rows)),
        models.FactorFileRef(P, "raw_tushare_adj_factor", SHA, len(rows)),
    )
    value = models.HistoryPlanRecord(
        1,
        run_identity,
        source_contract,
        1,
        NOW,
        models.stk_factor_pro_history_plan_digest(run_identity, source_contract, rows),
        models.stk_factor_pro_history_ranges_digest(rows),
        models.RecordRef(run, "history-ranges.parquet", "0" * 64),
        len(rows),
        factor_t,
        factor_p,
        None,
        None,
        None,
        None,
    )
    root = stk_factor_pro_run_staging_root(staging, run, T.isoformat())
    return history.write_stk_factor_pro_history_plan(
        root, value, rows, connection=conn
    ), rows


def old_success(conn, staging, rows, *, source_contract=None):
    """Persist only authenticated metadata, deliberately no old business files."""
    plan, rows = save_plan(
        conn, staging, rows, run="run-old", source_contract=source_contract
    )
    root = stk_factor_pro_run_staging_root(staging, "run-old", T.isoformat())
    units = tuple(
        models.UnitProjection(5, item.ts_code, None, item.start_date, item.end_date)
        for item in rows
    )
    scope = models.stk_factor_pro_scope_digest("history", T, units)
    input_digest = models.stk_factor_pro_history_input_digest(
        plan.identity, plan.contract, units, rows
    )
    source = models.SourceCompleteRecord(
        1,
        plan.identity,
        "history",
        plan.contract,
        models.RecordRef(
            "run-old", "history-plan.json", factor_file_sha(root / "history-plan.json")
        ),
        plan.history_plan_digest,
        1,
        None,
        None,
        input_digest,
        scope,
        units,
        models.RecordRef("run-old", "source/history/source-files.parquet", SHA),
        SHA,
        len(units),
        NOW,
    )
    history.write_stk_factor_pro_source_complete(root, source)
    source_ref = models.RecordRef(
        "run-old",
        "source/history/source-complete.json",
        factor_file_sha(root / "source/history/source-complete.json"),
    )
    targets = tuple(
        models.PublishedTarget(
            P,
            layer,
            False,
            SHA,
            len(rows),
            models.RecordRef(
                "run-old", f"publication/history/{P}/{layer}/complete.json", SHA
            ),
            0,
            len(rows),
            SHA,
            1,
        )
        for layer in ("raw", "silver")
    )
    completed = models.PublicationCompleteRecord(
        1,
        plan.identity,
        "history",
        plan.contract,
        plan.history_plan_digest,
        plan.history_ranges_digest,
        scope,
        input_digest,
        source_ref,
        None,
        SHA,
        targets,
        NOW,
    )
    path = root / "publication/history/publication-complete.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            models.stk_factor_pro_record_to_dict(completed),
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    assert not (root / "source/history/source-files.parquet").exists()
    assert not (root / "source/history/units").exists()
    assert not (root / "candidates").exists()
    return models.RecordRef(
        "run-old",
        "publication/history/publication-complete.json",
        factor_file_sha(path),
    )


class RejectOldBusinessRead:
    def __init__(self, conn):
        self.conn = conn

    def __getattr__(self, key):
        return getattr(self.conn, key)

    def execute(self, query, parameters=None):
        text = str(query) + repr(parameters)
        assert "run_id=run-old/source/history" not in text
        assert "run_id=run-old/candidates" not in text
        return (
            self.conn.execute(query)
            if parameters is None
            else self.conn.execute(query, parameters)
        )


def resolve(conn, staging, plan, rows, *, success=()):
    return history.resolve_stk_factor_pro_history_units(
        conn,
        plan=plan,
        ranges=rows,
        prior_results=prior(success=success),
        staging_root=staging,
    )


def guard_old_business_reads(monkeypatch):
    original_open = Path.open

    def guard(path, *args, **kwargs):
        text = path.as_posix()
        if "run_id=run-old/source/history/" in text:
            assert path.name == "source-complete.json"
        assert "run_id=run-old/candidates/" not in text
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guard)


@pytest.mark.parametrize("unknown", ["start", "T", "P"])
def test_one_unknown_stock_rejects_whole_scope_instead_of_filtering(tmp_path, unknown):
    _, staging = roots(tmp_path)
    b = range_row(B)
    if unknown == "start":
        b = range_row(B, start=None)
    elif unknown == "T":
        b = range_row(B, t_value=None, reasons=(4,))
    else:
        b = range_row(B, p_value=None, reasons=(3,))
    with connection(tmp_path) as conn:
        plan, rows = save_plan(conn, staging, (range_row(A), b))
        with pytest.raises(ValueError):
            resolve(conn, staging, plan, rows)


def test_proven_no_history_stock_is_kept_in_plan_but_excluded_from_units(tmp_path):
    _, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        plan, rows = save_plan(
            conn,
            staging,
            (range_row(A), range_row(B, start=None, p_value=None, reasons=(3, 6))),
        )
        assert plan.full_code_count == 2
        assert resolve(conn, staging, plan, rows) == (
            models.UnitProjection(5, A, None, P, T),
        )


def test_independent_ab_success_survives_new_c_without_reading_old_business_files(
    tmp_path, monkeypatch
):
    _, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        success = old_success(conn, staging, (range_row(A), range_row(B)))
        plan, rows = save_plan(
            conn, staging, (range_row(A), range_row(B), range_row(C))
        )
        guard_old_business_reads(monkeypatch)
        assert resolve(
            RejectOldBusinessRead(conn), staging, plan, rows, success=(success,)
        ) == (models.UnitProjection(5, C, None, P, T),)


@pytest.mark.parametrize("change", ["value", "range"])
def test_any_ab_input_change_invalidates_entire_old_success_scope(tmp_path, change):
    _, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        success = old_success(conn, staging, (range_row(A), range_row(B)))
        a = (
            range_row(A, t_value=3.0)
            if change == "value"
            else range_row(A, start=date(2026, 10, 14))
        )
        plan, rows = save_plan(conn, staging, (a, range_row(B)))
        assert resolve(conn, staging, plan, rows, success=(success,)) == tuple(
            models.UnitProjection(5, item.ts_code, None, item.start_date, T)
            for item in rows
        )


def test_old_success_with_different_contract_is_rejected_without_partial_skip(tmp_path):
    _, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        wrong = replace(contract(), contract_content_digest="b" * 64)
        success = old_success(
            conn, staging, (range_row(A), range_row(B)), source_contract=wrong
        )
        plan, rows = save_plan(conn, staging, (range_row(A), range_row(B)))
        with pytest.raises(ValueError):
            resolve(conn, staging, plan, rows, success=(success,))


def test_old_success_source_complete_changed_bytes_rejected(tmp_path, monkeypatch):
    _, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        success = old_success(conn, staging, (range_row(A), range_row(B)))
        plan, rows = save_plan(conn, staging, (range_row(A), range_row(B)))
        old_root = stk_factor_pro_run_staging_root(staging, "run-old", T.isoformat())
        source = old_root / "source/history/source-complete.json"
        source.write_text(source.read_text() + " ", encoding="utf-8")
        guard_old_business_reads(monkeypatch)
        with pytest.raises(ValueError, match="SHA"):
            resolve(
                RejectOldBusinessRead(conn), staging, plan, rows, success=(success,)
            )


@pytest.mark.parametrize("field", ["scope_digest", "history_input_digest"])
def test_old_success_business_digest_corrupt_despite_matching_file_refs(
    tmp_path, monkeypatch, field
):
    _, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        success = old_success(conn, staging, (range_row(A), range_row(B)))
        plan, rows = save_plan(conn, staging, (range_row(A), range_row(B)))
        old_root = stk_factor_pro_run_staging_root(staging, "run-old", T.isoformat())
        source = old_root / "source/history/source-complete.json"
        publication = old_root / success.relative_path
        source_value, published_value = (
            json.loads(source.read_text()),
            json.loads(publication.read_text()),
        )
        source_value[field] = published_value[field] = "f" * 64
        source.write_text(
            json.dumps(source_value, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        published_value["source_complete_ref"]["file_sha256"] = factor_file_sha(source)
        publication.write_text(
            json.dumps(published_value, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        corrected_ref = replace(success, file_sha256=factor_file_sha(publication))
        # Byte references are now valid; only recomputation of the actual scope
        # or factor-input meaning can reject these two self-consistent records.
        guard_old_business_reads(monkeypatch)
        with pytest.raises(ValueError, match="摘要"):
            resolve(
                RejectOldBusinessRead(conn),
                staging,
                plan,
                rows,
                success=(corrected_ref,),
            )


@pytest.mark.parametrize("change", ["outside", "inside", "raw", "silver"])
def test_recheck_uses_actual_scope_values_and_current_raw_silver_qualification(
    tmp_path, change
):
    lake, staging = roots(tmp_path)
    with connection(tmp_path) as conn:
        refs = (
            write_factor_file(conn, lake, T, ((A, 2.0), (B, 1.0))),
            write_factor_file(conn, lake, P, ((A, 1.0), (B, 1.0))),
        )
        plan, rows = save_plan(conn, staging, (range_row(A),), factors=refs)
        valid = eligibility(plan.identity, plan)
        current_t = write_factor_file(
            conn, lake, T, ((A, 7.0 if change == "inside" else 2.0), (B, 4.0))
        )
        coverage = (
            replace(valid.raw_coverage, complete=False)
            if change == "raw"
            else valid.raw_coverage
        )
        silver = (
            replace(valid.target_silver, ready=False)
            if change == "silver"
            else valid.target_silver
        )
        args = {
            "plan": plan,
            "ranges": rows,
            "expected_units": (models.UnitProjection(5, A, None, P, T),),
            "lake_root": lake,
            "recheck_inputs": lambda: (current_t, refs[1], coverage, silver),
        }
        if change == "outside":
            assert history.recheck_stk_factor_pro_history_inputs(conn, **args) == (
                current_t,
                refs[1],
                coverage,
                silver,
            )
        else:
            with pytest.raises(ValueError):
                history.recheck_stk_factor_pro_history_inputs(conn, **args)
