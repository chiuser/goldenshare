from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import duckdb
import pytest

from orchestrator.defs.bootstrap.major_index_mins_bootstrap_apply import (
    MajorIndexMinsBootstrapApplyError,
    audit_temporary_lake,
    build_temporary_lake_from_staging,
    promote_temporary_lake,
)
from orchestrator.defs.bootstrap.major_index_mins_bootstrap_plan import (
    MajorIndexMinsSourcePlan,
    build_date_plan,
    build_source_plan,
)
from orchestrator.defs.bootstrap.major_index_mins_bootstrap_stage import (
    audit_source_staging,
    source_window_parquet_path,
    source_window_sidecar_path,
    stage_source_windows,
)
from orchestrator.defs.bootstrap.major_index_mins_bootstrap_stage_cli import (
    main as stage_main,
)
from orchestrator.defs.paths import (
    raw_major_index_mins_path,
    silver_major_index_mins_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.resources import TushareResult
from orchestrator.defs.run_contracts.major_index_mins import (
    major_index_mins_exchange_for_code,
    major_index_mins_session_times,
)
from orchestrator.defs.tushare_request_policy import TushareRequestPolicy


class _MemoryDuckDB:
    @contextmanager
    def connect(self):
        connection = duckdb.connect(":memory:")
        try:
            yield connection
        finally:
            connection.close()


def _calendar(root: Path, dates: tuple[str, ...]) -> None:
    path = silver_trade_calendar_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    values = ", ".join(f"(DATE '{value}', 'SSE', true)" for value in dates)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            f"COPY (SELECT * FROM (VALUES {values}) AS t(trade_date, exchange, is_open)) TO ? (FORMAT PARQUET)",
            [str(path)],
        )


class _FakeTushare:
    def __init__(
        self,
        dates: tuple[str, ...],
        *,
        opening_sentinel: bool = False,
        missing_exchange: bool = False,
    ) -> None:
        self.dates = dates
        self.opening_sentinel = opening_sentinel
        self.missing_exchange = missing_exchange
        self.calls: list[dict[str, object]] = []

    def call(self, api_name, params, fields):
        assert api_name == "idx_mins"
        self.calls.append(dict(params))
        if int(params["offset"]):
            return TushareResult(rows=[], columns=tuple(fields), metadata={})
        code = str(params["ts_code"])
        frequency = str(params["freq"])
        exchange = major_index_mins_exchange_for_code(code)
        start_date = str(params["start_date"])[:10]
        end_date = str(params["end_date"])[:10]
        rows: list[dict[str, object]] = []
        for trade_date in self.dates:
            if not start_date <= trade_date <= end_date:
                continue
            for index, source_time in enumerate(
                major_index_mins_session_times(
                    exchange=exchange,
                    source_freq=frequency,
                )
            ):
                value = float(index + 100)
                sentinel = self.opening_sentinel and source_time == "09:30:00"
                rows.append(
                    {
                        "ts_code": code,
                        "freq": frequency,
                        "trade_time": f"{trade_date} {source_time}",
                        "open": value,
                        "close": value if sentinel else value + 0.1,
                        "high": 0.0 if sentinel else value + 0.2,
                        "low": 0.0 if sentinel else value - 0.1,
                        "vol": 10.0,
                        "amount": 20.0,
                        "exchange": None if self.missing_exchange else exchange,
                        "vwap": value,
                    }
                )
        return TushareResult(rows=rows, columns=tuple(fields), metadata={})


def _plans(root: Path, dates: tuple[str, ...]):
    _calendar(root, dates)
    with duckdb.connect(":memory:") as connection:
        date_plan = build_date_plan(connection=connection, lake_root=root)
    return date_plan, build_source_plan(date_plan)


def _policy() -> TushareRequestPolicy:
    return TushareRequestPolicy(
        minimum_interval_seconds=0,
        max_retries=0,
        max_requests=2,
        max_elapsed_seconds=30,
    )


def test_source_staging_is_atomic_resumable_and_request_free_to_audit(
    tmp_path: Path,
) -> None:
    calendar_root = tmp_path / "calendar"
    staging_root = tmp_path / "staging"
    dates = ("2025-01-02", "2025-01-03")
    date_plan, full_source_plan = _plans(calendar_root, dates)
    window = full_source_plan.windows[0]
    source_plan = MajorIndexMinsSourcePlan(
        windows=(window,),
        fingerprint="f" * 64,
        expected_row_count=window.expected_row_count,
        request_count_by_frequency={window.source_freq: 1},
    )
    tushare = _FakeTushare(dates)
    output = tmp_path / "stage.json"
    first = stage_source_windows(
        staging_root=staging_root,
        date_plan=date_plan,
        source_plan=source_plan,
        tushare=tushare,
        duckdb_resource=_MemoryDuckDB(),
        output_path=output,
        request_policy_factory=_policy,
        sleep_fn=lambda _: None,
    )
    assert first.should_stop is False
    assert first.written_window_count == 1
    assert source_window_parquet_path(staging_root, date_plan, window).is_file()
    assert source_window_sidecar_path(staging_root, date_plan, window).is_file()

    call_count = len(tushare.calls)
    second = stage_source_windows(
        staging_root=staging_root,
        date_plan=date_plan,
        source_plan=source_plan,
        tushare=tushare,
        duckdb_resource=_MemoryDuckDB(),
        output_path=output,
        request_policy_factory=_policy,
        sleep_fn=lambda _: None,
    )
    assert second.skipped_window_count == 1
    assert len(tushare.calls) == call_count

    audit = audit_source_staging(
        staging_root=staging_root,
        date_plan=date_plan,
        source_plan=source_plan,
        duckdb_resource=_MemoryDuckDB(),
    )
    assert audit.ready is True
    assert audit.source_row_count == source_plan.expected_row_count


def test_opening_sentinel_is_retained_and_blocks_temporary_lake(
    tmp_path: Path,
) -> None:
    calendar_root = tmp_path / "calendar"
    staging_root = tmp_path / "staging"
    dates = ("2025-01-02",)
    date_plan, full_source_plan = _plans(calendar_root, dates)
    window = full_source_plan.windows[0]
    source_plan = replace(
        full_source_plan,
        windows=(window,),
        expected_row_count=window.expected_row_count,
        request_count_by_frequency={window.source_freq: 1},
    )
    stage_source_windows(
        staging_root=staging_root,
        date_plan=date_plan,
        source_plan=source_plan,
        tushare=_FakeTushare(dates, opening_sentinel=True),
        duckdb_resource=_MemoryDuckDB(),
        output_path=tmp_path / "stage.json",
        request_policy_factory=_policy,
        sleep_fn=lambda _: None,
    )
    audit = audit_source_staging(
        staging_root=staging_root,
        date_plan=date_plan,
        source_plan=source_plan,
        duckdb_resource=_MemoryDuckDB(),
    )
    assert audit.ready is False
    assert audit.opening_ohlc_sentinel_count == 1
    assert "source_ohlc_policy_required" in audit.stop_reason_codes
    assert source_window_parquet_path(staging_root, date_plan, window).is_file()
    with pytest.raises(MajorIndexMinsBootstrapApplyError):
        build_temporary_lake_from_staging(
            staging_root=staging_root,
            date_plan=date_plan,
            source_plan=source_plan,
            duckdb_resource=_MemoryDuckDB(),
            output_path=tmp_path / "build.json",
        )


def test_source_staging_audit_counts_null_exchange_as_invalid_identity(
    tmp_path: Path,
) -> None:
    calendar_root = tmp_path / "calendar"
    staging_root = tmp_path / "staging"
    dates = ("2025-01-02",)
    date_plan, full_source_plan = _plans(calendar_root, dates)
    window = full_source_plan.windows[0]
    source_plan = replace(
        full_source_plan,
        windows=(window,),
        expected_row_count=window.expected_row_count,
        request_count_by_frequency={window.source_freq: 1},
    )
    stage_source_windows(
        staging_root=staging_root,
        date_plan=date_plan,
        source_plan=source_plan,
        tushare=_FakeTushare(dates, missing_exchange=True),
        duckdb_resource=_MemoryDuckDB(),
        output_path=tmp_path / "stage.json",
        request_policy_factory=_policy,
        sleep_fn=lambda _: None,
    )

    audit = audit_source_staging(
        staging_root=staging_root,
        date_plan=date_plan,
        source_plan=source_plan,
        duckdb_resource=_MemoryDuckDB(),
    )

    assert audit.ready is False
    assert audit.identity_invalid_count == window.expected_row_count
    assert "source_identity_invalid" in audit.stop_reason_codes


def test_full_clean_fixture_builds_audits_and_promotes_without_new_requests(
    tmp_path: Path,
) -> None:
    calendar_root = tmp_path / "calendar"
    staging_root = tmp_path / "staging"
    formal_root = tmp_path / "formal"
    dates = ("2025-01-02",)
    date_plan, source_plan = _plans(calendar_root, dates)
    tushare = _FakeTushare(dates)
    stage_source_windows(
        staging_root=staging_root,
        date_plan=date_plan,
        source_plan=source_plan,
        tushare=tushare,
        duckdb_resource=_MemoryDuckDB(),
        output_path=tmp_path / "stage.json",
        request_policy_factory=_policy,
        sleep_fn=lambda _: None,
    )
    call_count = len(tushare.calls)
    build = build_temporary_lake_from_staging(
        staging_root=staging_root,
        date_plan=date_plan,
        source_plan=source_plan,
        duckdb_resource=_MemoryDuckDB(),
        output_path=tmp_path / "build.json",
    )
    assert build.should_stop is False
    assert build.raw_written_count == 5
    assert build.silver_written_count == 7
    assert len(tushare.calls) == call_count
    audits = audit_temporary_lake(
        staging_root=staging_root,
        date_plan=date_plan,
        duckdb_resource=_MemoryDuckDB(),
    )
    assert all(audit.missing_count == 0 for audit in audits)
    assert all(audit.invalid_existing_count == 0 for audit in audits)

    promote = promote_temporary_lake(
        staging_root=staging_root,
        formal_lake_root=formal_root,
        date_plan=date_plan,
        source_plan=source_plan,
        duckdb_resource=_MemoryDuckDB(),
        output_path=tmp_path / "promote.json",
    )
    assert promote.should_stop is False
    assert promote.raw_promoted_count == 5
    assert promote.silver_promoted_count == 7
    assert raw_major_index_mins_path(formal_root, "1min", dates[0]).is_file()
    assert silver_major_index_mins_path(formal_root, "120min", dates[0]).is_file()
    assert len(tushare.calls) == call_count


def test_stage_cli_requires_confirmation_before_loading_plans() -> None:
    assert stage_main(["stage-source", "--staging-root", "/tmp/unused"]) == 2
