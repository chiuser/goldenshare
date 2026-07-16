from pathlib import Path

import duckdb

from orchestrator.defs.asset_guards.dc_board_relations import audit_raw_board_relation


def _write_codes(path: Path, codes: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    values = ", ".join(f"('{code}')" for code in codes)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            f"COPY (SELECT * FROM (VALUES {values}) AS t(ts_code)) TO '{path}' (FORMAT PARQUET)"
        )


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


def test_daily_relation_requires_exact_same_day_index_code_set(tmp_path):
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
            mode="daily_equals_index",
        )
    assert count == 2
    assert {row["reason_code"] for row in samples} == {
        "source_not_in_index",
        "index_not_in_source",
    }
