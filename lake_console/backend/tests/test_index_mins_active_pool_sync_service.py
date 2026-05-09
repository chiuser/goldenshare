from __future__ import annotations

import pytest

from lake_console.backend.app.services.index_mins_active_pool_sync_service import IndexMinsActivePoolSyncService
from lake_console.backend.app.services.parquet_writer import read_parquet_rows


def test_sync_index_mins_active_pool_writes_local_manifest(tmp_path, monkeypatch) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")

    monkeypatch.setattr(
        "lake_console.backend.app.services.index_mins_active_pool_sync_service._fetch_active_pool_rows",
        lambda **_: [
            {"resource": "index_mins", "ts_code": "000001.SH"},
            {"resource": "index_mins", "ts_code": "000300.SH"},
        ],
    )

    summary = IndexMinsActivePoolSyncService(
        lake_root=tmp_path,
        database_url="postgresql://unused",
        progress=lambda _: None,
    ).sync()

    rows = read_parquet_rows(
        tmp_path / "manifest" / "index_universe" / "index_mins_active_pool.parquet"
    )
    assert summary["operation"] == "sync_index_mins_active_pool"
    assert summary["written_rows"] == 2
    assert rows == [
        {"resource": "index_mins", "ts_code": "000001.SH"},
        {"resource": "index_mins", "ts_code": "000300.SH"},
    ]
