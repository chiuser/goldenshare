"""Completed-week contracts and real temporary-file recovery; no formal writes."""

import json
from datetime import datetime
from pathlib import Path

import duckdb
import pytest

from orchestrator.defs.bootstrap.stock_weekly_candidates import fingerprint
from orchestrator.defs.bootstrap.stock_weekly_capture import WeeklyCaptureError
from orchestrator.defs.checks.stock_weekly_checks import audit_weekly_file
from orchestrator.defs.paths import (
    raw_stock_daily_path,
    raw_trade_calendar_path,
    silver_stock_identity_map_path,
)
from orchestrator.defs.run_contracts.stock_weekly import (
    StockWeeklyPointPolicy,
    StockWeeklySource,
)
from orchestrator.defs.source_readiness.stock_weekly import (
    load_weekly_reference,
    verify_weekly_source_completion,
)
from orchestrator.defs.stock_weekly_point import deliver_stock_weekly_point
from orchestrator.defs.stock_weekly_update import (
    completed_week,
    weekly_open_dates,
    weekly_update_intent,
    weekly_window_open,
)
from orchestrator.defs.stock_weekly_update_execution import WeeklyUpdateExecution

from .test_stock_weekly_definitions import frame_for


@pytest.mark.parametrize(
    "stamp,expected",
    [
        ("2026-10-02T19:29:59+08:00", False),
        ("2026-10-02T19:30:00+08:00", True),
        ("2026-10-04T11:30:00+00:00", True),
        ("2026-10-05T00:00:00+08:00", False),
    ],
)
def test_daily_time_gate(stamp, expected):
    assert weekly_window_open(datetime.fromisoformat(stamp)) is expected


def test_completed_friday_and_intent_identity():
    assert not completed_week(
        datetime.fromisoformat("2026-10-01T20:00:00+08:00"), "2026-10-02"
    )
    assert completed_week(
        datetime.fromisoformat("2026-10-02T19:30:00+08:00"), "2026-10-02"
    )
    source = StockWeeklySource.PRIMARY_UNADJUSTED
    first = weekly_update_intent(source, "2026-10-02", "2026-10-04")
    assert first == weekly_update_intent(source, "2026-10-02", "2026-10-04")
    assert (
        first["unit_id"]
        != weekly_update_intent(source, "2026-10-02", "2026-10-05")["unit_id"]
    )
    with pytest.raises(ValueError, match="alternate_automatic_forbidden"):
        weekly_update_intent(
            StockWeeklySource.ALTERNATE_WEEKLY, "2026-10-02", "2026-10-04"
        )
    with pytest.raises(ValueError, match="timezone"):
        weekly_window_open(datetime(2026, 10, 4, 20))  # noqa: DTZ001 -- Explicit naive-input rejection.


def test_calendar_requires_closed_rows_and_keeps_friday():
    calendar = {f"2026-09-{d}": 1 for d in (28, 29, 30)} | {
        "2026-10-01": 0,
        "2026-10-02": 0,
    }
    assert weekly_open_dates("2026-10-02", calendar) == (
        "2026-09-28",
        "2026-09-29",
        "2026-09-30",
    )
    with pytest.raises(ValueError, match="calendar_incomplete"):
        weekly_open_dates("2026-10-02", {"2026-09-30": 1})
    assert weekly_open_dates("2026-10-02", dict.fromkeys(calendar, 0)) == ()


def reference():
    return {
        "week": "2026-10-02",
        "expected": {"000001.SZ": "20260930", "000002.SZ": "20260928"},
        "canonical": {
            "000001.SZ": "000001.SZ",
            "000002.SZ": "000002.SZ",
            "000003.SZ": "000003.SZ",
        },
    }


def test_per_stock_cutoff_halt_and_extra_retired():
    result = verify_weekly_source_completion(
        [
            ("000001.SZ", "20261002", "20261004", "week"),
            ("000002.SZ", "20261002", "20260928", "week"),
            ("000003.SZ", "20261002", "20260921", "week"),
        ],
        reference(),
    )
    assert result == {"expected_codes": 2, "source_rows": 3, "reason_code": "ready"}


@pytest.mark.parametrize(
    "rows,reason",
    [
        ([], "weekly_source_empty_or_over_budget"),
        (
            [
                ("000001.SZ", "20261002", "20260929", "week"),
                ("000002.SZ", "20261002", "20260928", "week"),
            ],
            "weekly_source_not_ready",
        ),
        (
            [("000001.SZ", "20261002", "20260930", "week")],
            "weekly_source_coverage_incomplete",
        ),
        ([("000004.SZ", "20261002", "20260930", "week")], "weekly_identity_unresolved"),
        (
            [("000001.SZ", "20260930", "20260930", "week")],
            "weekly_source_coordinate_mismatch",
        ),
        ([("000001.SZ", "20261002", None, "week")], "weekly_source_cutoff_invalid"),
    ],
)
def test_source_completion_negative(rows, reason):
    with pytest.raises(WeeklyCaptureError, match=reason):
        verify_weekly_source_completion(rows, reference())


def write_upstream(tmp_path):
    root = tmp_path / "lake"
    with duckdb.connect() as con:
        calendar = raw_trade_calendar_path(root)
        identity = silver_stock_identity_map_path(root)
        daily = raw_stock_daily_path(root, "2020-02-28")
        for path in (calendar, identity, daily):
            path.parent.mkdir(parents=True, exist_ok=True)
        con.execute(
            "CREATE TABLE calendar AS SELECT 'SSE' AS exchange, '202002' || CAST(day AS VARCHAR) AS cal_date, CASE WHEN day=28 THEN 1 ELSE 0 END AS is_open FROM range(24,29) t(day)"
        )
        con.execute("COPY calendar TO ? (FORMAT PARQUET)", [str(calendar)])
        con.execute(
            "CREATE TABLE identity AS SELECT '000005.SZ' AS source_ts_code,'000005.SZ' AS latest_ts_code,'confirmed' AS confidence"
        )
        con.execute("COPY identity TO ? (FORMAT PARQUET)", [str(identity)])
        con.execute(
            "CREATE TABLE daily AS SELECT '000005.SZ' AS ts_code, '20200228' AS trade_date"
        )
        con.execute("COPY daily TO ? (FORMAT PARQUET)", [str(daily)])
    return root


def delivery(tmp_path, source, fetch, **kwargs):
    root = tmp_path / "lake"
    update = WeeklyUpdateExecution(
        source,
        "2020-02-28",
        "2020-02-28",
        target_root=root,
        upstream_ready=lambda days: True,
    )
    return deliver_stock_weekly_point(
        source,
        "2020-02-28",
        target_root=root,
        staging_root=tmp_path / "stage",
        worker=None,
        fetch=fetch,
        update=update,
        **kwargs,
    )


@pytest.mark.parametrize(
    "source", (StockWeeklySource.PRIMARY_UNADJUSTED, StockWeeklySource.PRIMARY_ADJUSTED)
)
def test_automatic_delivery_actual_receipts_checks_and_no_refetch(tmp_path, source):
    write_upstream(tmp_path)
    calls = []

    def fetch(*args):
        calls.append(args[1])
        return frame_for(source)

    first = delivery(tmp_path, source, fetch)
    before = fingerprint(Path(first["path"]))
    assert (
        audit_weekly_file(
            source,
            "2020-02-28",
            tmp_path / "lake",
            kind="delivery_reconciliation",
        )
        == 1
    )
    second = delivery(
        tmp_path, source, lambda *args: pytest.fail("replay fetched source")
    )
    assert second["audit_hash"] == first["audit_hash"]
    assert fingerprint(Path(first["path"])) == before
    assert len(calls) == 1 and calls[0] == {
        "trade_date": "20200228",
        "freq": "week",
        "limit": 6000,
        "offset": 0,
    }


def test_successful_page_survives_cancel_and_resumes(tmp_path, monkeypatch):
    write_upstream(tmp_path)
    from orchestrator.defs import stock_weekly_point as point

    monkeypatch.setattr(
        point,
        "StockWeeklyPointPolicy",
        lambda: StockWeeklyPointPolicy(page_limit=1, page_call_cap=4),
    )
    source = StockWeeklySource.PRIMARY_UNADJUSTED
    calls = []

    def fetch(*args):
        calls.append(args[1]["offset"])
        return frame_for(source)

    def canceled():
        return bool(list((tmp_path / "stage").glob("**/receipt.json")))

    with pytest.raises(WeeklyCaptureError, match="canceled"):
        delivery(tmp_path, source, fetch, cancel=canceled)
    assert calls == [0]
    assert not list(
        (tmp_path / "lake").glob("raw/tushare/stk_period_bar_week/**/*.parquet")
    )

    def finish(*args):
        calls.append(args[1]["offset"])
        assert args[1]["offset"] == 1
        return frame_for(source).iloc[:0]

    result = delivery(tmp_path, source, finish)
    assert calls == [0, 1] and result["requests"] == 2


def test_not_ready_keeps_capture_without_formal_file(tmp_path):
    root = write_upstream(tmp_path)
    frame = frame_for(StockWeeklySource.PRIMARY_UNADJUSTED)
    frame["end_date"] = "20200227"
    with pytest.raises(WeeklyCaptureError, match="weekly_source_not_ready"):
        delivery(tmp_path, StockWeeklySource.PRIMARY_UNADJUSTED, lambda *args: frame)
    assert list((tmp_path / "stage").glob("**/receipt.json"))
    assert not list(root.glob("raw/tushare/stk_period_bar_week/**/*.parquet"))


def test_reference_missing_unready_and_changes(tmp_path):
    root = write_upstream(tmp_path)
    with duckdb.connect() as con:
        with pytest.raises(WeeklyCaptureError, match="weekly_upstream_not_ready"):
            load_weekly_reference(
                con, root, "2020-02-28", upstream_ready=lambda days: False
            )
        ref = load_weekly_reference(
            con, root, "2020-02-28", upstream_ready=lambda days: True
        )
        assert ref["expected"] == {"000005.SZ": "20200228"}
    raw_stock_daily_path(root, "2020-02-28").write_bytes(b"changed")
    from orchestrator.defs.source_readiness.stock_weekly import (
        assert_weekly_references_unchanged,
    )

    with pytest.raises(WeeklyCaptureError, match="weekly_reference_changed"):
        assert_weekly_references_unchanged(ref["references"])


def test_observation_failure_after_promote_keeps_file_and_recovers(tmp_path):
    write_upstream(tmp_path)
    source = StockWeeklySource.PRIMARY_UNADJUSTED

    def progress(payload):
        if payload["stage"] == "verified":
            raise RuntimeError("offline observation failure")

    with pytest.raises(RuntimeError, match="observation"):
        delivery(tmp_path, source, lambda *args: frame_for(source), progress=progress)
    assert list(
        (tmp_path / "lake").glob("raw/tushare/stk_period_bar_week/**/*.parquet")
    )
    result = delivery(
        tmp_path, source, lambda *args: pytest.fail("unexpected source call")
    )
    assert result["rows"] == 1


@pytest.mark.parametrize("failure", ["source_failed", "source_timeout"])
def test_request_budget_persists_across_reexecution_no_alternate(tmp_path, failure):
    write_upstream(tmp_path)
    source = StockWeeklySource.PRIMARY_UNADJUSTED
    calls = []

    def fail(*args):
        calls.append(args[1])
        error = WeeklyCaptureError(failure)
        error.add_note("source_diagnostic=network_proxy")
        raise error

    with pytest.raises(WeeklyCaptureError, match=failure) as error:
        delivery(tmp_path, source, fail)
    assert str(error.value) == failure
    assert error.value.__notes__ == ["source_diagnostic=network_proxy"]
    assert len(calls) == 3
    with pytest.raises(WeeklyCaptureError, match="point_request_cap_exceeded"):
        delivery(tmp_path, source, fail)
    assert len(calls) == 3
    control = json.loads(
        next((tmp_path / "stage").glob("**/requests.json")).read_text()
    )
    assert control["calls"] == 3 and control["page_attempts"] == {"0": 3}


def test_revision_plan_does_not_modify_existing_file(tmp_path):
    root = write_upstream(tmp_path)
    source = StockWeeklySource.PRIMARY_UNADJUSTED
    first = deliver_stock_weekly_point(
        source,
        "2020-02-28",
        target_root=root,
        staging_root=tmp_path / "stage",
        worker=None,
        fetch=lambda *args: frame_for(source),
    )
    before = fingerprint(Path(first["path"]))
    changed = frame_for(source)
    changed["close"] = "99.0000"
    with pytest.raises(WeeklyCaptureError, match="revision_required"):
        delivery(tmp_path, source, lambda *args: changed)
    assert fingerprint(Path(first["path"])) == before
    plan = json.loads(
        next((tmp_path / "stage").glob("**/revision_required.json")).read_text()
    )
    assert plan["difference_rows"] == 1 and plan["automatic_overwrite"] is False


def test_process_exit_after_sealed_page_then_resume(tmp_path):
    import os
    import subprocess
    import sys
    import tempfile

    write_upstream(tmp_path)
    script = tmp_path / "exit.py"
    script.write_text("""
import os,sys
from pathlib import Path
from orchestrator.defs import stock_weekly_point as point
from orchestrator.defs.run_contracts.stock_weekly import StockWeeklyPointPolicy,StockWeeklySource
from tests.test_stock_weekly_definitions import frame_for
from tests.test_stock_weekly_update import delivery
point.StockWeeklyPointPolicy=lambda:StockWeeklyPointPolicy(page_limit=1,page_call_cap=4)
root=Path(sys.argv[1])
def cancel():
    if list((root/'stage').glob('**/receipt.json')): os._exit(17)
    return False
delivery(root,StockWeeklySource.PRIMARY_UNADJUSTED,lambda *args:frame_for(StockWeeklySource.PRIMARY_UNADJUSTED),cancel=cancel)
""")
    project = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(script), str(tmp_path)],
        env={
            "PATH": os.environ["PATH"],
            "PYTHONPATH": f"{project / 'src'}:{project}",
            "TMPDIR": tempfile.gettempdir(),
        },
        capture_output=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 17, result.stderr.decode()
    assert list((tmp_path / "stage").glob("**/receipt.json"))
    from orchestrator.defs import stock_weekly_point as point

    original = point.StockWeeklyPointPolicy
    point.StockWeeklyPointPolicy = lambda: StockWeeklyPointPolicy(
        page_limit=1, page_call_cap=4
    )
    try:

        def finish(*args):
            assert args[1]["offset"] == 1
            return frame_for(StockWeeklySource.PRIMARY_UNADJUSTED).iloc[:0]

        resumed = delivery(tmp_path, StockWeeklySource.PRIMARY_UNADJUSTED, finish)
        assert resumed["requests"] == 2
    finally:
        point.StockWeeklyPointPolicy = original


@pytest.mark.parametrize(
    "source", (StockWeeklySource.PRIMARY_UNADJUSTED, StockWeeklySource.PRIMARY_ADJUSTED)
)
def test_automatic_real_asset_job_partitioned_checks(tmp_path, monkeypatch, source):
    import dagster as dg

    from orchestrator.defs.assets import stock_weekly as assets
    from orchestrator.defs.partitions import cn_a_stock_week_ends
    from orchestrator.defs.run_contracts.stock_weekly import (
        weekly_asset_key,
        weekly_job_name,
    )

    from .test_stock_weekly_definitions import bind_delivery, definition_for

    write_upstream(tmp_path)
    bind_delivery(monkeypatch, tmp_path, source)
    monkeypatch.setattr(assets, "weekly_upstream_events_ready", lambda *args: True)
    definitions, _, _ = definition_for(tmp_path, source)
    with dg.DagsterInstance.ephemeral() as instance:
        instance.add_dynamic_partitions(cn_a_stock_week_ends.name, ["2020-02-28"])
        result = definitions.resolve_job_def(
            weekly_job_name(source)
        ).execute_in_process(
            instance=instance,
            partition_key="2020-02-28",
            run_config={
                "ops": {
                    weekly_asset_key(source): {
                        "config": {"automatic_intent_date": "2020-02-28"}
                    }
                }
            },
        )
        assert result.success
        checks = [
            e.event_specific_data
            for e in result.all_events
            if e.event_type_value == "ASSET_CHECK_EVALUATION"
        ]
        assert len(checks) == 3 and all(
            e.passed and e.partition == "2020-02-28" for e in checks
        )


def test_full_page_cap_is_not_complete(tmp_path, monkeypatch):
    from orchestrator.defs import stock_weekly_point as point

    write_upstream(tmp_path)
    monkeypatch.setattr(
        point,
        "StockWeeklyPointPolicy",
        lambda: StockWeeklyPointPolicy(page_limit=1, page_call_cap=4),
    )
    calls = []

    def fetch(*args):
        offset = args[1]["offset"]
        calls.append(offset)
        frame = frame_for(StockWeeklySource.PRIMARY_UNADJUSTED)
        frame["ts_code"] = f"{offset + 5:06d}.SZ"
        return frame

    with pytest.raises(WeeklyCaptureError, match="point_page_cap_exceeded"):
        delivery(tmp_path, StockWeeklySource.PRIMARY_UNADJUSTED, fetch)
    assert calls == [0, 1, 2, 3]
    assert not list(
        (tmp_path / "lake").glob("raw/tushare/stk_period_bar_week/**/*.parquet")
    )


@pytest.mark.parametrize(
    "missing,failed,expected",
    [(False, False, True), (True, False, False), (False, True, False)],
)
def test_daily_event_batch_matches_target_identity_and_is_bounded(
    monkeypatch, missing, failed, expected
):
    from types import SimpleNamespace as NS

    from orchestrator.defs import stock_weekly_update_state as state
    from orchestrator.defs.sensors.readiness import RAW_STOCK_DAILY_READINESS_SPEC

    days = ["2026-09-28", "2026-09-29", "2026-09-30"]
    mats = [
        NS(partition_key=day, storage_id=index + 10) for index, day in enumerate(days)
    ]
    monkeypatch.setattr(state, "weekly_event_binding", lambda *args: (None, True))
    calls = []

    def fetch(*args, **kwargs):
        calls.append(("mat", kwargs["limit"]))
        assert set(args[0].asset_partitions) == set(days)
        return NS(records=mats[:-1] if missing else mats)

    def execution(storage_id, passed):
        return NS(
            status=NS(value="SUCCEEDED" if passed else "FAILED"),
            event=NS(
                dagster_event=NS(
                    event_specific_data=NS(
                        target_materialization_data=NS(storage_id=storage_id),
                        passed=passed,
                        blocking=True,
                    )
                )
            ),
        )

    def history(key, *, limit):
        calls.append(("history", limit))
        assert limit == 20
        rows = [execution(mat.storage_id, True) for mat in mats]
        return [execution(10, False), *rows] if failed else rows

    instance = NS(
        fetch_materializations=fetch,
        event_log_storage=NS(get_asset_check_execution_history=history),
    )
    assert state.weekly_upstream_events_ready(instance, days) is expected
    assert len(calls) <= 1 + len(RAW_STOCK_DAILY_READINESS_SPEC.blocking_check_names)
