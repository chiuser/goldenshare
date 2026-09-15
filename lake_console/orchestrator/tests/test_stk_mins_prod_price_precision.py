"""Prod original-price normalization, without rewriting existing Lake facts."""

import duckdb
import pytest

from orchestrator.defs.assets import stk_mins


@pytest.mark.parametrize("freq", [1, 5, 15, 30, 60])
def test_prod_real_prices_are_normalized_before_raw_write(freq, tmp_path):
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            f"""
            CREATE TEMP TABLE prod_stk_mins_source AS SELECT
              '000001.SZ'::VARCHAR AS ts_code, {freq}::INTEGER AS freq,
              TIMESTAMP '2026-09-14 09:31:00' AS trade_time,
              11.74::FLOAT AS open, 11.80::FLOAT AS close,
              11.83::FLOAT AS high, 11.73::FLOAT AS low,
              3027087::BIGINT AS vol, 35655656.125::DOUBLE AS amount
            """
        )
        sql = stk_mins._prod_db_raw_stk_mins_output_sql(freq=freq)
        path = tmp_path / "normalized.parquet"
        connection.execute(f"COPY ({sql}) TO '{path}' (FORMAT PARQUET)")
        row = connection.execute(
            "SELECT open, close, high, low, vol, amount, vwap, exchange "
            "FROM read_parquet(?)", [str(path)]
        ).fetchone()
        assert row[:4] == (11.74, 11.80, 11.83, 11.73)
        assert row[4:6] == (3027087, 35655656.125)
        assert row[6] == 35655656.125 / 3027087
        assert row[7] == "XSHE"
        assert connection.execute(
            "SELECT close <= 11.80, open >= 11.74, typeof(close) "
            "FROM read_parquet(?)", [str(path)]
        ).fetchone() == (True, True, "DOUBLE")


def test_prod_normalization_preserves_null_and_zero():
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            """
            CREATE TEMP TABLE prod_stk_mins_source AS SELECT
              '600000.SH' AS ts_code, 1 AS freq,
              TIMESTAMP '2026-09-14 09:31:00' AS trade_time,
              NULL::DOUBLE AS open, NULL::DOUBLE AS close,
              0.0::DOUBLE AS high, 0.0::DOUBLE AS low,
              0::BIGINT AS vol, NULL::DOUBLE AS amount
            """
        )
        row = connection.execute(
            stk_mins._prod_db_raw_stk_mins_output_sql(freq=1)
        ).fetchone()
        assert row[3:9] == (None, None, 0.0, 0.0, 0, None)


def test_existing_raw_is_reused_without_reading_prod(tmp_path, monkeypatch):
    path = stk_mins.raw_stk_mins_path(tmp_path, 1, "2026-09-14")
    path.parent.mkdir(parents=True)
    path.write_bytes(b"existing file must not be rewritten")
    reused = object()
    monkeypatch.setattr(
        stk_mins, "_reuse_existing_raw_stk_mins_partition", lambda **kwargs: reused
    )
    result = stk_mins.write_raw_stk_mins_partition_from_prod_db(
        lake_root=tmp_path, duckdb=None, prod_postgres=None, freq=1,
        partition_key="2026-09-14", stock_codes=("000001.SZ",),
    )
    assert result is reused
    assert path.read_bytes() == b"existing file must not be rewritten"
