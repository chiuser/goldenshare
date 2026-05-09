from __future__ import annotations

from datetime import date

import pytest

from lake_console.backend.app.services.index_mins_universe_filter import (
    IndexMinsUniverseError,
    load_index_mins_universe_for_range,
)
from lake_console.backend.app.services.parquet_writer import write_rows_to_parquet


def test_index_mins_universe_filter_applies_lifecycle_window(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")

    _write_active_pool(
        tmp_path,
        [
            {"resource": "index_mins", "ts_code": "000001.SH"},
            {"resource": "index_mins", "ts_code": "000002.SH"},
            {"resource": "index_mins", "ts_code": "000003.SH"},
        ],
    )
    _write_index_basic(
        tmp_path,
        [
            _index_basic("000001.SH", "20000101", None),
            _index_basic("000002.SH", "20260110", None),
            _index_basic("000003.SH", "20050101", "20251231"),
        ],
    )

    result = load_index_mins_universe_for_range(
        lake_root=tmp_path,
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 31),
    )

    assert result.ts_codes == ["000001.SH", "000002.SH"]
    assert result.total_candidates == 3
    assert result.selected_candidates == 2
    assert result.skipped_listed_after_range == 0
    assert result.skipped_expired_before_range == 1
    assert result.is_effective_on(ts_code="000001.SH", trade_date=date(2026, 1, 5)) is True
    assert result.is_effective_on(ts_code="000002.SH", trade_date=date(2026, 1, 5)) is False
    assert result.is_effective_on(ts_code="000002.SH", trade_date=date(2026, 1, 10)) is True
    assert result.effective_code_count_on(trade_date=date(2026, 1, 5)) == 1
    assert result.effective_code_count_on(trade_date=date(2026, 1, 10)) == 2


def test_index_mins_universe_filter_rejects_ts_code_outside_active_pool(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")

    _write_active_pool(tmp_path, [{"resource": "index_mins", "ts_code": "000001.SH"}])
    _write_index_basic(tmp_path, [_index_basic("000001.SH", "20000101", None)])

    with pytest.raises(IndexMinsUniverseError, match="不在本地 active pool"):
        load_index_mins_universe_for_range(
            lake_root=tmp_path,
            start_date=date(2026, 1, 5),
            end_date=date(2026, 1, 5),
            ts_code="000300.SH",
        )


def test_index_mins_universe_filter_ignores_irrelevant_invalid_index_basic_rows(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")

    _write_active_pool(tmp_path, [{"resource": "index_mins", "ts_code": "000001.SH"}])
    _write_index_basic(
        tmp_path,
        [
            _index_basic("000001.SH", "20000101", None),
            _index_basic("000124.SH", float("nan"), None),
        ],
    )

    result = load_index_mins_universe_for_range(
        lake_root=tmp_path,
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 5),
    )

    assert result.ts_codes == ["000001.SH"]
    assert result.selected_candidates == 1


def _index_basic(ts_code: str, list_date: str, exp_date: str | None) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "name": ts_code,
        "market": "SSE",
        "publisher": "CSI",
        "category": "规模指数",
        "list_date": list_date,
        "exp_date": exp_date,
    }


def _write_active_pool(root, rows: list[dict[str, object]]) -> None:
    write_rows_to_parquet(rows, root / "manifest" / "index_universe" / "index_mins_active_pool.parquet")


def _write_index_basic(root, rows: list[dict[str, object]]) -> None:
    write_rows_to_parquet(rows, root / "manifest" / "index_universe" / "tushare_index_basic.parquet")
