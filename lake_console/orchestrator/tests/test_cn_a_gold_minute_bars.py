from __future__ import annotations

from time import perf_counter

import duckdb
import pytest

from orchestrator.defs.io.cn_a_gold_minute_bars import (
    audit_canonical_gold_minute_relation,
    build_canonical_gold_minute_select_sql,
)


def _source_relation(rows: tuple[tuple[object, ...], ...]) -> str:
    values = ",\n".join(
        "("
        + ", ".join(
            f"'{value}'" if isinstance(value, str) else str(value) for value in row
        )
        + ")"
        for row in rows
    )
    return f"""
    SELECT
      CAST(ts_code AS VARCHAR) AS ts_code,
      CAST(freq AS VARCHAR) AS freq,
      CAST(trade_time AS TIMESTAMP) AS trade_time,
      CAST(open AS DOUBLE) AS open,
      CAST(high AS DOUBLE) AS high,
      CAST(low AS DOUBLE) AS low,
      CAST(close AS DOUBLE) AS close,
      CAST(vol AS DOUBLE) AS vol,
      CAST(amount AS DOUBLE) AS amount,
      CAST(exchange AS VARCHAR) AS exchange,
      CAST(vwap AS DOUBLE) AS vwap
    FROM (VALUES {values}) rows(
      ts_code, freq, trade_time, open, high, low, close,
      vol, amount, exchange, vwap
    )
    """


def test_one_minute_preserves_0930_and_excludes_all_post_close_rows() -> None:
    source_sql = _source_relation(
        (
            (
                "000001.SH",
                "1min",
                "2026-08-12 09:30:00",
                90,
                120,
                80,
                100,
                10,
                1000,
                "SSE",
                95,
            ),
            (
                "000001.SH",
                "1min",
                "2026-08-12 15:00:00",
                105,
                108,
                104,
                107,
                4,
                400,
                "SSE",
                106,
            ),
            (
                "000001.SH",
                "1min",
                "2026-08-12 15:01:00",
                107,
                109,
                106,
                108,
                3,
                300,
                "SSE",
                108,
            ),
            (
                "000001.SH",
                "1min",
                "2026-08-12 15:30:00",
                108,
                110,
                107,
                109,
                2,
                200,
                "SSE",
                109,
            ),
        )
    )
    sql = build_canonical_gold_minute_select_sql(
        source_relation_sql=source_sql,
        target_freq=1,
        partition_key="2026-08-12",
        price_basis_relation_sql=None,
    )

    with duckdb.connect() as connection:
        rows = connection.execute(sql).fetchall()

    comparable_rows = [
        (row[0], row[1], row[2].isoformat(), row[3].isoformat(sep=" "), *row[4:])
        for row in rows
    ]
    assert comparable_rows == [
        (
            "000001.SH",
            1,
            "2026-08-12",
            "2026-08-12 09:30:00",
            90.0,
            120.0,
            80.0,
            100.0,
            10.0,
            1000.0,
            "SSE",
            95.0,
        ),
        (
            "000001.SH",
            1,
            "2026-08-12",
            "2026-08-12 15:00:00",
            105.0,
            108.0,
            104.0,
            107.0,
            4.0,
            400.0,
            "SSE",
            106.0,
        ),
    ]


def test_five_minute_first_bar_uses_anchor_close_once_and_applies_price_basis() -> None:
    source_sql = _source_relation(
        (
            (
                "000001.SH",
                "1min",
                "2026-08-12 09:30:00",
                90,
                120,
                80,
                100,
                10,
                1000,
                "SSE",
                95,
            ),
            (
                "000001.SH",
                "1min",
                "2026-08-12 09:31:00",
                101,
                103,
                99,
                102,
                1,
                10,
                "SSE",
                101,
            ),
            (
                "000001.SH",
                "1min",
                "2026-08-12 09:32:00",
                102,
                104,
                100,
                103,
                1,
                10,
                "SSE",
                102,
            ),
            (
                "000001.SH",
                "1min",
                "2026-08-12 09:33:00",
                103,
                105,
                101,
                104,
                1,
                10,
                "SSE",
                103,
            ),
            (
                "000001.SH",
                "1min",
                "2026-08-12 09:34:00",
                104,
                106,
                102,
                105,
                1,
                10,
                "SSE",
                104,
            ),
            (
                "000001.SH",
                "1min",
                "2026-08-12 09:35:00",
                105,
                107,
                103,
                106,
                1,
                10,
                "SSE",
                105,
            ),
            (
                "000001.SH",
                "1min",
                "2026-08-12 15:30:00",
                999,
                999,
                999,
                999,
                999,
                999,
                "SSE",
                999,
            ),
        )
    )
    price_basis_sql = """
    SELECT '000001.SH'::VARCHAR AS ts_code,
           DATE '2026-08-12' AS trade_date,
           2.0::DOUBLE AS price_multiplier
    """
    sql = build_canonical_gold_minute_select_sql(
        source_relation_sql=source_sql,
        target_freq=5,
        partition_key="2026-08-12",
        price_basis_relation_sql=price_basis_sql,
    )

    with duckdb.connect() as connection:
        rows = connection.execute(sql).fetchall()

    comparable_rows = [
        (row[0], row[1], row[2].isoformat(), row[3].isoformat(sep=" "), *row[4:])
        for row in rows
    ]
    assert comparable_rows == [
        (
            "000001.SH",
            5,
            "2026-08-12",
            "2026-08-12 09:35:00",
            200.0,
            214.0,
            198.0,
            212.0,
            15.0,
            1050.0,
            "SSE",
            None,
        ),
    ]


@pytest.mark.parametrize(
    (
        "target_freq",
        "source_freq",
        "regular_times",
        "target_time",
        "expected_high",
        "expected_close",
        "expected_vol",
        "expected_amount",
    ),
    (
        (
            15,
            "5min",
            ("09:35:00", "09:40:00", "09:45:00"),
            "09:45:00",
            113.0,
            108.0,
            16.0,
            1600.0,
        ),
        (
            30,
            "5min",
            ("09:35:00", "09:40:00", "09:45:00", "09:50:00", "09:55:00", "10:00:00"),
            "10:00:00",
            116.0,
            111.0,
            31.0,
            3100.0,
        ),
        (60, "30min", ("10:00:00", "10:30:00"), "10:30:00", 112.0, 107.0, 13.0, 1300.0),
        (
            90,
            "30min",
            ("10:00:00", "10:30:00", "11:00:00"),
            "11:00:00",
            113.0,
            108.0,
            16.0,
            1600.0,
        ),
        (
            120,
            "60min",
            ("10:30:00", "11:30:00"),
            "11:30:00",
            112.0,
            107.0,
            13.0,
            1300.0,
        ),
    ),
)
def test_non_one_minute_first_bar_matches_literal_ohlcv_golden(
    target_freq: int,
    source_freq: str,
    regular_times: tuple[str, ...],
    target_time: str,
    expected_high: float,
    expected_close: float,
    expected_vol: float,
    expected_amount: float,
) -> None:
    rows: list[tuple[object, ...]] = [
        (
            "000001.SH",
            source_freq,
            "2026-08-12 09:30:00",
            90,
            120,
            80,
            100,
            10,
            1000,
            "SSE",
            95,
        )
    ]
    rows.extend(
        (
            "000001.SH",
            source_freq,
            f"2026-08-12 {source_time}",
            100 + index,
            110 + index,
            90 + index,
            105 + index,
            index,
            100 * index,
            "SSE",
            100 + index,
        )
        for index, source_time in enumerate(regular_times, start=1)
    )
    sql = build_canonical_gold_minute_select_sql(
        source_relation_sql=_source_relation(tuple(rows)),
        target_freq=target_freq,
        partition_key="2026-08-12",
        price_basis_relation_sql=None,
    )

    with duckdb.connect() as connection:
        result = connection.execute(sql).fetchall()

    comparable = [
        (row[0], row[1], row[3].isoformat(sep=" "), *row[4:]) for row in result
    ]
    assert comparable == [
        (
            "000001.SH",
            target_freq,
            f"2026-08-12 {target_time}",
            100.0,
            expected_high,
            91.0,
            expected_close,
            expected_vol,
            expected_amount,
            "SSE",
            None,
        )
    ]


@pytest.mark.parametrize(
    "invalid_case",
    ("missing_anchor", "duplicate_anchor", "missing_regular", "duplicate_regular"),
)
def test_incomplete_or_duplicate_first_window_fails_closed(invalid_case: str) -> None:
    rows = (
        (
            "000001.SH",
            "1min",
            "2026-08-12 09:30:00",
            90,
            120,
            80,
            100,
            10,
            1000,
            "SSE",
            95,
        ),
        (
            "000001.SH",
            "1min",
            "2026-08-12 09:31:00",
            101,
            111,
            91,
            106,
            1,
            100,
            "SSE",
            101,
        ),
        (
            "000001.SH",
            "1min",
            "2026-08-12 09:32:00",
            102,
            112,
            92,
            107,
            2,
            200,
            "SSE",
            102,
        ),
        (
            "000001.SH",
            "1min",
            "2026-08-12 09:33:00",
            103,
            113,
            93,
            108,
            3,
            300,
            "SSE",
            103,
        ),
        (
            "000001.SH",
            "1min",
            "2026-08-12 09:34:00",
            104,
            114,
            94,
            109,
            4,
            400,
            "SSE",
            104,
        ),
        (
            "000001.SH",
            "1min",
            "2026-08-12 09:35:00",
            105,
            115,
            95,
            110,
            5,
            500,
            "SSE",
            105,
        ),
    )
    invalid_rows = {
        "missing_anchor": rows[1:],
        "duplicate_anchor": (rows[0], *rows),
        "missing_regular": rows[:-1],
        "duplicate_regular": (*rows, rows[-1]),
    }[invalid_case]
    sql = build_canonical_gold_minute_select_sql(
        source_relation_sql=_source_relation(tuple(invalid_rows)),
        target_freq=5,
        partition_key="2026-08-12",
        price_basis_relation_sql=None,
    )

    with duckdb.connect() as connection:
        result = connection.execute(sql).fetchall()

    assert result == []


def test_relation_audit_reports_missing_duplicate_and_forbidden_times() -> None:
    relation_sql = """
    SELECT * FROM (VALUES
      ('000001.SH', 5, DATE '2026-08-12', TIMESTAMP '2026-08-12 09:30:00', 1.0::DOUBLE, 1.0::DOUBLE, 1.0::DOUBLE, 1.0::DOUBLE, 1.0::DOUBLE, 1.0::DOUBLE, 'SSE', NULL::DOUBLE),
      ('000001.SH', 5, DATE '2026-08-12', TIMESTAMP '2026-08-12 09:30:00', 1.0::DOUBLE, 1.0::DOUBLE, 1.0::DOUBLE, 1.0::DOUBLE, 1.0::DOUBLE, 1.0::DOUBLE, 'SSE', NULL::DOUBLE),
      ('000001.SH', 5, DATE '2026-08-12', TIMESTAMP '2026-08-12 15:30:00', 1.0::DOUBLE, 1.0::DOUBLE, 1.0::DOUBLE, 1.0::DOUBLE, 1.0::DOUBLE, 1.0::DOUBLE, 'SSE', NULL::DOUBLE)
    ) rows(ts_code, freq, trade_date, trade_time, open, high, low, close, vol, amount, exchange, vwap)
    """
    with duckdb.connect() as connection:
        audit = audit_canonical_gold_minute_relation(
            connection,
            relation_sql=relation_sql,
            target_freq=5,
            partition_key="2026-08-12",
            expected_codes=("000001.SH",),
        )

    assert not audit.ready
    assert audit.duplicate_key_count == 1
    assert audit.non_1m_0930_row_count == 2
    assert audit.post_close_row_count == 1
    assert audit.missing_key_count == 48
    assert audit.unexpected_key_count == 2


def test_set_based_530_code_fixture_stays_within_p1_budget() -> None:
    source_sql = """
    WITH codes AS (
      SELECT printf('%06d.SH', code_id)::VARCHAR AS ts_code
      FROM range(1, 531) ids(code_id)
    ), source_times AS (
      SELECT TIMESTAMP '2026-08-12 09:30:00' + i * INTERVAL 1 MINUTE AS trade_time
      FROM range(0, 121) morning(i)
      UNION ALL
      SELECT TIMESTAMP '2026-08-12 13:00:00' + i * INTERVAL 1 MINUTE AS trade_time
      FROM range(1, 121) afternoon(i)
    )
    SELECT
      codes.ts_code,
      '1min'::VARCHAR AS freq,
      source_times.trade_time,
      10.0::DOUBLE AS open,
      11.0::DOUBLE AS high,
      9.0::DOUBLE AS low,
      10.5::DOUBLE AS close,
      1.0::DOUBLE AS vol,
      10.0::DOUBLE AS amount,
      'SSE'::VARCHAR AS exchange,
      10.25::DOUBLE AS vwap
    FROM codes CROSS JOIN source_times
    """
    sql = build_canonical_gold_minute_select_sql(
        source_relation_sql=source_sql,
        target_freq=5,
        partition_key="2026-08-12",
        price_basis_relation_sql=None,
    )
    expected_codes = tuple(f"{code_id:06d}.SH" for code_id in range(1, 531))

    started_at = perf_counter()
    with duckdb.connect() as connection:
        connection.execute("PRAGMA threads=1")
        audit = audit_canonical_gold_minute_relation(
            connection,
            relation_sql=sql,
            target_freq=5,
            partition_key="2026-08-12",
            expected_codes=expected_codes,
        )
    elapsed_ms = (perf_counter() - started_at) * 1000

    assert audit.ready
    assert audit.row_count == 530 * 48
    assert elapsed_ms < 5_000
