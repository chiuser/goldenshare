from __future__ import annotations

from pathlib import Path

import duckdb

from orchestrator.defs.bootstrap import (
    index_daily_000680_history_supplement_apply as apply,
)
from orchestrator.defs.bootstrap import (
    index_daily_000680_history_supplement_audit as audit,
)
from orchestrator.defs.duckdb_sql import INDEX_DAILY_RAW_COLUMNS


def _row(ts_code: str) -> tuple[object, ...]:
    values = {
        "ts_code": ts_code,
        "trade_date": "20200102",
        "open": 10.0,
        "high": 11.0,
        "low": 9.0,
        "close": 10.5,
        "pre_close": 10.0,
        "change": 0.5,
        "pct_chg": 5.0,
        "vol": 100.0,
        "amount": 1_000.0,
    }
    return tuple(values[column] for column in INDEX_DAILY_RAW_COLUMNS)


def _write_raw(path: Path, rows: tuple[tuple[object, ...], ...]) -> None:
    with duckdb.connect(":memory:") as connection:
        apply._write_source_staging(
            connection=connection,
            rows=rows,
            target_path=path,
        )


def test_physical_layer_audit_requires_one_target_row_per_file(tmp_path: Path) -> None:
    path = tmp_path / "raw" / "trade_date=2020-01-02" / "part-000.parquet"
    _write_raw(path, (_row("000001.SH"), _row(apply.TARGET_CODE)))

    with duckdb.connect(":memory:") as connection:
        result, rows = audit.audit_layer(connection, layer="raw", paths=(path,))

    assert result.passed is True
    assert result.target_row_count == 1
    assert result.target_missing_file_count == 0
    assert len(rows) == 1


def test_physical_layer_audit_fails_when_target_is_missing(tmp_path: Path) -> None:
    path = tmp_path / "raw" / "trade_date=2020-01-02" / "part-000.parquet"
    _write_raw(path, (_row("000001.SH"),))

    with duckdb.connect(":memory:") as connection:
        result, _ = audit.audit_layer(connection, layer="raw", paths=(path,))

    assert result.passed is False
    assert result.target_row_count == 0
    assert result.target_missing_file_count == 1


def test_physical_layer_audit_rejects_duplicate_target_keys(tmp_path: Path) -> None:
    path = tmp_path / "raw" / "trade_date=2020-01-02" / "part-000.parquet"
    _write_raw(path, (_row(apply.TARGET_CODE), _row(apply.TARGET_CODE)))

    with duckdb.connect(":memory:") as connection:
        result, _ = audit.audit_layer(connection, layer="raw", paths=(path,))

    assert result.passed is False
    assert result.target_duplicate_key_count == 1
