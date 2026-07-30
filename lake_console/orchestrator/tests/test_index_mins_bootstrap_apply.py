from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import tempfile

import duckdb
import pytest

from orchestrator.defs.bootstrap.index_mins_bootstrap_apply import (
    INDEX_MINS_APPROVED_SOURCE_EMPTY_FALLBACK_SCOPE,
    IndexMinsBootstrapApplyError,
    load_historical_index_mins_code_scopes,
    run_bootstrap_apply,
)
from orchestrator.defs.bootstrap.index_mins_bootstrap_apply_cli import main
from orchestrator.defs.bootstrap.index_mins_bootstrap_plan import build_date_plan
from orchestrator.defs.paths import (
    raw_index_mins_path,
    silver_index_basic_path,
    silver_index_mins_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.prod_db.index_mins import IndexMinsActivePool
from orchestrator.defs.run_contracts.index_mins import index_mins_code_set_hash


class _MemoryDuckDB:
    @contextmanager
    def connect(self):
        connection = duckdb.connect(":memory:")
        try:
            yield connection
        finally:
            connection.close()


class _FakeProd:
    pass


def _write_calendar(root: Path) -> tuple[str, ...]:
    dates = tuple(INDEX_MINS_APPROVED_SOURCE_EMPTY_FALLBACK_SCOPE)
    path = silver_trade_calendar_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(":memory:")
    try:
        values = ", ".join(f"(DATE '{value}', 'SSE', true)" for value in dates)
        connection.execute(
            "COPY (SELECT * FROM (VALUES "
            f"{values}) AS t(trade_date, exchange, is_open)) TO ? (FORMAT PARQUET)",
            [str(path)],
        )
    finally:
        connection.close()
    return dates


def _build_reports(root: Path, output_dir: Path) -> tuple[Path, Path]:
    connection = duckdb.connect(":memory:")
    try:
        plan = build_date_plan(
            connection=connection,
            lake_root=root,
            end_date="2025-08-01",
        )
    finally:
        connection.close()
    source_readiness = []
    for trade_date, target_frequencies in INDEX_MINS_APPROVED_SOURCE_EMPTY_FALLBACK_SCOPE.items():
        empty = set(target_frequencies)
        source_readiness.append(
                    {
                        "trade_date": trade_date,
                        "reason_code": (
                            "prod_index_mins_source_empty"
                            if target_frequencies
                            else "prod_index_mins_source_ready"
                        ),
                        "frequency_coverages": [
                    {
                        "source_freq": f"{frequency}min",
                        "source_row_count": 0 if frequency in empty else 10,
                    }
                    for frequency in (1, 5, 15, 30, 60)
                ],
            }
        )
    source_report = {
        "schema_version": 1,
        "lake_root": str(root.resolve()),
        "should_stop": True,
        "stop_reason_codes": ["source_coverage_not_ready"],
        "date_plan": plan.to_dict(),
        "source_probe": {
            "ready": False,
            "probe_mode": "coverage_only",
            "failed_date_count": 5,
        },
        "source_readiness": source_readiness,
        "target_audits": [
            {"layer": "raw", "invalid_existing_count": 0},
            {"layer": "silver", "invalid_existing_count": 0},
        ],
        "disk_budget": {
            "passed": True,
            "estimated_required_bytes": 1,
        },
    }
    fallback_report = {
        "schema_version": 1,
        "status": "completed",
        "dates": list(INDEX_MINS_APPROVED_SOURCE_EMPTY_FALLBACK_SCOPE),
        "target_frequencies": {
            date: list(frequencies)
            for date, frequencies in INDEX_MINS_APPROVED_SOURCE_EMPTY_FALLBACK_SCOPE.items()
        },
        "full_dry_run_reexecuted": False,
        "full_bootstrap_started": False,
        "dagster_event_write": False,
    }
    source_path = output_dir / "source.json"
    fallback_path = output_dir / "fallback.json"
    source_path.write_text(json.dumps(source_report), encoding="utf-8")
    fallback_path.write_text(json.dumps(fallback_report), encoding="utf-8")
    return source_path, fallback_path


def _scope_loader(*, connection, lake_root, trade_dates):
    del connection, lake_root
    return {
        trade_date: IndexMinsActivePool(
            codes=("000001.SH",),
            code_set_hash=index_mins_code_set_hash(("000001.SH",)),
        )
        for trade_date in trade_dates
    }


def _write_raw_file(*, lake_root, source_freq, partition_key, active_pool, **_kwargs):
    path = raw_index_mins_path(lake_root, source_freq, partition_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(
            """
            CREATE TEMP TABLE sample_raw AS SELECT
              ?::VARCHAR AS ts_code,
              ?::VARCHAR AS freq,
              CAST(? || ' 09:30:00' AS TIMESTAMP) AS trade_time,
              1.0::DOUBLE AS open, 1.1::DOUBLE AS close,
              1.2::DOUBLE AS high, 0.9::DOUBLE AS low,
              10.0::DOUBLE AS vol, 20.0::DOUBLE AS amount,
              'SSE'::VARCHAR AS exchange, 1.05::DOUBLE AS vwap
            """,
            [active_pool.codes[0], source_freq, partition_key],
        )
        connection.execute("COPY sample_raw TO ? (FORMAT PARQUET)", [str(path)])
    finally:
        connection.close()
    return {
        "write_mode": "fake_staged_atomic_replace",
        "source_freq": source_freq,
        "partition_key": partition_key,
        "written_row_count": 1,
    }


def _write_silver_file(*, lake_root, freq, partition_key, **_kwargs):
    path = silver_index_mins_path(lake_root, freq, partition_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized_freq = f"{freq}min" if isinstance(freq, int) else str(freq)
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(
            """
            CREATE TEMP TABLE sample_silver AS SELECT
              '000001.SH'::VARCHAR AS ts_code,
              ?::VARCHAR AS freq,
              CAST(? || ' 09:30:00' AS TIMESTAMP) AS trade_time,
              1.0::DOUBLE AS open, 1.1::DOUBLE AS close,
              1.2::DOUBLE AS high, 0.9::DOUBLE AS low,
              10.0::DOUBLE AS vol, 20.0::DOUBLE AS amount,
              'SSE'::VARCHAR AS exchange, NULL::DOUBLE AS vwap
            """,
            [normalized_freq, partition_key],
        )
        connection.execute("COPY sample_silver TO ? (FORMAT PARQUET)", [str(path)])
    finally:
        connection.close()
    return {
        "write_mode": "fake_staged_atomic_replace",
        "silver_freq": str(freq),
        "partition_key": partition_key,
        "written_row_count": 1,
    }


def test_apply_runs_raw_then_silver_with_bounded_batches(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    lake.mkdir()
    reports = tmp_path / "reports"
    reports.mkdir()
    _write_calendar(lake)
    source_report, fallback_report = _build_reports(lake, reports)

    report = run_bootstrap_apply(
        lake_root=lake,
        duckdb_resource=_MemoryDuckDB(),
        prod_postgres=_FakeProd(),
        source_report_path=source_report,
        fallback_report_path=fallback_report,
        output_dir=reports,
        end_date="2025-08-01",
        batch_size=2,
        apply_id="test",
        raw_writer=_write_raw_file,
        silver_writer=_write_silver_file,
        source_scope_loader=_scope_loader,
    )

    assert report["should_stop"] is False
    assert report["dagster_event_write"] is False
    assert len(report["raw_records"]) == 25
    assert len(report["silver_records"]) == 35
    assert report["raw_audit"]["missing_count"] == 0
    assert report["silver_audit"]["missing_count"] == 0
    assert len(list((lake / "raw/tushare/index_mins").rglob("part-000.parquet"))) == 25
    assert len(list((lake / "silver/quote/index_mins").rglob("part-000.parquet"))) == 35


def test_apply_rejects_source_fingerprint_before_writing(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    lake.mkdir()
    reports = tmp_path / "reports"
    reports.mkdir()
    _write_calendar(lake)
    source_report, fallback_report = _build_reports(lake, reports)
    payload = json.loads(source_report.read_text(encoding="utf-8"))
    payload["date_plan"]["fingerprint"] = "wrong"
    source_report.write_text(json.dumps(payload), encoding="utf-8")
    calls: list[str] = []

    def raw_writer(**kwargs):
        calls.append(kwargs["partition_key"])
        raise AssertionError("writer must not run after preflight rejection")

    with pytest.raises(IndexMinsBootstrapApplyError, match="fingerprint"):
        run_bootstrap_apply(
            lake_root=lake,
            duckdb_resource=_MemoryDuckDB(),
            prod_postgres=_FakeProd(),
            source_report_path=source_report,
            fallback_report_path=fallback_report,
            output_dir=reports,
            end_date="2025-08-01",
            raw_writer=raw_writer,
            source_scope_loader=_scope_loader,
        )
    assert calls == []
    assert not (lake / "raw").exists()


def test_apply_rejects_invalid_existing_target_before_writing(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    lake.mkdir()
    reports = tmp_path / "reports"
    reports.mkdir()
    dates = _write_calendar(lake)
    source_report, fallback_report = _build_reports(lake, reports)
    invalid = raw_index_mins_path(lake, "1min", dates[0])
    invalid.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("COPY (SELECT 1 AS wrong_column) TO ? (FORMAT PARQUET)", [str(invalid)])
    finally:
        connection.close()

    with pytest.raises(IndexMinsBootstrapApplyError, match="invalid existing"):
        run_bootstrap_apply(
            lake_root=lake,
            duckdb_resource=_MemoryDuckDB(),
            prod_postgres=_FakeProd(),
            source_report_path=source_report,
            fallback_report_path=fallback_report,
            output_dir=reports,
            end_date="2025-08-01",
            raw_writer=_write_raw_file,
            source_scope_loader=_scope_loader,
        )
    assert invalid.exists()


def test_historical_scope_uses_list_and_exp_dates(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    lake.mkdir()
    path = silver_index_basic_path(lake)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(
            """
            COPY (SELECT * FROM (VALUES
              ('000001.SH', DATE '2025-01-01', NULL::DATE),
              ('000002.SH', DATE '2025-07-21', NULL::DATE),
              ('000003.SH', DATE '2025-01-01', DATE '2025-07-25')
            ) AS t(ts_code, list_date, exp_date)) TO ? (FORMAT PARQUET)
            """,
            [str(path)],
        )
        scopes = load_historical_index_mins_code_scopes(
            connection=connection,
            lake_root=lake,
            trade_dates=("2025-07-24", "2025-07-25"),
        )
    finally:
        connection.close()

    assert scopes["2025-07-24"].codes == (
        "000001.SH",
        "000002.SH",
        "000003.SH",
    )
    assert scopes["2025-07-25"].codes == ("000001.SH", "000002.SH")


def test_cli_requires_explicit_lake_write_confirmation() -> None:
    assert main(
        [
            "--source-report",
            "/private/tmp/source.json",
            "--fallback-report",
            "/private/tmp/fallback.json",
            "--end-date",
            "2025-08-01",
        ]
    ) == 2


def test_apply_rejects_batch_over_20_before_writing(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    lake.mkdir()
    with pytest.raises(ValueError, match="between 1 and 20"):
        run_bootstrap_apply(
            lake_root=lake,
            duckdb_resource=_MemoryDuckDB(),
            prod_postgres=_FakeProd(),
            source_report_path=tmp_path / "missing-source.json",
            fallback_report_path=tmp_path / "missing-fallback.json",
            output_dir=tmp_path,
            end_date="2025-08-01",
            batch_size=21,
        )


def test_apply_modules_do_not_access_dagster_events() -> None:
    source = (
        Path(__file__).parents[1]
        / "src/orchestrator/defs/bootstrap/index_mins_bootstrap_apply.py"
    )
    text = source.read_text(encoding="utf-8")
    assert "get_event_records" not in text
    assert "report_runless_asset_event" not in text
    assert "import dagster" not in text.lower()
