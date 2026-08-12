from __future__ import annotations

from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

from src.scripts.audit_index_minute_gold import (  # noqa: E402
    READY,
    SOURCE_NOT_READY,
    SOURCE_NOT_READY_CODE,
    run_gold_acceptance,
)


def _write_fixture(root: Path, *, dataset: str) -> None:
    if dataset == "silver":
        target = root / (
            "silver/quote/major_index_mins/freq=5min/"
            "trade_date=2026-08-11/part-000.parquet"
        )
        create_sql = """
            CREATE TABLE fixture (
              ts_code VARCHAR, freq VARCHAR, trade_time TIMESTAMP,
              open DOUBLE, close DOUBLE, high DOUBLE, low DOUBLE,
              vol DOUBLE, amount DOUBLE, exchange VARCHAR, vwap DOUBLE
            )
        """
        insert_sql = """
            INSERT INTO fixture VALUES (
              '000001.SH', '5min', TIMESTAMP '2026-08-11 09:35:00',
              1, 1.1, 1.2, .9, 10, 100, 'SSE', 1.05
            )
        """
    else:
        target = root / (
            "gold/indicator/major_index_mins_technical/freq=5/"
            "trade_date=2026-08-11/part-000.parquet"
        )
        create_sql = """
            CREATE TABLE fixture (
              ts_code VARCHAR, freq SMALLINT, trade_date DATE, trade_time TIMESTAMP,
              ma_5 DOUBLE, ma_10 DOUBLE, ma_20 DOUBLE, ma_30 DOUBLE,
              ma_60 DOUBLE, ma_90 DOUBLE, ma_250 DOUBLE,
              boll_mid DOUBLE, boll_upper DOUBLE, boll_lower DOUBLE,
              macd_dif DOUBLE, macd_dea DOUBLE, macd DOUBLE,
              kdj_k DOUBLE, kdj_d DOUBLE, kdj_j DOUBLE,
              observation_count INTEGER, params_key VARCHAR, indicator_version INTEGER
            )
        """
        insert_sql = """
            INSERT INTO fixture VALUES (
              '000001.SH', 5, DATE '2026-08-11', TIMESTAMP '2026-08-11 09:35:00',
              NULL, NULL, NULL, NULL, NULL, NULL, NULL,
              NULL, NULL, NULL, 0, 0, 0, 50, 50, 50, 1,
              'ma_5_10_20_30_60_90_250__boll_20_2__macd_12_26_9__kdj_9_3_3', 1
            )
        """
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(create_sql)
        connection.execute(insert_sql)
        connection.execute("COPY fixture TO ? (FORMAT PARQUET)", [str(target)])
    finally:
        connection.close()


def test_gold_acceptance_reports_source_not_ready_without_gold_files(
    tmp_path: Path,
) -> None:
    _write_fixture(tmp_path, dataset="silver")

    result = run_gold_acceptance(
        lake_root=tmp_path,
        ts_codes=("000001.SH",),
        frequencies=(5,),
        runs=1,
    )

    assert result["status"] == SOURCE_NOT_READY
    assert result["code"] == SOURCE_NOT_READY_CODE
    assert result["readOnly"] is True
    assert result["performance"] is None


def test_gold_acceptance_checks_alignment_and_query_service_performance(
    tmp_path: Path,
) -> None:
    _write_fixture(tmp_path, dataset="silver")
    _write_fixture(tmp_path, dataset="gold")

    result = run_gold_acceptance(
        lake_root=tmp_path,
        ts_codes=("000001.SH",),
        frequencies=(5,),
        runs=1,
        full_alignment=True,
    )

    assert result["status"] == READY
    assert result["code"] is None
    assert result["frequencies"][0]["checkedPartitionCount"] == 1
    assert result["frequencies"][0]["alignmentFailures"] == []
    assert result["performance"]["status"] == READY
    assert result["performance"]["frequencies"][0]["sampleCount"] == 1
