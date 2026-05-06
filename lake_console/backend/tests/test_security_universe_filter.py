from __future__ import annotations

from datetime import date

import pytest

from lake_console.backend.app.services.parquet_writer import write_rows_to_parquet
from lake_console.backend.app.services.security_universe_filter import SecurityUniverseError, load_security_universe_for_range


def test_security_universe_filters_by_lifecycle_overlap(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    _write_universe(
        tmp_path,
        [
            _stock("000001.SZ", "L", "20090105", None),
            _stock("000002.SZ", "D", "20060101", "20120601"),
            _stock("000003.SZ", "L", "20210315", None),
            _stock("000004.SZ", "D", "20050101", "20071231"),
            _stock("000005.SZ", "P", "20190510", "20200102"),
        ],
    )

    result = load_security_universe_for_range(
        lake_root=tmp_path,
        start_date=date(2009, 1, 1),
        end_date=date(2019, 12, 31),
    )

    assert result.ts_codes == ["000001.SZ", "000002.SZ", "000005.SZ"]
    assert result.total_symbols == 5
    assert result.selected_symbols == 3
    assert result.skipped_listed_after_range == 1
    assert result.skipped_delisted_before_range == 1
    assert result.selected_listed_symbols == 1
    assert result.selected_delisted_or_paused_symbols == 2


def test_security_universe_rejects_listed_stock_with_delist_date(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    _write_universe(tmp_path, [_stock("000001.SZ", "L", "20090105", "20190101")])

    with pytest.raises(SecurityUniverseError, match="list_status=L 但 delist_date 非空"):
        load_security_universe_for_range(
            lake_root=tmp_path,
            start_date=date(2009, 1, 1),
            end_date=date(2019, 12, 31),
        )


def test_security_universe_rejects_delisted_stock_without_delist_date(tmp_path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    _write_universe(tmp_path, [_stock("000001.SZ", "D", "20090105", None)])

    with pytest.raises(SecurityUniverseError, match="list_status=D 但 delist_date 为空"):
        load_security_universe_for_range(
            lake_root=tmp_path,
            start_date=date(2009, 1, 1),
            end_date=date(2019, 12, 31),
        )


def _stock(ts_code: str, list_status: str, list_date: str, delist_date: str | None) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "list_status": list_status,
        "list_date": list_date,
        "delist_date": delist_date,
    }


def _write_universe(root, rows: list[dict[str, object]]) -> None:
    write_rows_to_parquet(rows, root / "manifest" / "security_universe" / "tushare_stock_basic.parquet")
