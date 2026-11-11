"""Prelaunch small-record handover; fixtures use the actual bootstrap producer."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

import pytest

from orchestrator.defs.asset_guards import stk_factor_pro_readiness as G
from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_coverage as B
from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_records as R
from orchestrator.defs.bootstrap import stk_factor_pro_history as H
from tests.test_stk_factor_pro_bootstrap_coverage import (
    DAY,
    A,
    connection,
    save,
    setup,
    summary,
)


@pytest.fixture
def prepared_fixture(tmp_path):
    manager = connection(tmp_path)
    conn = manager.__enter__()
    known = {}
    args = setup(conn, tmp_path, codes=(A,), known_records=known, date_results={})
    result = save(conn, args, known_records=known)
    summary(args, known_records=known)
    yield conn, known, args, result
    manager.__exit__(None, None, None)


def load(args, known):
    return H.load_stk_factor_pro_bootstrap_supplement_state(
        staging_root=args["staging_root"],
        approval=args["approval"],
        approval_digest=args["_approval_digest"],
        approved_counts=args["_approved_counts"],
        known_records=known,
    )


def test_small_ledger_uses_date_not_stale_summary_and_never_business_files(
    prepared_fixture,
):
    conn, known, args, result = prepared_fixture
    path = R.operation_path(
        args["staging_root"], args["approval"], f"coverage/{DAY}/result.json"
    )
    # A legitimate newer saved date must win if the following summary save failed.
    newer = replace(result, evaluated_at=result.evaluated_at + timedelta(seconds=1))
    R.write_json(path, newer, mutable=True, known_records=known)
    with (
        patch.object(H, "_classify_date", side_effect=AssertionError("full scan")),
        patch.object(
            H, "factor_known_file_sha", side_effect=AssertionError("business file")
        ),
    ):
        fresh = {}
        state = load(args, fresh)
        assert state["date_results"][DAY]["persisted_result"] == newer
        assert state["totals"]["counts"]["current_raw_rows"] == 1
        assert state["totals"]["counts"]["missing_count_known_dates"] == 2
        assert len(fresh) == 2  # One date JSON and one summary JSON.
        entry = H.prepare_stk_factor_pro_bootstrap_supplement_entry(
            conn,
            staging_root=args["staging_root"],
            approval=args["approval"],
            approval_digest=args["_approval_digest"],
            trade_date=DAY,
            approved_counts=args["_approved_counts"],
            date_results=state["date_results"],
            known_records=fresh,
        )
        assert entry["source_complete"].actual_rows == 1
        assert (
            len(fresh) == 6
        )  # Three touched-date facts plus first approval, no business files.
        assert (
            H.prepare_stk_factor_pro_bootstrap_supplement_entry(
                conn,
                staging_root=args["staging_root"],
                approval=args["approval"],
                approval_digest=args["_approval_digest"],
                trade_date=DAY,
                approved_counts=args["_approved_counts"],
                date_results=state["date_results"],
                known_records=fresh,
            )
            is entry
        )


def test_single_day_wrapper_uses_existing_relations_without_month_reload(
    prepared_fixture,
):
    conn, _known, args, result = prepared_fixture
    B.release_stk_factor_pro_bootstrap_coverage_inputs(
        conn,
        basis_inputs=args["_basis_inputs"],
    )
    facts, known_day = {}, {}
    inputs = G.prepare_stk_factor_pro_coverage_inputs(
        conn,
        lake_root=args["lake_root"],
        trade_date=DAY,
        inherited_facts=facts,
        known_records=known_day,
    )
    with patch.object(G, "_load_basis", side_effect=AssertionError("duplicate read")):
        assert (
            G.prepare_stk_factor_pro_coverage_inputs(
                conn,
                lake_root=args["lake_root"],
                trade_date=DAY,
                inherited_facts=facts,
                known_records=known_day,
            )
            is inputs
        )
        prepared = B.prepare_stk_factor_pro_bootstrap_supplement_date(
            trade_date=DAY,
            raw_audit=args["raw_audit"],
            silver_audit=args["silver_audit"],
            coverage_inputs=inputs,
        )
        assert prepared["trade_date"] == DAY
        assert prepared["raw_rows"] == result.raw_rows
        assert (
            not {
                "source_complete",
                "current_publication",
                "input_digest",
                "reusable_result",
            }
            & prepared.keys()
        )
        assert "month" not in prepared
        assert all(prepared["relations"].values())


def test_incomplete_original_import_rejected_by_small_records(prepared_fixture):
    _conn, _known, args, _ = prepared_fixture
    path = R.operation_path(
        args["staging_root"], args["approval"], "coverage/summary.json"
    )
    path.unlink()
    with pytest.raises(ValueError, match="原物理导入"):
        load(args, {})


def test_initial_authorization_rejects_wrong_result_digest(
    prepared_fixture, monkeypatch
):
    from datetime import datetime
    from types import SimpleNamespace

    from orchestrator.defs.run_contracts import stk_factor_pro as C

    conn, known, args, result = prepared_fixture
    config = C.StkFactorProRunInput(
        DAY,
        DAY,
        "bootstrap_supplement",
        None,
        args["approval"].operation_id,
        args["_approval_digest"],
        known[
            R.operation_path(
                args["staging_root"], args["approval"], f"coverage/{DAY}/result.json"
            )
        ][1],
    )
    monkeypatch.setattr(
        H, "_now", lambda: datetime.fromisoformat("2019-10-16T19:00:00+08:00")
    )
    current = SimpleNamespace(
        run_id="supplement-first", parent_run_id=None, root_run_id=None
    )

    # Native PG is not consulted for a first, unparented authorization.
    class NoPG:
        def __getattr__(self, name):
            raise AssertionError(name)

    known_pg = {}
    context = H.resolve_stk_factor_pro_bootstrap_context(
        NoPG(),
        conn,
        lake_root=args["lake_root"],
        staging_root=args["staging_root"],
        current_run=current,
        run_input=config,
        calendar=(DAY - timedelta(days=1), DAY),
        known_pg=known_pg,
        known_records=known,
    )
    assert context.authorized_missing_count == 2
    assert context.authorization_run_id == "supplement-first"
    assert context.authorized_missing_codes_ref == result.missing_codes_ref
    assert (
        known_pg[("bootstrap_supplement", args["approval"].operation_id)]["totals"][
            "counts"
        ]["current_raw_rows"]
        == 1
    )
    with pytest.raises(ValueError, match="缺口依据已变"):
        H.resolve_stk_factor_pro_bootstrap_context(
            NoPG(),
            conn,
            lake_root=args["lake_root"],
            staging_root=args["staging_root"],
            current_run=SimpleNamespace(
                run_id="bad", parent_run_id=None, root_run_id=None
            ),
            run_input=replace(config, expected_bootstrap_date_result_digest="0" * 64),
            calendar=(DAY - timedelta(days=1), DAY),
            known_pg={},
            known_records=known,
        )


def test_coverage_precedes_dg_events_and_final_record_needs_no_relations(
    prepared_fixture,
    monkeypatch,
):
    """Original synthetic source A=1; current A/B/C=3, no DG id at calculation."""
    from orchestrator.defs.io.stk_factor_pro_candidates import RAW_EXPECTED
    from orchestrator.defs.run_contracts import stk_factor_pro as C
    from tests.test_stk_factor_pro_bootstrap_coverage import (
        B_CODE,
        C_CODE,
        supplement_audits,
    )
    from tests.test_stk_factor_pro_bootstrap_publication import release_date_work

    conn, _known, args, previous = prepared_fixture
    release_date_work(conn, include_source=True)
    known = {}
    raw, silver = supplement_audits(
        conn, args, (A, B_CODE, C_CODE), known_records=known
    )
    inputs = G.prepare_stk_factor_pro_coverage_inputs(
        conn,
        lake_root=args["lake_root"],
        trade_date=DAY,
        inherited_facts={
            path: fact
            for path, fact in args["_basis_inputs"]["files"].items()
            if fact["basis"].trade_date is None
        },
        known_records=known,
    )
    prepared = B.prepare_stk_factor_pro_bootstrap_supplement_date(
        trade_date=DAY,
        raw_audit=raw,
        silver_audit=silver,
        coverage_inputs=inputs,
    )
    digest = B._date_digest(
        args["approval"],
        args["_approval_digest"],
        DAY,
        args["source_complete"],
        (raw.file_sha256, silver.file_sha256),
        prepared["basis_files"],
        prepared["is_open"],
    )
    calculated = B.compute_stk_factor_pro_bootstrap_coverage_date(
        conn,
        lake_root=args["lake_root"],
        staging_root=args["staging_root"],
        approval=args["approval"],
        prepared=prepared,
        raw_relation=RAW_EXPECTED,
        diagnostic_run=None,
        input_digest=digest,
        check_space=lambda *a, **k: None,
        known_records=known,
    )
    assert calculated["coverage_counts"].missing_count == 0
    assert calculated["coverage_counts"].actual_count == 3
    assert calculated["missing_codes_ref"] is None
    release_date_work(conn, include_source=True)
    publication = C.StkFactorProBootstrapCurrentPublication(
        "supplement-run",
        DAY,
        11,
        12,
        13,
        14,
        raw.file_sha256,
        silver.file_sha256,
        raw.file_sha256,
        C.STK_FACTOR_PRO_CONTRACT_CONTENT_DIGEST,
        C.STK_FACTOR_PRO_PROCESSING_VERSION,
    )
    # These are pure constructors: file/network/SQL access is unavailable here.
    monkeypatch.setattr(
        B,
        "calculate_stk_factor_pro_coverage",
        lambda *a, **k: pytest.fail("recalculated"),
    )
    final = B.evaluate_stk_factor_pro_bootstrap_coverage_date(
        prepared=prepared,
        calculated=calculated,
        approval_digest=args["_approval_digest"],
        input_digest=digest,
        source_complete=args["source_complete"],
        current_publication=publication,
        previous_result=previous,
    )
    assert (final.source_rows, final.raw_rows, final.silver_rows) == (1, 3, 3)
    assert final.current_publication == publication
    assert (
        C.parse_stk_factor_pro_record(
            type(final), C.stk_factor_pro_record_to_dict(final)
        )
        == final
    )
