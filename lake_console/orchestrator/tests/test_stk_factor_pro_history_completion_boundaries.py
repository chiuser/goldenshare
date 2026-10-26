"""Independent current-scope completion and failed-run re-entry boundaries."""

import json
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import dagster as dg
import pytest

from orchestrator.defs.checks.stk_factor_pro import factor_file_sha
from orchestrator.defs.io import stk_factor_pro_download as downloads
from orchestrator.defs.io import stk_factor_pro_history as history
from orchestrator.defs.io import stk_factor_pro_publication as publication
from orchestrator.defs.paths import (
    raw_stk_factor_pro_path,
    silver_stock_factor_pro_path,
    stk_factor_pro_run_staging_root,
)
from orchestrator.defs.run_contracts import stk_factor_pro as models
from tests.stk_factor_pro_history_test_support import (
    HistoryDownloader,
    connection,
    contract,
    eligibility,
    identity,
    roots,
    row,
    write_factor_file,
)
from tests.test_stk_factor_pro_history_publication_batches import (
    assert_clean,
    write_rows,
)
from tests.test_stk_factor_pro_history_scope_boundaries import old_success, range_row

T, P, S = date(2026, 10, 16), date(2026, 10, 15), date(2026, 10, 14)
A, B, C = "000001.SZ", "600000.SH", "000002.SZ"


def empty_prior():
    return models.StkFactorProRecordedResults(
        T, None, None, None, None, None, None, (), (), None, None
    )


def complete_path(root):
    return root / "publication/history/publication-complete.json"


def read_completion(root):
    return models.parse_stk_factor_pro_record(
        models.PublicationCompleteRecord, json.loads(complete_path(root).read_text())
    )


def prepare(
    conn,
    tmp_path,
    *,
    run="run-a",
    start=S,
    codes=(A, B),
    old=None,
    supplied_rows=None,
):
    lake, staging = roots(tmp_path)
    all_codes = tuple(sorted({A, B, C}))
    target_paths = (
        raw_stk_factor_pro_path(lake, T.isoformat()),
        silver_stock_factor_pro_path(lake, T.isoformat()),
    )
    # Formal T belongs only to the daily path. Historical source below still
    # includes T but must leave these independently initialized values intact.
    if not target_paths[0].exists():
        t_rows = tuple(row(code, "20261016", close=Decimal(99)) for code in all_codes)
        write_rows(conn, target_paths[0], t_rows, layer="raw")
        write_rows(conn, target_paths[1], t_rows, layer="silver")
    factors = (
        write_factor_file(
            conn,
            lake,
            T,
            tuple((code, 2.0 if code in codes else 1.0) for code in all_codes),
        ),
        write_factor_file(conn, lake, P, tuple((code, 1.0) for code in all_codes)),
    )
    old = empty_prior() if old is None else old
    run_identity = identity(run)
    plan = history.build_stk_factor_pro_history_plan(
        conn,
        identity=run_identity,
        contract=contract(),
        lake_root=lake,
        staging_root=staging,
        factor_t=factors[0],
        factor_p=factors[1],
        prior_results=old,
        history_starts=tuple(
            models.StkFactorProHistoryStart(code, start, 1, start)
            for code in sorted(codes)
        ),
        check_cancel=lambda: None,
    )
    root = stk_factor_pro_run_staging_root(staging, run, T.isoformat())
    ranges = history.read_stk_factor_pro_history_ranges(conn, root=root, plan=plan)
    valid = eligibility(
        run_identity,
        plan,
        factor_file_sha(target_paths[0]),
        factor_file_sha(target_paths[1]),
        stock_count=len(all_codes),
    )
    dates = (P, T) if start == P else (S, P, T)
    supplied_rows = (
        {
            code: tuple(row(code, day.strftime("%Y%m%d")) for day in dates)
            for code in codes
        }
        if supplied_rows is None
        else supplied_rows
    )
    downloader = HistoryDownloader(supplied_rows)

    def recheck():
        return factors[0], factors[1], valid.raw_coverage, valid.target_silver

    download_args = {
        "identity": run_identity,
        "contract": contract(),
        "plan": plan,
        "ranges": ranges,
        "prior_results": old,
        "eligibility": valid,
        "lake_root": lake,
        "staging_root": staging,
        "recheck_inputs": recheck,
        "downloader": downloader,
        "check_cancel": lambda: None,
    }
    publish_args = {
        "plan": plan,
        "ranges": ranges,
        "lake_root": lake,
        "staging_root": staging,
        "calendar": dates,
        "registered_dates": dates[:-1],
        "recheck_inputs": recheck,
        "check_cancel": lambda: None,
    }
    return lake, staging, root, downloader, download_args, publish_args


def source_and_publish(conn, download_args, publish_args):
    source = downloads.download_stk_factor_pro_history(conn, **download_args)
    return source, publication.publish_stk_factor_pro_history(
        conn, source=source, **publish_args
    )


def test_successful_ab_old_rows_are_outside_current_c_completion_scope(tmp_path):
    with connection(tmp_path) as conn:
        lake, staging = roots(tmp_path)
        success = old_success(conn, staging, (range_row(A), range_row(B)))
        old = replace(empty_prior(), successful_publication_refs=(success,))
        lake, _, root, downloader, download_args, publish_args = prepare(
            conn,
            tmp_path,
            start=P,
            codes=(A, B, C),
            old=old,
            supplied_rows={C: (row(C, "20261015"), row(C, "20261016"))},
        )
        old_rows = (
            row(A, "20261015", close=Decimal(71)),
            row(B, "20261015", close=Decimal(72)),
        )
        for layer, path in (
            ("raw", raw_stk_factor_pro_path(lake, P.isoformat())),
            ("silver", silver_stock_factor_pro_path(lake, P.isoformat())),
        ):
            write_rows(conn, path, old_rows, layer=layer)
        rechecks = []
        original_recheck = publish_args["recheck_inputs"]

        def recheck():
            rechecks.append(True)
            return original_recheck()

        download_args["recheck_inputs"] = publish_args["recheck_inputs"] = recheck
        source, outputs = source_and_publish(conn, download_args, publish_args)
        results = tuple(outputs)
        assert len(rechecks) == 3
        assert source.source_complete.expected_units == (
            models.UnitProjection(5, C, None, P, T),
        )
        assert download_args["plan"].full_code_count == 3
        assert len(downloader.calls) == 1 and len(downloader.sessions[0].units) == 1
        assert downloader.sessions[0].units[0].object_code == C
        assert all(
            target.unrefreshed_count == 0 and target.scope_rows == 1
            for target, _ in results
        )
        completed = read_completion(root)
        assert completed.scope_digest == source.source_complete.scope_digest
        assert (
            completed.history_input_digest
            == source.source_complete.history_input_digest
        )
        assert completed.targets == tuple(target for target, _ in results)
        assert all(
            target.file_rows == 3 and target.scope_rows == 1
            for target in completed.targets
        )
        for path in (
            raw_stk_factor_pro_path(lake, P.isoformat()),
            silver_stock_factor_pro_path(lake, P.isoformat()),
        ):
            assert conn.execute(
                "SELECT ts_code,close FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code",
                [str(path)],
            ).fetchall() == [(A, 71.0), (C, 10.0), (B, 72.0)]
        assert_clean(conn)


def test_missing_old_scope_key_keeps_valid_files_but_fails_whole_history(tmp_path):
    with connection(tmp_path) as conn:
        lake, _, root, _, download_args, publish_args = prepare(
            conn,
            tmp_path,
            supplied_rows={
                A: (row(A, "20261014"), row(A, "20261016")),
                B: (row(B, "20261014"), row(B, "20261015"), row(B, "20261016")),
            },
        )
        before = (
            row(A, "20261015", close=Decimal(99)),
            row(C, "20261015", close=Decimal(42)),
        )
        for layer, path in (
            ("raw", raw_stk_factor_pro_path(lake, P.isoformat())),
            ("silver", silver_stock_factor_pro_path(lake, P.isoformat())),
        ):
            write_rows(conn, path, before, layer=layer)
        source, outputs = source_and_publish(conn, download_args, publish_args)
        assert source.source_complete.completed_unit_count == 2
        results = []
        with pytest.raises(dg.Failure) as captured:
            # extend keeps each yielded file fact even when exhaustion raises.
            results.extend(outputs)
        assert [(target.trade_date, target.layer) for target, _ in results] == [
            (S, "raw"),
            (S, "silver"),
            (P, "raw"),
            (P, "silver"),
        ]
        assert all(audit is not None and audit.passed for _, audit in results)
        assert sum(target.unrefreshed_count for target, _ in results) == 2
        failure = captured.value
        assert failure.allow_retries is False
        assert failure.metadata["goldenshare/retryable"].value is True
        assert failure.metadata["goldenshare/failure_phase"].value == "history"
        assert "历史修复未完成" in failure.description
        assert not complete_path(root).exists()
        for layer, path in (
            ("raw", raw_stk_factor_pro_path(lake, P.isoformat())),
            ("silver", silver_stock_factor_pro_path(lake, P.isoformat())),
        ):
            assert conn.execute(
                "SELECT ts_code,close FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code",
                [str(path)],
            ).fetchall() == [(A, 99.0), (C, 42.0), (B, 10.0)]
            diagnostic = (
                root / f"publication/history/{P}/{layer}/unrefreshed-keys.parquet"
            )
            assert conn.execute(
                "SELECT layer,ts_code,trade_date FROM read_parquet(?,hive_partitioning=false)",
                [str(diagnostic)],
            ).fetchall() == [(layer, A, P)]
        assert_clean(conn)


class NoOldSourceConnection:
    def __init__(self, conn, old_root):
        self.conn, self.old_root = conn, old_root

    def __getattr__(self, key):
        return getattr(self.conn, key)

    def execute(self, query, parameters=None):
        text = str(query) + repr(parameters)
        assert str(self.old_root / "source") not in text
        assert str(self.old_root / "candidates") not in text
        return (
            self.conn.execute(query)
            if parameters is None
            else self.conn.execute(query, parameters)
        )


@pytest.mark.parametrize("old_stage", ["silver_failed", "physical_complete"])
def test_new_run_redownloads_every_original_unit_despite_prior_source_or_files(
    tmp_path, monkeypatch, old_stage
):
    with connection(tmp_path) as conn:
        lake, _, old_root, _, first_download, first_publish = prepare(
            conn, tmp_path, run="run-failed"
        )
        original_silver = publication.build_stk_factor_pro_silver_candidate

        def failed(*args, **kwargs):
            raise OSError("test: first run silver failed")

        if old_stage == "silver_failed":
            monkeypatch.setattr(
                publication, "build_stk_factor_pro_silver_candidate", failed
            )
        _, old_outputs = source_and_publish(conn, first_download, first_publish)
        if old_stage == "silver_failed":
            with pytest.raises(OSError, match="first run silver"):
                tuple(old_outputs)
            assert not complete_path(old_root).exists()
        else:
            tuple(old_outputs)
            assert complete_path(old_root).exists()
        assert (old_root / "source/history/source-complete.json").exists()
        assert raw_stk_factor_pro_path(lake, S.isoformat()).exists()
        monkeypatch.setattr(
            publication, "build_stk_factor_pro_silver_candidate", original_silver
        )
        previous = replace(
            empty_prior(),
            pending_plan_refs=(
                models.RecordRef(
                    "run-failed",
                    "history-plan.json",
                    factor_file_sha(old_root / "history-plan.json"),
                ),
            ),
        )
        # The stage reader has not established a successful producer here, even
        # when all old physical files and publication-complete happen to exist.
        assert previous.successful_publication_refs == ()
        original_open = Path.open

        def no_old_source(path, *args, **kwargs):
            assert not path.is_relative_to(old_root / "source")
            assert not path.is_relative_to(old_root / "candidates")
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", no_old_source)
        guarded = NoOldSourceConnection(conn, old_root)
        _, _, root, downloader, retry_download, retry_publish = prepare(
            guarded, tmp_path, run="run-retry", old=previous
        )
        source, outputs = source_and_publish(guarded, retry_download, retry_publish)
        results = tuple(outputs)
        assert source.identity.creator_run_id == "run-retry"
        assert len(downloader.calls) == 1
        assert tuple(unit.object_code for unit in downloader.sessions[0].units) == (
            A,
            B,
        )
        assert source.source_complete.expected_units == (
            models.UnitProjection(5, A, None, S, T),
            models.UnitProjection(5, B, None, S, T),
        )
        assert len(results) == 4 and complete_path(root).exists()
        assert_clean(conn)
