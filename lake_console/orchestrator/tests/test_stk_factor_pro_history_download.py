"""Mode-5 history download adapter boundaries, using only isolated resources."""

from dataclasses import replace
from datetime import date

import pytest

from orchestrator.defs.io import stk_factor_pro_download as downloads
from orchestrator.defs.io import stk_factor_pro_history as history
from orchestrator.defs.paths import stk_factor_pro_run_staging_root
from orchestrator.defs.run_contracts import stk_factor_pro as models
from orchestrator.tushare_download import DownloadControl, DownloadMode, DownloadStatus
from orchestrator.tushare_download.download_errors import (
    DownloadError,
    DownloadErrorCode,
    ErrorDetails,
)
from orchestrator.tushare_download.download_models import CleanupIssue
from tests.stk_factor_pro_history_test_support import (
    NAMES,
    HistoryDownloader,
    check_test_space,
    connection,
    contract,
    eligibility,
    identity,
    roots,
    row,
    write_factor_file,
)

T, P = date(2026, 10, 16), date(2026, 10, 15)
A, B = "000001.SZ", "600000.SH"


def prepare(conn, tmp_path, *, kind="normal", run="run-a", known_records):
    lake, staging = roots(tmp_path)
    t = ((A, 1.0), (B, 2.0)) if kind == "no_action" else ((A, 2.0), (B, 3.0))
    p = ((A, 1.0), (B, 2.0))
    refs = (
        write_factor_file(conn, lake, T, t),
        write_factor_file(conn, lake, P, p),
    )
    starts = (
        models.StkFactorProHistoryStart(A, P, 1, P),
        models.StkFactorProHistoryStart(B, None, None, None)
        if kind == "unknown"
        else models.StkFactorProHistoryStart(
            B,
            date(2026, 10, 14) if kind == "different_starts" else P,
            1,
            date(2026, 10, 14) if kind == "different_starts" else P,
        ),
    )
    old = models.StkFactorProRecordedResults(
        T, None, None, None, None, None, None, (), (), None, None
    )
    factor_relations, lifecycle_relation = (
        history.prepare_stk_factor_pro_history_inputs(
            conn,
            identity=identity(run),
            lake_root=lake,
            factor_t=refs[0],
            factor_p=refs[1],
            known_records=known_records,
            check_cancel=lambda: None,
        )
    )
    plan, ranges, plan_ref = history.build_stk_factor_pro_history_plan(
        conn,
        identity=identity(run),
        contract=contract(),
        lake_root=lake,
        staging_root=staging,
        factor_t=refs[0],
        factor_p=refs[1],
        prior_results=old,
        history_starts=starts,
        check_cancel=lambda: None,
        known_records=known_records,
        factor_relations=factor_relations,
        lifecycle_relation=lifecycle_relation,
    )
    root = stk_factor_pro_run_staging_root(staging, run, T.isoformat())
    valid = eligibility(plan.identity, plan, stock_count=2)
    expected_units = (
        ()
        if kind in ("unknown", "no_action")
        else history.resolve_stk_factor_pro_history_units(
            conn,
            plan=plan,
            ranges=ranges,
            prior_results=old,
            staging_root=staging,
            known_records=known_records,
        )
    )
    args = {
        "expected_units": expected_units,
        "check_space": check_test_space,
        "plan_ref": plan_ref,
        "identity": plan.identity,
        "contract": plan.contract,
        "plan": plan,
        "ranges": ranges,
        "prior_results": old,
        "eligibility": valid,
        "lake_root": lake,
        "staging_root": staging,
        "recheck_inputs": lambda: (
            refs[0],
            refs[1],
            valid.raw_coverage,
            valid.target_silver,
        ),
        "check_cancel": lambda: None,
    }
    return root, args


def sample_downloader(**kwargs):
    return HistoryDownloader(
        {A: (row(A, "20261015"), row(A, "20261016")), B: ()}, **kwargs
    )


def run_download(conn, args, downloader, *, known_records):
    return downloads.download_stk_factor_pro_history(
        conn,
        **args,
        downloader=downloader,
        known_records=known_records,
    )


def assert_no_complete(root):
    assert not (root / "source/history/source-complete.json").exists()
    assert not (root / "candidates").exists()
    assert not (root / "publication").exists()


def assert_no_relations(conn, *, retained_source=None):
    names = conn.execute(
        "SELECT table_name FROM duckdb_tables() WHERE temporary UNION ALL "
        "SELECT view_name FROM duckdb_views() WHERE temporary AND NOT internal"
    ).fetchall()
    actual = {name for (name,) in names if name.startswith("stk_factor_pro_")}
    if retained_source is not None:
        assert {
            retained_source,
            "stk_factor_pro_history_factor_t",
            "stk_factor_pro_history_factor_p",
        } <= actual
        assert actual <= {
            retained_source,
            "stk_factor_pro_history_factor_t",
            "stk_factor_pro_history_factor_p",
            "stk_factor_pro_history_lifecycle",
        }
    else:
        assert not actual


def test_all_native_units_and_zero_row_schema_saved_before_current_source_is_returned(
    tmp_path, monkeypatch
):
    known_records = {}
    with connection(tmp_path) as conn:
        root, args = prepare(conn, tmp_path, known_records=known_records)
        downloader = sample_downloader()
        written = []
        original = history.write_stk_factor_pro_source_complete

        def after_close(*positional, **keywords):
            assert downloader.sessions and all(
                item.closed and item.summary.status is DownloadStatus.SUCCEEDED
                for item in downloader.sessions
            )
            written.append(True)
            return original(*positional, **keywords)

        monkeypatch.setattr(
            history, "write_stk_factor_pro_source_complete", after_close
        )
        if hasattr(downloads, "write_stk_factor_pro_source_complete"):
            monkeypatch.setattr(
                downloads, "write_stk_factor_pro_source_complete", after_close
            )
        verified = run_download(conn, args, downloader, known_records=known_records)
        assert isinstance(verified, models.VerifiedSource) and written == [True]
        source = verified.source_complete
        assert source.identity == args["identity"]
        assert source.completed_unit_count == 2
        assert source.expected_units == (
            models.UnitProjection(5, A, None, P, T),
            models.UnitProjection(5, B, None, P, T),
        )
        files = history.read_stk_factor_pro_source_files(
            root,
            source.files_manifest_ref,
            connection=conn,
            identity=args["identity"],
            contract=args["contract"],
            known_records=known_records,
        )
        by_code = {item.object_code: item for item in files}
        assert set(by_code) == {A, B}
        for code, count in ((A, 2), (B, 0)):
            item = by_code[code]
            assert (
                item.source_row_count == item.saved_row_count == item.file_rows == count
            )
            assert item.mode == 5 and item.point is None
            assert (item.start_date, item.end_date) == (P, T)
            assert (
                item.file_relative_path
                == f"source/history/units/{item.unit_key}.parquet"
            )
            path = root / item.file_relative_path
            actual_schema = tuple(
                (field, kind)
                for field, kind, *_ in conn.execute(
                    "DESCRIBE SELECT * FROM read_parquet(?,hive_partitioning=false)",
                    [str(path)],
                ).fetchall()
            )
            # Source document 328 independently defines two string fields and
            # 259 numeric fields. Empty units retain this exact full schema.
            assert actual_schema == tuple(
                (name, "VARCHAR" if index < 2 else "DOUBLE")
                for index, name in enumerate(NAMES)
            )
        data = conn.execute(
            "SELECT ts_code,trade_date,pe,macd_bfq FROM read_parquet(?,hive_partitioning=false) ORDER BY trade_date",
            [str(root / by_code[A].file_relative_path)],
        ).fetchall()
        assert data == [(A, "20261015", None, -1.25), (A, "20261016", None, -1.25)]
        native = tuple(
            unit for session in downloader.sessions for unit in session.units
        )
        assert {item.component_unit_id for item in files} == {
            item.unit_id for item in native
        }
        assert all(
            task.mode is DownloadMode.BY_OBJECT_RANGE for task, _ in downloader.calls
        )
        assert_no_relations(conn, retained_source=verified.source_relation)
        downloads.release_stk_factor_pro_history_source(conn)
        assert_no_relations(conn)


@pytest.mark.parametrize("kind", ["unknown", "no_action"])
def test_unknown_or_no_work_rejects_before_network(tmp_path, kind):
    known_records = {}
    with connection(tmp_path) as conn:
        root, args = prepare(conn, tmp_path, kind=kind, known_records=known_records)
        downloader = sample_downloader()
        with pytest.raises(ValueError):
            run_download(conn, args, downloader, known_records=known_records)
        assert downloader.calls == []
        assert_no_complete(root)


def test_invalid_eligibility_rejects_before_network(tmp_path):
    known_records = {}
    with connection(tmp_path) as conn:
        root, args = prepare(conn, tmp_path, known_records=known_records)
        valid = args["eligibility"]
        args["eligibility"] = replace(
            valid, raw_coverage=replace(valid.raw_coverage, complete=False)
        )
        downloader = sample_downloader()
        with pytest.raises(ValueError):
            run_download(conn, args, downloader, known_records=known_records)
        assert downloader.calls == []
        assert_no_complete(root)


def test_old_run_plan_cannot_supply_a_new_run_download(tmp_path):
    known_records = {}
    with connection(tmp_path) as conn:
        root, args = prepare(conn, tmp_path, run="run-old", known_records=known_records)
        args["identity"] = identity("run-new")
        downloader = sample_downloader()
        with pytest.raises(ValueError):
            run_download(conn, args, downloader, known_records=known_records)
        assert downloader.calls == []
        assert_no_complete(root)


def test_close_failure_1304_never_forms_complete_source(tmp_path):
    known_records = {}
    with connection(tmp_path) as conn:
        root, args = prepare(conn, tmp_path, known_records=known_records)
        downloader = sample_downloader(
            close_error=DownloadError(DownloadErrorCode.CLEANUP)
        )
        with pytest.raises(DownloadError) as captured:
            run_download(conn, args, downloader, known_records=known_records)
        assert captured.value.code is DownloadErrorCode.CLEANUP
        assert downloader.sessions[0].closed
        assert_no_complete(root)
        assert_no_relations(conn)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", DownloadStatus.FAILED),
        ("status", DownloadStatus.STOPPED),
        ("status", DownloadStatus.CANCELLED),
        ("download_complete", False),
        ("total_units", 3),
        ("completed_units", 1),
        ("delivered_units", 1),
        ("completed_row_count", 7),
        ("row_count", 7),
        ("task_id", "another-session"),
        ("failure", ErrorDetails(code=DownloadErrorCode.TRANSIENT_SOURCE)),
        ("cleanup_errors", (CleanupIssue("transport", "OSError"),)),
    ],
)
def test_bad_final_summary_cannot_release_saved_units_for_publication(
    tmp_path, field, value
):
    known_records = {}
    with connection(tmp_path) as conn:
        root, args = prepare(conn, tmp_path, known_records=known_records)
        downloader = sample_downloader(
            summary_transform=lambda summary: replace(summary, **{field: value})
        )
        with pytest.raises(ValueError):
            run_download(conn, args, downloader, known_records=known_records)
        assert downloader.sessions[0].closed
        assert_no_complete(root)
        assert_no_relations(conn)


def corrupt_result(value, kind):
    if kind == "unit_id":
        return replace(value, unit=replace(value.unit, unit_id="another-native-unit"))
    if kind == "ordinal":
        return replace(value, unit=replace(value.unit, ordinal=99))
    if kind == "mode":
        return replace(value, unit=replace(value.unit, mode=DownloadMode.BY_POINT))
    if kind == "half":
        return replace(
            value, termination=replace(value.termination, all_scopes_complete=False)
        )
    if kind == "count":
        return replace(
            value,
            statistics=replace(value.statistics, row_count=len(value.records) + 1),
        )
    if kind == "observed_fields":
        return replace(value, observed_field_sets=(NAMES[:-1],))
    if not value.records:
        return value
    record = value.records[0]
    if kind == "record_fields":
        record = replace(record, fields=NAMES[:-1], values=record.values[:-1])
    elif kind == "code":
        record = replace(record, values=(B, *record.values[1:]))
    elif kind == "before":
        record = replace(record, values=(A, "20261014", *record.values[2:]))
    elif kind == "after":
        record = replace(record, values=(A, "20261017", *record.values[2:]))
    elif kind == "duplicate":
        return replace(value, records=(record, record))
    return replace(value, records=(record, *value.records[1:]))


@pytest.mark.parametrize(
    "kind",
    [
        "unit_id",
        "ordinal",
        "mode",
        "half",
        "count",
        "observed_fields",
        "record_fields",
        "code",
        "before",
        "after",
        "duplicate",
    ],
)
def test_invalid_unit_identity_or_rows_cannot_form_complete_source(tmp_path, kind):
    known_records = {}
    with connection(tmp_path) as conn:
        root, args = prepare(conn, tmp_path, known_records=known_records)
        downloader = sample_downloader(
            result_transform=lambda value: corrupt_result(value, kind)
        )
        with pytest.raises(ValueError):
            run_download(conn, args, downloader, known_records=known_records)
        assert downloader.sessions[0].closed
        assert_no_complete(root)
        assert_no_relations(conn)


def test_per_stock_different_start_dates_use_exact_native_object_ranges(tmp_path):
    known_records = {}
    with connection(tmp_path) as conn:
        root, args = prepare(
            conn, tmp_path, kind="different_starts", known_records=known_records
        )
        downloader = HistoryDownloader(
            {
                A: (row(A, "20261015"),),
                B: (row(B, "20261014"), row(B, "20261016")),
            }
        )
        verified = run_download(conn, args, downloader, known_records=known_records)
        assert verified.source_complete.expected_units == (
            models.UnitProjection(5, A, None, P, T),
            models.UnitProjection(5, B, None, date(2026, 10, 14), T),
        )
        assert len(downloader.calls) == 1
        task = downloader.calls[0][0]
        assert task.objects is None and task.time_range is None
        assert tuple(
            (part.object_code, part.time_range.start, part.time_range.end)
            for part in task.object_ranges
        ) == (
            (A, "2026-10-15", "2026-10-16"),
            (B, "2026-10-14", "2026-10-16"),
        )
        assert (root / "source/history/source-complete.json").is_file()
        assert_no_relations(conn, retained_source=verified.source_relation)
        downloads.release_stk_factor_pro_history_source(conn)
        assert_no_relations(conn)


@pytest.mark.parametrize("kind", ["missing", "extra"])
def test_exact_planned_unit_list_is_required(tmp_path, kind):
    known_records = {}

    class ChangedUnits(HistoryDownloader):
        def download(self, task, **kwargs):
            session = super().download(task, **kwargs)
            session.units = (
                session.units[:-1]
                if kind == "missing"
                else (*session.units, session.units[-1])
            )
            return session

    with connection(tmp_path) as conn:
        root, args = prepare(conn, tmp_path, known_records=known_records)
        downloader = ChangedUnits({A: (row(A, "20261015"),), B: ()})
        with pytest.raises(ValueError):
            run_download(conn, args, downloader, known_records=known_records)
        assert_no_complete(root)
        assert_no_relations(conn)


def test_business_source_copy_failure_is_not_retried_or_followed_by_another_unit(
    tmp_path,
):
    known_records = {}

    class FailingCopy:
        def __init__(self, conn):
            self.conn, self.copy_attempts = conn, 0

        def __getattr__(self, key):
            return getattr(self.conn, key)

        def execute(self, query, parameters=None):
            if "COPY" in query and "source/history/units/" in query:
                self.copy_attempts += 1
                raise OSError("test: local source write failed")
            return (
                self.conn.execute(query)
                if parameters is None
                else self.conn.execute(query, parameters)
            )

    with connection(tmp_path) as conn:
        root, args = prepare(conn, tmp_path, known_records=known_records)
        failing = FailingCopy(conn)
        downloader = sample_downloader()
        with pytest.raises(OSError, match="local source write"):
            run_download(failing, args, downloader, known_records=known_records)
        assert failing.copy_attempts == 1
        assert len(downloader.calls) == 1
        assert downloader.sessions[0].closed and downloader.sessions[0].delivered == 1
        assert_no_complete(root)
        assert_no_relations(conn)


def test_cancel_after_first_saved_unit_stops_before_next_unit_and_complete(tmp_path):
    known_records = {}
    with connection(tmp_path) as conn:
        root, args = prepare(conn, tmp_path, known_records=known_records)
        downloader = sample_downloader()

        def cancelled():
            if tuple((root / "source/history/units").glob("*.parquet")):
                raise RuntimeError("test: cancelled after unit save")

        args["check_cancel"] = cancelled
        with pytest.raises(RuntimeError, match="cancelled after unit"):
            run_download(conn, args, downloader, known_records=known_records)
        assert downloader.sessions[0].closed and downloader.sessions[0].delivered == 1
        assert_no_complete(root)
        assert_no_relations(conn)


def test_recheck_failure_is_not_a_swallowed_progress_notification(tmp_path):
    known_records = {}
    with connection(tmp_path) as conn:
        root, args = prepare(conn, tmp_path, known_records=known_records)
        downloader = sample_downloader()

        def failed():
            raise RuntimeError("test: cannot confirm upstream inputs")

        args["recheck_inputs"] = failed
        with pytest.raises(RuntimeError, match="confirm upstream"):
            run_download(conn, args, downloader, known_records=known_records)
        assert downloader.calls == []
        assert_no_complete(root)


def test_progress_and_control_are_forwarded_without_data_saving_callback(tmp_path):
    known_records = {}
    with connection(tmp_path) as conn:
        root, args = prepare(conn, tmp_path, known_records=known_records)
        downloader = sample_downloader()
        received = []
        callback = received.append
        control = DownloadControl(is_cancelled=lambda: False)
        args.update(on_progress=callback, control=control)
        run_download(conn, args, downloader, known_records=known_records)
        assert all(
            kwargs["on_progress"] is callback and kwargs["control"] is control
            for _, kwargs in downloader.calls
        )
        assert (
            received == []
        )  # The business adapter does not manufacture row callbacks.
        assert (root / "source/history/source-complete.json").is_file()
