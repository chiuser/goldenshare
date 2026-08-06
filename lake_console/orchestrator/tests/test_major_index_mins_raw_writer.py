from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

import duckdb
import pytest

from orchestrator.defs.io.major_index_mins_raw_writer import (
    MajorIndexMinsRawValidationError,
    write_major_index_mins_raw_partition,
)
from orchestrator.defs.paths import (
    raw_major_index_mins_path,
    raw_major_index_mins_staging_path,
)
from orchestrator.defs.resources import TushareResult
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_SOURCE_COLUMNS,
    effective_codes_for_date,
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


class _FakeTushare:
    def __init__(self, rows_by_code=None):
        self.rows_by_code = rows_by_code or {}
        self.calls = []

    def call(self, api_name, params, fields):
        self.calls.append((api_name, dict(params), tuple(fields)))
        rows = self.rows_by_code.get(params["ts_code"], []) if params["offset"] == 0 else []
        return TushareResult(rows=list(rows), columns=tuple(fields), metadata={})


def _policy() -> TushareRequestPolicy:
    return TushareRequestPolicy(
        minimum_interval_seconds=0.0,
        max_retries=0,
        max_requests=100,
        max_elapsed_seconds=30.0,
    )


def _exchange(code: str) -> str:
    if code.endswith(".SH"):
        return "XSHG"
    if code.endswith(".SZ"):
        return "XSHE"
    return "BSE"


def _row(
    code: str,
    *,
    trade_time: str = "2026-08-04 15:00:00",
    freq: str = "60min",
    high: float = 1.2,
) -> dict[str, object]:
    return {
        "ts_code": code,
        "freq": freq,
        "trade_time": trade_time,
        "open": 1.0,
        "close": 1.1,
        "high": high,
        "low": 0.9,
        "vol": 10.0,
        "amount": 11.0,
        "exchange": _exchange(code),
        "vwap": 1.05,
    }


def _all_rows(*, high: float = 1.2) -> dict[str, list[dict[str, object]]]:
    return {
        code: [
            _row(
                code,
                trade_time=f"2026-08-04 {source_time}",
                high=high,
            )
            for source_time in major_index_mins_session_times(
                exchange=major_index_mins_exchange_for_code(code),
                source_freq="60min",
            )
        ]
        for code in effective_codes_for_date("2026-08-04")
    }


def _daily_1min_rows() -> dict[str, list[dict[str, object]]]:
    return {
        code: [
            _row(
                code,
                trade_time=f"2026-08-04 {source_time}",
                freq="1min",
            )
            for source_time in major_index_mins_session_times(
                exchange=major_index_mins_exchange_for_code(code),
                source_freq="1min",
            )
        ]
        for code in effective_codes_for_date("2026-08-04")
    }


def test_raw_paths_are_dedicated_and_reject_unsafe_inputs(tmp_path: Path) -> None:
    assert raw_major_index_mins_path(tmp_path, "60min", "2026-08-04") == (
        tmp_path
        / "raw/tushare/major_index_mins/freq=60min/trade_date=2026-08-04/part-000.parquet"
    )
    with pytest.raises(ValueError):
        raw_major_index_mins_path(tmp_path, "90min", "2026-08-04")
    with pytest.raises(ValueError):
        raw_major_index_mins_path(tmp_path, "60min", "20260804")
    with pytest.raises(ValueError):
        raw_major_index_mins_staging_path(
            tmp_path,
            "bad/run",
            "60min",
            "2026-08-04",
        )


def test_writer_stages_validates_and_atomically_promotes(tmp_path: Path) -> None:
    fake = _FakeTushare(_all_rows())
    result = write_major_index_mins_raw_partition(
        lake_root_path=tmp_path,
        duckdb_resource=_MemoryDuckDB(),
        tushare=fake,
        source_freq="60min",
        partition_key="2026-08-04",
        run_id="p2-good",
        request_policy=_policy(),
    )

    target_path = raw_major_index_mins_path(tmp_path, "60min", "2026-08-04")
    assert result.write_mode == "staged_atomic_replace"
    assert result.target_path == target_path
    assert result.source_row_count == 50
    assert result.output_row_count == result.source_row_count
    assert result.request_count == result.expected_code_count
    assert target_path.exists()
    assert not result.staging_path.exists()

    with duckdb.connect(":memory:") as connection:
        description = connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?, hive_partitioning=false)",
            [str(target_path)],
        ).fetchall()
        rows = connection.execute(
            "SELECT ts_code, freq, trade_time "
            "FROM read_parquet(?, hive_partitioning=false) ORDER BY ts_code",
            [str(target_path)],
        ).fetchall()
    assert tuple(row[0] for row in description) == MAJOR_INDEX_MINS_SOURCE_COLUMNS
    assert all(row[1] == "60min" for row in rows)
    assert len(rows) == result.output_row_count


def test_writer_reuses_valid_existing_target_without_source_request(tmp_path: Path) -> None:
    write_major_index_mins_raw_partition(
        lake_root_path=tmp_path,
        duckdb_resource=_MemoryDuckDB(),
        tushare=_FakeTushare(_all_rows()),
        source_freq="60min",
        partition_key="2026-08-04",
        run_id="p2-first",
        request_policy=_policy(),
    )
    no_source = _FakeTushare({})
    result = write_major_index_mins_raw_partition(
        lake_root_path=tmp_path,
        duckdb_resource=_MemoryDuckDB(),
        tushare=no_source,
        source_freq="60min",
        partition_key="2026-08-04",
        run_id="p2-second",
        request_policy=_policy(),
    )
    assert result.write_mode == "reuse_existing"
    assert no_source.calls == []


def test_writer_rejects_invalid_existing_target_without_source_request(tmp_path: Path) -> None:
    target_path = raw_major_index_mins_path(tmp_path, "60min", "2026-08-04")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            "COPY (SELECT 'bad'::VARCHAR AS ts_code) TO ? (FORMAT PARQUET)",
            [str(target_path)],
        )
    no_source = _FakeTushare({})

    with pytest.raises(
        MajorIndexMinsRawValidationError,
        match="existing Raw target is invalid",
    ):
        write_major_index_mins_raw_partition(
            lake_root_path=tmp_path,
            duckdb_resource=_MemoryDuckDB(),
            tushare=no_source,
            source_freq="60min",
            partition_key="2026-08-04",
            run_id="p2-invalid-existing",
            request_policy=_policy(),
        )

    assert no_source.calls == []
    with duckdb.connect(":memory:") as connection:
        columns = connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?, hive_partitioning=false)",
            [str(target_path)],
        ).fetchall()
    assert tuple(row[0] for row in columns) == ("ts_code",)


def test_invalid_source_does_not_create_target_or_leave_staging(tmp_path: Path) -> None:
    with pytest.raises(MajorIndexMinsRawValidationError, match="source validation"):
        write_major_index_mins_raw_partition(
            lake_root_path=tmp_path,
            duckdb_resource=_MemoryDuckDB(),
            tushare=_FakeTushare(_all_rows(high=0.8)),
            source_freq="60min",
            partition_key="2026-08-04",
            run_id="p2-invalid-source",
            request_policy=_policy(),
        )
    assert not raw_major_index_mins_path(
        tmp_path,
        "60min",
        "2026-08-04",
    ).exists()
    assert not raw_major_index_mins_staging_path(
        tmp_path,
        "p2-invalid-source",
        "60min",
        "2026-08-04",
    ).exists()


def test_staging_readback_failure_does_not_create_target(tmp_path: Path) -> None:
    with patch(
        "orchestrator.defs.io.major_index_mins_raw_writer._raw_output_sql",
        return_value=(
            "SELECT * FROM major_index_mins_source "
            "WHERE ts_code <> '000001.SH' ORDER BY ts_code, trade_time"
        ),
    ), pytest.raises(MajorIndexMinsRawValidationError, match="staging validation"):
        write_major_index_mins_raw_partition(
            lake_root_path=tmp_path,
            duckdb_resource=_MemoryDuckDB(),
            tushare=_FakeTushare(_all_rows()),
            source_freq="60min",
            partition_key="2026-08-04",
            run_id="p2-invalid-staging",
            request_policy=_policy(),
        )
    assert not raw_major_index_mins_path(
        tmp_path,
        "60min",
        "2026-08-04",
    ).exists()
    assert not raw_major_index_mins_staging_path(
        tmp_path,
        "p2-invalid-staging",
        "60min",
        "2026-08-04",
    ).exists()


def test_daily_1min_shape_stays_within_local_writer_budget(tmp_path: Path) -> None:
    started_at = perf_counter()
    result = write_major_index_mins_raw_partition(
        lake_root_path=tmp_path,
        duckdb_resource=_MemoryDuckDB(),
        tushare=_FakeTushare(_daily_1min_rows()),
        source_freq="1min",
        partition_key="2026-08-04",
        run_id="p2-performance",
        request_policy=_policy(),
    )
    elapsed_seconds = perf_counter() - started_at

    assert result.output_row_count == 2_410
    assert result.request_count == 10
    assert result.page_count == 10
    assert elapsed_seconds < 10.0
