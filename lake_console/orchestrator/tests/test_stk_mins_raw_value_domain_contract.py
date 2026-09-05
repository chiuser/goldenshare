"""Preserve useful Raw samples when the obsolete migration audit is retired."""

from contextlib import nullcontext
from types import SimpleNamespace

import dagster as dg
import duckdb
import pytest

from orchestrator.defs.checks import stk_mins_checks
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.paths import raw_stk_mins_path
from orchestrator.defs.resources import DuckDBResource


@pytest.mark.parametrize(
    ("freq", "code", "time", "prices", "volume", "amount", "expected"),
    (
        (
            1,
            "600515.SH",
            "09:32:00",
            (5.83, 5.83, 5.83, 0.0, 5.83),
            10000,
            58300.0,
            True,
        ),
        (5, "000007.SZ", "09:35:00", (0.0, 0.0, 0.0, 0.0, 0.0), 0, 0.0, True),
        (
            1,
            "600515.SH",
            "09:32:00",
            (-1.0, 5.83, 5.83, 0.0, 5.83),
            10000,
            58300.0,
            False,
        ),
        (5, "000007.SZ", "09:35:00", (None, 0.0, 0.0, 0.0, 0.0), 0, 0.0, False),
    ),
    ids=("zero-low", "all-zero-quote", "negative-open", "null-open"),
)
def test_current_raw_value_domain_preserves_zero_policy(
    tmp_path, monkeypatch, freq, code, time, prices, volume, amount, expected
):
    def forbidden(*args, **kwargs):
        raise AssertionError("formal Dagster/network access is forbidden")

    monkeypatch.setattr(dg.DagsterInstance, "get", forbidden)
    monkeypatch.setattr("socket.socket.connect", forbidden)
    day = "2026-05-07"
    path = raw_stk_mins_path(tmp_path, freq, day)
    path.parent.mkdir(parents=True)
    # All SQL and check reads stay on one in-memory connection with temporary spill.
    with duckdb.connect(
        database=":memory:", config={"temp_directory": str(tmp_path / "spill")}
    ) as connection:
        connection.execute(
            """
            CREATE TABLE sample (
                ts_code VARCHAR, freq INTEGER, trade_time TIMESTAMP,
                open DOUBLE, close DOUBLE, high DOUBLE, low DOUBLE,
                vol BIGINT, amount DOUBLE, exchange VARCHAR, vwap DOUBLE
            )
            """
        )
        open_value, close, high, low, vwap = prices
        connection.execute(
            "INSERT INTO sample VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                code,
                freq,
                f"{day} {time}",
                open_value,
                close,
                high,
                low,
                volume,
                amount,
                None,
                vwap,
            ],
        )
        connection.execute(f"COPY sample TO {duckdb_string(path)} (FORMAT PARQUET)")
        monkeypatch.setattr(
            stk_mins_checks,
            "connect_configured_duckdb",
            lambda: nullcontext(connection),
        )
        result = stk_mins_checks._raw_value_domain_check(
            context=SimpleNamespace(partition_key=day),
            lake_root=SimpleNamespace(root=lambda: tmp_path),
            duckdb=DuckDBResource(),
            freq=freq,
        )
    assert result.passed is expected
    assert result.metadata["goldenshare/checked_row_count"].value == 1
    assert result.metadata["goldenshare/failed_row_count"].value == int(not expected)
    assert result.metadata["goldenshare/failed_rule_names"].value == (
        [] if expected else ["raw_stk_mins_price_volume_sanity"]
    )
