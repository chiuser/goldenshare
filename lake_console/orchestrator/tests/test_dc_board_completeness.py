from pathlib import Path

import duckdb

from orchestrator.defs.asset_guards.dc_board_relations import audit_raw_board_relation


def _write_codes(path: Path, codes: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if "dc_index" in str(path):
        values = ", ".join(
            f"('{code}', '行业板块', '板块', '股票', '000001.SZ', 1.0, 2.0, 3.0, 4.0, 5, 6)"
            for code in codes
        )
        query = f"""
            COPY (
                SELECT * FROM (VALUES {values}) AS t(
                    ts_code, idx_type, name, "leading", leading_code,
                    pct_change, leading_pct, total_mv, turnover_rate, up_num, down_num
                )
            ) TO '{path}' (FORMAT PARQUET)
        """
    else:
        values = ", ".join(f"('{code}')" for code in codes)
        query = f"COPY (SELECT * FROM (VALUES {values}) AS t(ts_code)) TO '{path}' (FORMAT PARQUET)"
    with duckdb.connect(":memory:") as connection:
        connection.execute(query)


def test_member_relation_reports_codes_outside_same_day_index(tmp_path):
    root = Path(tmp_path)
    source = root / "raw/board/dc_member/trade_date=2026-07-14/part-000.parquet"
    index = root / "raw/board/dc_index/trade_date=2026-07-14/part-000.parquet"
    _write_codes(source, ("BK0001.DC", "BK0002.DC"))
    _write_codes(index, ("BK0001.DC",))

    with duckdb.connect(":memory:") as connection:
        count, samples = audit_raw_board_relation(
            connection,
            source_path=source,
            index_path=index,
            mode="member_subset_index",
        )
    assert count == 1
    assert samples == (
        {"ts_code": "BK0002.DC", "reason_code": "member_code_not_in_index"},
    )


def test_daily_relation_allows_source_codes_beyond_same_day_index(tmp_path):
    root = Path(tmp_path)
    source = root / "raw/board/dc_daily/trade_date=2026-07-14/part-000.parquet"
    index = root / "raw/board/dc_index/trade_date=2026-07-14/part-000.parquet"
    _write_codes(source, ("BK0001.DC", "BK0002.DC"))
    _write_codes(index, ("BK0001.DC",))

    with duckdb.connect(":memory:") as connection:
        count, samples = audit_raw_board_relation(
            connection,
            source_path=source,
            index_path=index,
            mode="index_subset_daily",
        )
    assert count == 0
    assert samples == ()


def test_daily_relation_reports_index_code_missing_from_daily(tmp_path):
    root = Path(tmp_path)
    source = root / "raw/board/dc_daily/trade_date=2026-07-14/part-000.parquet"
    index = root / "raw/board/dc_index/trade_date=2026-07-14/part-000.parquet"
    _write_codes(source, ("BK0001.DC", "BK0002.DC"))
    _write_codes(index, ("BK0001.DC", "BK0003.DC"))

    with duckdb.connect(":memory:") as connection:
        count, samples = audit_raw_board_relation(
            connection,
            source_path=source,
            index_path=index,
            mode="index_subset_daily",
        )
    assert count == 1
    assert samples == (
        {"ts_code": "BK0003.DC", "reason_code": "index_code_missing_from_daily"},
    )


def test_daily_relation_ignores_exact_index_placeholder(tmp_path):
    root = Path(tmp_path)
    source = root / "raw/board/dc_daily/trade_date=2026-07-14/part-000.parquet"
    index = root / "raw/board/dc_index/trade_date=2026-07-14/part-000.parquet"
    _write_codes(source, ("BK0001.DC",))
    index.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            f"""
            COPY (
                SELECT * FROM (VALUES
                    ('BK0001.DC', '板块一', '股票一', '000001.SZ', 1.0, 2.0, 3.0, 4.0, 5, 6),
                    ('BK1675.DC', '历史新高', '-', NULL, 0.0, 0.0, 0.0, 0.0, NULL, NULL)
                ) AS t(ts_code, name, "leading", leading_code, pct_change,
                       leading_pct, total_mv, turnover_rate, up_num, down_num)
            ) TO '{index}' (FORMAT PARQUET)
            """
        )

    with duckdb.connect(":memory:") as connection:
        count, samples = audit_raw_board_relation(
            connection,
            source_path=source,
            index_path=index,
            mode="index_subset_daily",
        )
    assert count == 0
    assert samples == ()


def test_removed_daily_equality_mode_is_rejected(tmp_path):
    root = Path(tmp_path)
    source = root / "raw/board/dc_daily/trade_date=2026-07-14/part-000.parquet"
    index = root / "raw/board/dc_index/trade_date=2026-07-14/part-000.parquet"
    _write_codes(source, ("BK0001.DC",))
    _write_codes(index, ("BK0001.DC",))

    with duckdb.connect(":memory:") as connection:
        try:
            audit_raw_board_relation(
                connection,
                source_path=source,
                index_path=index,
                mode="daily_equals_index",
            )
        except ValueError as exc:
            assert str(exc) == "unknown board relation mode: daily_equals_index"
        else:
            raise AssertionError("removed equality relation mode must fail closed")
