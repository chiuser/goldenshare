"""Offline fixtures for month completion, source preservation and durable recovery."""

import json
import os
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pandas as pd
import pytest

from orchestrator.defs.bootstrap.stock_weekly_capture import WeeklyCaptureError
from orchestrator.defs.paths import (
    raw_stock_daily_path,
    raw_stock_monthly_path,
    raw_trade_calendar_path,
    silver_stock_identity_map_path,
)
from orchestrator.defs.run_contracts.stock_monthly import (
    MonthlyUpdatePolicy,
    StockMonthlyPolicy,
    StockMonthlySource,
    month_window,
    monthly_column_specs,
    request_date_for_month,
)
from orchestrator.defs.source_readiness.stock_monthly import (
    assert_month_references_unchanged,
    freeze_month_references,
)
from orchestrator.defs.stock_monthly_point import (
    deliver_month_intent,
    read_month_delivery,
)
from orchestrator.defs.stock_monthly_update import (
    completed_month,
    monthly_update_intent,
    monthly_window_open,
    next_month,
)
from orchestrator.defs.stock_weekly_source import fetch_weekly_request_supervised

SOURCES = tuple(StockMonthlySource)


def parquet(path, frame):
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as con:
        con.register("frame", frame)
        con.execute("COPY frame TO ? (FORMAT PARQUET)", [str(path)])


def setup_reference(tmp_path, month="2020-02", all_weekdays=False):
    lake, staging = tmp_path / "lake", tmp_path / "staging"
    lake.mkdir(exist_ok=True)
    staging.mkdir(exist_ok=True)
    start, end = month_window(month)
    days = [start + timedelta(days=i) for i in range((end - start).days)]
    opened = (
        [d for d in days if d.weekday() < 5]
        if all_weekdays
        else [
            end - timedelta(days=2) if month == "2020-02" else end - timedelta(days=1)
        ]
    )
    parquet(
        raw_trade_calendar_path(lake),
        pd.DataFrame(
            {
                "exchange": ["SSE"] * len(days),
                "cal_date": [d.strftime("%Y%m%d") for d in days],
                "is_open": [int(d in opened) for d in days],
            }
        ),
    )
    parquet(
        silver_stock_identity_map_path(lake),
        pd.DataFrame(
            {
                "source_ts_code": ["000001.SZ", "600000.SH", "000002.SZ"],
                "latest_ts_code": ["000001.SZ", "600000.SH", "000002.SZ"],
                "confidence": ["confirmed"] * 3,
            }
        ),
    )
    for day in opened:
        parquet(
            raw_stock_daily_path(lake, day.isoformat()),
            pd.DataFrame(
                {
                    "ts_code": ["000001.SZ", "600000.SH"],
                    "trade_date": [day.strftime("%Y%m%d")] * 2,
                }
            ),
        )
    return lake, staging, opened


def frame_for(source, month="2020-02", codes=("000001.SZ", "600000.SH")):
    fields = [n for n, _ in monthly_column_specs(source)]
    rows = []
    for code in codes:
        row = dict.fromkeys(fields, "12.3400")
        row.update(
            ts_code=code,
            trade_date=request_date_for_month(month),
            end_date=request_date_for_month(month),
            freq="month",
            amount=None,
        )
        rows.append(row)
    return pd.DataFrame(rows, columns=fields)


def deliver(tmp_path, source, *, month="2020-02", fetch=None, **kwargs):
    lake, staging, _ = (
        setup_reference(tmp_path, month)
        if not (tmp_path / "lake").exists()
        else (tmp_path / "lake", tmp_path / "staging", None)
    )
    if fetch is None:
        fetch = lambda *args: frame_for(source, month)
    return deliver_month_intent(
        source,
        month,
        target_root=lake,
        staging_root=staging,
        worker=None,
        execution_id="test-run",
        upstream_bindings=lambda days: {"ids": list(days)},
        fetch=fetch,
        **kwargs,
    )


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("month", ["2020-02", "2026-05", "2026-09"])
def test_delivery_exact_fields_dates_nulls_and_replay(tmp_path, source, month):
    calls = []
    result = deliver(
        tmp_path,
        source,
        month=month,
        fetch=lambda worker, params, *args: (
            calls.append(params),
            frame_for(source, month),
        )[1],
    )
    assert len(calls) == 1 and calls[0] == {
        "freq": "month",
        "trade_date": request_date_for_month(month),
        "limit": 6000,
        "offset": 0,
    }
    with duckdb.connect() as con:
        observed = con.execute(
            "SELECT ts_code,trade_date,freq,open,amount FROM read_parquet(?,hive_partitioning=false) ORDER BY 1",
            [result["path"]],
        ).fetchall()
        assert [(r[0], r[1], r[2], str(r[3]), r[4]) for r in observed] == [
            (c, request_date_for_month(month), "month", "12.3400", None)
            for c in ("000001.SZ", "600000.SH")
        ]
        read_month_delivery(result, tmp_path / "lake", source, month, connection=con)
    again = deliver(
        tmp_path,
        source,
        month=month,
        fetch=lambda *args: pytest.fail("successful receipt replay requested source"),
    )
    assert again == result


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("trade_date", "20200229", "unexpected_month_source_date"),
        ("freq", "week", "monthly_key_or_date_invalid"),
        ("open", "0.00001", "monthly_decimal_invalid_or_lossy"),
        ("end_date", None, "monthly_identity_or_source_cutoff_invalid"),
        ("end_date", "20200227", "monthly_source_not_ready"),
        ("ts_code", "999999.SZ", "monthly_identity_or_source_cutoff_invalid"),
        ("ts_code", "T600018.SH", "monthly_receipt_codes_invalid"),
    ],
)
def test_invalid_source_is_not_promoted(tmp_path, field, value, reason):
    frame = frame_for(SOURCES[0])
    frame.loc[0, field] = value
    with pytest.raises(ValueError, match=reason):
        deliver(tmp_path, SOURCES[0], fetch=lambda *args: frame)
    assert not raw_stock_monthly_path(tmp_path / "lake", SOURCES[0], "2020-02").exists()


def test_missing_code_and_retired_without_daily(tmp_path):
    with pytest.raises(ValueError, match="monthly_source_missing_keys"):
        deliver(
            tmp_path,
            SOURCES[0],
            fetch=lambda *args: frame_for(SOURCES[0], codes=("000001.SZ",)),
        )
    # 000002.SZ exists in identities but has no actual daily; it is not required.
    result = deliver_month_intent(
        SOURCES[0],
        "2020-02",
        target_root=tmp_path / "lake",
        staging_root=tmp_path / "staging",
        worker=None,
        execution_id="new-intent",
        upstream_bindings=lambda days: {"ids": list(days)},
        fetch=lambda *args: frame_for(SOURCES[0]),
    )
    assert result["rows"] == 2


def test_full_page_empty_tail_and_duplicate_rejected(tmp_path):
    policy = replace(StockMonthlyPolicy(), page_limit=2)
    calls = []

    def fetch(worker, params, *args):
        calls.append(params["offset"])
        return (
            frame_for(SOURCES[0])
            if params["offset"] == 0
            else frame_for(SOURCES[0], codes=())
        )

    result = deliver(tmp_path, SOURCES[0], policy=policy, fetch=fetch)
    assert calls == [0, 2] and result["requests"] == 2
    other = tmp_path / "dup"
    other.mkdir()
    with pytest.raises(ValueError, match="monthly_duplicate_key"):
        deliver(
            other,
            SOURCES[0],
            policy=replace(policy, page_limit=3),
            fetch=lambda *args: pd.concat(
                [frame_for(SOURCES[0]), frame_for(SOURCES[0]).iloc[:1]],
                ignore_index=True,
            ),
        )


def test_cap_full_is_not_truncated_success(tmp_path):
    with pytest.raises(ValueError, match="monthly_page_cap_exceeded"):
        deliver(
            tmp_path,
            SOURCES[0],
            policy=replace(StockMonthlyPolicy(), page_limit=2, max_pages=1),
            fetch=lambda *args: frame_for(SOURCES[0]),
        )
    assert not raw_stock_monthly_path(tmp_path / "lake", SOURCES[0], "2020-02").exists()


@pytest.mark.parametrize("source", SOURCES)
def test_attempt_budget_persists_across_restarts(tmp_path, source):
    calls = []

    def fail(*args):
        calls.append(1)
        error = WeeklyCaptureError("source_failed")
        error.add_note("synthetic-secret-token https://user:password@example.invalid/")
        error.add_note("source_diagnostic=synthetic-secret-token")
        error.add_note("source_diagnostic=network_proxy")
        raise error

    for execution in range(2):
        with pytest.raises(
            ValueError, match="monthly_request_budget_exhausted"
        ) as error:
            deliver(tmp_path, source, fetch=fail)
        assert str(error.value) == "monthly_request_budget_exhausted"
        assert getattr(error.value, "__notes__", []) == (
            ["source_diagnostic=network_proxy"] if execution == 0 else []
        )
    assert len(calls) == 3
    ledger = json.loads(next((tmp_path / "staging").rglob("requests.json")).read_text())
    assert ledger["calls"] == 3 and ledger["attempts"] == {"0": 3}
    assert "synthetic-secret-token" not in json.dumps(ledger)


@pytest.mark.parametrize("source", SOURCES)
def test_monthly_nonretry_failure_keeps_safe_diagnostic(tmp_path, source):
    calls = []

    def fail(*args):
        calls.append(1)
        error = WeeklyCaptureError("source_schema_mismatch")
        error.add_note("source_diagnostic=response_schema")
        raise error

    with pytest.raises(ValueError) as error:
        deliver(tmp_path, source, fetch=fail)
    assert str(error.value) == "monthly_source_schema_mismatch"
    assert error.value.__notes__ == ["source_diagnostic=response_schema"]
    assert len(calls) == 1


def test_cancel_after_successful_page_resumes_without_refetch(tmp_path):
    state = {"cancel": False}
    calls = []

    def progress(p):
        if p["stage"] == "captured":
            state["cancel"] = True

    def fetch(worker, params, *args):
        calls.append(params["offset"])
        return (
            frame_for(SOURCES[0])
            if params["offset"] == 0
            else frame_for(SOURCES[0], codes=())
        )

    policy = replace(StockMonthlyPolicy(), page_limit=2)
    with pytest.raises(ValueError, match="monthly_cancelled"):
        deliver(
            tmp_path,
            SOURCES[0],
            policy=policy,
            fetch=fetch,
            cancel=lambda: state["cancel"],
            progress=progress,
        )
    state["cancel"] = False
    result = deliver(tmp_path, SOURCES[0], policy=policy, fetch=fetch)
    assert calls == [0, 2] and result["rows"] == 2


def test_observation_failure_preserves_file_and_recovers(tmp_path, monkeypatch):
    from orchestrator.defs import stock_monthly_point as module

    real = module._write

    def fail(path, payload):
        if path.name == "promoted.json":
            raise OSError("fixture observation failed")
        return real(path, payload)

    monkeypatch.setattr(module, "_write", fail)
    with pytest.raises(OSError, match="observation"):
        deliver(tmp_path, SOURCES[0])
    assert raw_stock_monthly_path(tmp_path / "lake", SOURCES[0], "2020-02").exists()
    monkeypatch.setattr(module, "_write", real)
    result = deliver(
        tmp_path, SOURCES[0], fetch=lambda *args: pytest.fail("refetch after promotion")
    )
    assert result["rows"] == 2


def test_different_existing_values_require_revision(tmp_path):
    result = deliver(tmp_path, SOURCES[0])
    original = Path(result["path"]).read_bytes()
    frame = frame_for(SOURCES[0])
    frame.loc[0, "close"] = "99.0000"
    with pytest.raises(ValueError, match="revision_required"):
        deliver_month_intent(
            SOURCES[0],
            "2020-02",
            target_root=tmp_path / "lake",
            staging_root=tmp_path / "staging",
            worker=None,
            execution_id="second-run",
            upstream_bindings=lambda days: {"ids": list(days)},
            fetch=lambda *args: frame,
        )
    assert Path(result["path"]).read_bytes() == original


def test_month_more_than_twenty_days_uses_sql_aggregation(tmp_path):
    lake, _, days = setup_reference(tmp_path, "2026-09", True)
    assert len(days) == 22
    with duckdb.connect() as con:
        reference = freeze_month_references(
            con, lake, "2026-09", upstream_bindings=lambda days: {"ids": list(days)}
        )
        assert reference["daily_rows"] == 44 and reference["expected"] == {
            "000001.SZ": "20260930",
            "600000.SH": "20260930",
        }
        assert "000002.SZ" not in reference["expected"]


def identity_frame(lake):
    with duckdb.connect() as con:
        return con.execute(
            "SELECT * FROM read_parquet(?,hive_partitioning=false)",
            [str(silver_stock_identity_map_path(lake))],
        ).df()


@pytest.mark.parametrize("source", SOURCES)
def test_unreferenced_historical_identity_preserved_without_blocking(tmp_path, source):
    lake, _, _ = setup_reference(tmp_path)
    path = silver_stock_identity_map_path(lake)
    frame = pd.concat(
        [
            identity_frame(lake),
            pd.DataFrame(
                {
                    "source_ts_code": ["T600018.SH", "600018.SH"],
                    "latest_ts_code": ["T600018.SH", "600018.SH"],
                    "confidence": ["confirmed", "confirmed"],
                }
            ),
        ],
        ignore_index=True,
    )
    parquet(path, frame)
    original = path.read_bytes()
    with duckdb.connect() as con:
        reference = freeze_month_references(
            con, lake, "2020-02", upstream_bindings=lambda days: {"ids": list(days)}
        )
    assert reference["canonical"]["T600018.SH"] == "T600018.SH"
    assert reference["canonical"]["600018.SH"] == "600018.SH"
    assert reference["expected"] == {
        "000001.SZ": "20200228",
        "600000.SH": "20200228",
    }
    result = deliver(tmp_path, source)
    assert result["rows"] == 2 and path.read_bytes() == original
    with duckdb.connect() as con:
        assert con.execute(
            "SELECT ts_code FROM read_parquet(?,hive_partitioning=false) ORDER BY 1",
            [result["path"]],
        ).fetchall() == [("000001.SZ",), ("600000.SH",)]


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_ts_code", None),
        ("latest_ts_code", None),
        ("source_ts_code", " "),
        ("latest_ts_code", " "),
        ("source_ts_code", "000001.SZ"),
    ],
)
def test_unreferenced_identity_structural_errors_still_block(tmp_path, field, value):
    lake, _, _ = setup_reference(tmp_path)
    frame = identity_frame(lake)
    frame.loc[2, field] = value
    parquet(silver_stock_identity_map_path(lake), frame)
    with pytest.raises(ValueError, match="monthly_identity_invalid_or_over_budget"):
        deliver(
            tmp_path,
            SOURCES[0],
            fetch=lambda *args: pytest.fail("source requested after identity failure"),
        )
    assert not raw_stock_monthly_path(lake, SOURCES[0], "2020-02").exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("latest_ts_code", "T600018.SH"),
        ("latest_ts_code", "bad-code"),
        ("confidence", "inferred"),
        ("confidence", None),
        ("source_ts_code", "999999.SZ"),
    ],
)
def test_daily_referenced_identity_errors_block_before_source(tmp_path, field, value):
    lake, _, _ = setup_reference(tmp_path)
    frame = identity_frame(lake)
    frame.loc[0, field] = value
    parquet(silver_stock_identity_map_path(lake), frame)
    with pytest.raises(ValueError, match="monthly_identity_unresolved"):
        deliver(
            tmp_path,
            SOURCES[0],
            fetch=lambda *args: pytest.fail("source requested after identity failure"),
        )


def test_daily_referenced_historical_code_still_rejected(tmp_path):
    lake, _, days = setup_reference(tmp_path)
    frame = identity_frame(lake)
    frame.loc[0, ["source_ts_code", "latest_ts_code"]] = "T600018.SH"
    parquet(silver_stock_identity_map_path(lake), frame)
    parquet(
        raw_stock_daily_path(lake, days[0].isoformat()),
        pd.DataFrame({"ts_code": ["T600018.SH"], "trade_date": ["20200228"]}),
    )
    with pytest.raises(ValueError, match="monthly_identity_unresolved"):
        deliver(
            tmp_path,
            SOURCES[0],
            fetch=lambda *args: pytest.fail("source requested for invalid daily code"),
        )


@pytest.mark.parametrize(
    "field,value",
    [("latest_ts_code", "T600018.SH"), ("confidence", "inferred")],
)
def test_extra_source_identity_is_validated_even_without_daily(tmp_path, field, value):
    lake, _, _ = setup_reference(tmp_path)
    frame = identity_frame(lake)
    frame.loc[2, field] = value  # 000002.SZ has no daily rows, but is returned below.
    parquet(silver_stock_identity_map_path(lake), frame)
    with pytest.raises(ValueError, match="monthly_identity_or_source_cutoff_invalid"):
        deliver(
            tmp_path,
            SOURCES[0],
            fetch=lambda *args: frame_for(
                SOURCES[0], codes=("000001.SZ", "000002.SZ", "600000.SH")
            ),
        )
    assert not raw_stock_monthly_path(lake, SOURCES[0], "2020-02").exists()


def test_identity_budget_applies_to_full_snapshot(tmp_path, monkeypatch):
    from orchestrator.defs.source_readiness import stock_monthly as module

    lake, _, _ = setup_reference(tmp_path)
    monkeypatch.setattr(
        module,
        "StockMonthlyPolicy",
        lambda: replace(StockMonthlyPolicy(), max_codes=2, prod_code_batch=2),
    )
    with (
        duckdb.connect() as con,
        pytest.raises(ValueError, match="monthly_identity_invalid_or_over_budget"),
    ):
        freeze_month_references(
            con, lake, "2020-02", upstream_bindings=lambda days: {"ids": list(days)}
        )


def test_unreferenced_identity_changes_invalidate_full_snapshot_hash(tmp_path):
    lake, _, _ = setup_reference(tmp_path)
    with duckdb.connect() as con:
        reference = freeze_month_references(
            con, lake, "2020-02", upstream_bindings=lambda days: {"ids": list(days)}
        )
    frame = identity_frame(lake)
    frame.loc[2, "confidence"] = "inferred"
    parquet(silver_stock_identity_map_path(lake), frame)
    with pytest.raises(ValueError, match="monthly_reference_changed"):
        assert_month_references_unchanged(reference["references"])


def test_upstream_blocking_gate_remains_required(tmp_path):
    lake, _, _ = setup_reference(tmp_path)
    with (
        duckdb.connect() as con,
        pytest.raises(ValueError, match="monthly_upstream_not_ready"),
    ):
        freeze_month_references(
            con, lake, "2020-02", upstream_bindings=lambda days: None
        )


@pytest.mark.parametrize(
    "mutation", ["missing_file", "duplicate", "placement", "identity", "calendar"]
)
def test_reference_gate_fails_before_source(tmp_path, mutation):
    lake, _, days = setup_reference(tmp_path)
    path = raw_stock_daily_path(lake, days[0].isoformat())
    if mutation == "missing_file":
        path.unlink()
    if mutation == "duplicate":
        parquet(
            path,
            pd.DataFrame(
                {"ts_code": ["000001.SZ"] * 2, "trade_date": ["20200228"] * 2}
            ),
        )
    if mutation == "placement":
        parquet(
            path, pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20200227"]})
        )
    if mutation == "identity":
        parquet(
            silver_stock_identity_map_path(lake),
            pd.DataFrame(
                {
                    "source_ts_code": ["000001.SZ"],
                    "latest_ts_code": ["000001.SZ"],
                    "confidence": ["pending"],
                }
            ),
        )
    if mutation == "calendar":
        parquet(
            raw_trade_calendar_path(lake),
            pd.DataFrame(
                {"exchange": ["SSE"], "cal_date": ["20200228"], "is_open": [1]}
            ),
        )
    with pytest.raises((ValueError, OSError, duckdb.Error)):
        deliver(
            tmp_path,
            SOURCES[0],
            fetch=lambda *args: pytest.fail(
                "source requested despite reference failure"
            ),
        )


@pytest.mark.parametrize(
    "time,opened",
    [
        ("2026-10-05T19:29:59+08:00", False),
        ("2026-10-05T19:30:00+08:00", True),
        ("2026-10-05T11:30:00+00:00", True),
    ],
)
def test_time_window(time, opened):
    assert monthly_window_open(datetime.fromisoformat(time)) is opened
    assert completed_month(datetime.fromisoformat(time), "2026-09")
    assert not completed_month(datetime.fromisoformat(time), "2026-10")
    assert next_month("2026-12") == "2027-01"


def test_current_month_auto_intent_rejected():
    with pytest.raises(ValueError, match="monthly_period_not_completed"):
        monthly_update_intent(SOURCES[0], "2026-10", "2026-10-05")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"call_timeout_seconds": 21},
        {"max_reference_rows": 320001},
        {"max_daily_files": 32},
        {"timezone": "UTC"},
        {"daily_start_time": "20:00"},
        {"tick_min_seconds": 0},
    ],
)
def test_update_configuration_caps(kwargs):
    with pytest.raises(ValueError):
        MonthlyUpdatePolicy(**kwargs)


def test_real_process_exit_preserves_captured_page(tmp_path):
    import subprocess
    import sys

    setup_reference(tmp_path)
    script = """
import os,sys
from pathlib import Path
from tests.test_stock_monthly_update import deliver,SOURCES

def progress(payload):
    if payload['stage']=='captured':os._exit(17)
deliver(Path(sys.argv[1]),SOURCES[0],progress=progress)
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 17, result.stderr
    assert next((tmp_path / "staging").rglob("receipt.json")).exists()
    recovered = deliver(
        tmp_path,
        SOURCES[0],
        fetch=lambda *args: pytest.fail("refetch captured page after actual exit"),
    )
    assert recovered["rows"] == 2 and recovered["requests"] == 1


class ExitWorker:
    def __call__(self, *args):
        os._exit(19)


def test_actual_supervised_transport_process_exit():
    with pytest.raises(WeeklyCaptureError, match="source_failed"):
        fetch_weekly_request_supervised(
            ExitWorker(),
            {"freq": "month"},
            ("ts_code",),
            2,
            SimpleNamespace(call_timeout_seconds=2),
            lambda: False,
        )


@pytest.mark.parametrize("tamper", ["csv", "receipt", "proof", "reference", "formal"])
def test_delivery_tampering_fails_local_check(tmp_path, tamper):
    result = deliver(tmp_path, SOURCES[0])
    directory = Path(result["proof_path"]).parent
    path = {
        "csv": directory / "page-0/source.csv",
        "receipt": directory / "page-0/receipt.json",
        "proof": Path(result["proof_path"]),
        "reference": directory / "reference.json",
        "formal": Path(result["path"]),
    }[tamper]
    path.write_bytes(path.read_bytes() + b"changed")
    with duckdb.connect() as con, pytest.raises((ValueError, OSError, duckdb.Error)):
        read_month_delivery(
            result, tmp_path / "lake", SOURCES[0], "2020-02", connection=con
        )


def test_cross_page_duplicate_never_promotes(tmp_path):
    policy = replace(StockMonthlyPolicy(), page_limit=2)

    def fetch(worker, params, *args):
        return (
            frame_for(SOURCES[0])
            if params["offset"] == 0
            else frame_for(SOURCES[0], codes=("000001.SZ",))
        )

    with pytest.raises(ValueError, match="monthly_duplicate_key"):
        deliver(tmp_path, SOURCES[0], policy=policy, fetch=fetch)


def test_original_raw_identity_is_preserved(tmp_path):
    lake, _, _ = setup_reference(tmp_path)
    parquet(
        silver_stock_identity_map_path(lake),
        pd.DataFrame(
            {
                "source_ts_code": ["000001.SZ", "600000.SH", "000002.SZ", "920001.BJ"],
                "latest_ts_code": ["920001.BJ", "600000.SH", "000002.SZ", "920001.BJ"],
                "confidence": ["confirmed"] * 4,
            }
        ),
    )
    result = deliver(tmp_path, SOURCES[0])
    with duckdb.connect() as con:
        assert con.execute(
            "SELECT ts_code FROM read_parquet(?,hive_partitioning=false) ORDER BY 1",
            [result["path"]],
        ).fetchall() == [("000001.SZ",), ("600000.SH",)]


def test_references_changed_after_capture_prevent_promotion(tmp_path):
    lake, _, days = setup_reference(tmp_path)

    def fetch(*args):
        parquet(
            raw_stock_daily_path(lake, days[0].isoformat()),
            pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20200228"]}),
        )
        return frame_for(SOURCES[0])

    with pytest.raises(ValueError, match="monthly_reference_changed"):
        deliver(tmp_path, SOURCES[0], fetch=fetch)
    assert not raw_stock_monthly_path(lake, SOURCES[0], "2020-02").exists()


def test_same_values_new_intent_reuses_formal_bytes(tmp_path):
    result = deliver(tmp_path, SOURCES[0])
    before = Path(result["path"]).read_bytes()
    replay = deliver_month_intent(
        SOURCES[0],
        "2020-02",
        target_root=tmp_path / "lake",
        staging_root=tmp_path / "staging",
        worker=None,
        execution_id="new-identical",
        upstream_bindings=lambda days: {"ids": list(days)},
        fetch=lambda *args: frame_for(SOURCES[0]),
    )
    assert replay["rows"] == 2 and Path(result["path"]).read_bytes() == before


def test_global_monthly_writer_lock_prevents_concurrent_sources(tmp_path):
    from orchestrator.defs.bootstrap.stock_monthly_files import monthly_file_lock

    _, staging, _ = setup_reference(tmp_path)
    locks = staging / "stock_monthly_raw/updates"
    locks.mkdir(parents=True)
    with (
        monthly_file_lock(locks / "writer.lock"),
        pytest.raises(ValueError, match="monthly_writer_busy"),
    ):
        deliver(
            tmp_path,
            SOURCES[1],
            fetch=lambda *args: pytest.fail("parallel source call"),
        )
